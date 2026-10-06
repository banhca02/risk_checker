"""Deterministic cross-document validation for Commercial Invoice, Packing
List and Bill of Lading (Import Document Risk Checker).

Implements rules R01-R26 from docs/SPEC_EXTRACTION_AND_VALIDATION.md.
This module never uses an LLM. Findings are risk flags for human review,
not a fraud verdict.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
from typing import Any, Optional
import re


# ---------------------------------------------------------------------------
# Tunables — all thresholds confirmed in the spec (mục 6, 10/5/2026).
# ---------------------------------------------------------------------------
WEIGHT_TOLERANCE_RATIO = 0.001       # 0.1% — must stay < 0.43% (seeded R08 gap)
MEASUREMENT_TOLERANCE_RATIO = 0.001  # 0.1% (R25)
MONEY_ABS_TOLERANCE = Decimal("0.01")
NAME_REVIEW_THRESHOLD = 0.70         # R04 names (đã chốt: cả 2 ngưỡng = 0.70)
ADDRESS_REVIEW_THRESHOLD = 0.70      # R04 addresses

# Optional place aliases: normalized key -> normalized canonical (R13/R14).
PORT_ALIASES: dict[str, str] = {}

# Canonical document keys (lowercase, matches DocumentType enum values).
CI = "commercial_invoice"
PL = "packing_list"
BL = "bill_of_lading"
REQUIRED_DOCS = (CI, PL, BL)

DOC_LABEL = {
    CI: "Commercial Invoice (CI)",
    PL: "Packing List (PL)",
    BL: "Bill of Lading (BL)",
}

# Normalized field -> {doc prefix: actual field name} (from the matrix).
FIELD_MAPPING = {
    "invoice_no":     {"CI": "invoice_no",     "PL": "invoice_reference_no"},
    "seller_name":    {"CI": "seller_name",    "PL": "seller_name",    "BL": "shipper_name"},
    "seller_address": {"CI": "seller_address", "PL": "seller_address", "BL": "shipper_address"},
    "buyer_name":     {"CI": "buyer_name",     "PL": "buyer_name",     "BL": "consignee_name"},
    "buyer_address":  {"CI": "buyer_address",  "PL": "buyer_address",  "BL": "consignee_address"},
}

# R24 — configured date relations. REL-3 (invoice <= shipped) ĐÃ CHỐT BỎ.
# (id, left (doc, field), right (doc, field), operator, severity, status)
DATE_RELATIONS = [
    ("REL-1", (CI, "invoice_date"), (PL, "reference_date"), "==", "MEDIUM", "FAIL"),
    ("REL-2", (BL, "issue_date"), (BL, "shipped_on_board_date"), ">=", "MEDIUM", "REVIEW"),
]

# R02 — required fields per document type: (field, critical -> HIGH else MEDIUM).
REQUIRED_FIELDS: dict[str, list[tuple[str, bool]]] = {
    CI: [
        ("invoice_no", True), ("invoice_date", True), ("seller_name", True),
        ("buyer_name", True), ("total_amount", True), ("items", True),
        ("seller_address", False), ("buyer_address", False), ("currency", False),
        ("port_of_loading", False), ("port_of_discharge", False),
        ("total_quantity", False), ("total_package_unit", False),
        ("total_net_weight", False), ("total_gross_weight", False),
    ],
    PL: [
        ("invoice_reference_no", True), ("reference_date", True),
        ("buyer_name", True), ("items", True),
        ("seller_name", False), ("seller_address", False), ("buyer_address", False),
        ("total_packages", False), ("total_package_unit", False),
        ("total_net_weight", False), ("total_gross_weight", False),
    ],
    BL: [
        ("bl_no", True), ("shipped_on_board_date", True),
        ("shipper_name", True), ("consignee_name", True), ("containers", True),
        ("shipper_address", False), ("consignee_address", False),
        ("port_of_loading", False), ("port_of_discharge", False),
        ("total_packages", False), ("total_package_unit", False),
        ("total_gross_weight", False),
    ],
}


@dataclass
class Finding:
    rule_id: str
    severity: str  # HIGH, MEDIUM, LOW
    status: str    # FAIL, REVIEW, PASS
    message: str
    documents: list[str]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------
_ENTITY_SUFFIXES = {"co", "corp", "company", "ltd", "limited", "llc", "jsc", "pte"}

_DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y")


def _value(doc: dict[str, Any] | None, key: str, default=None):
    if not doc:
        return default
    value = doc.get(key, default)
    # Support both plain values and {"value": ..., "evidence": [...]} wrappers.
    if isinstance(value, dict) and "value" in value:
        return value.get("value", default)
    return value


def _number(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float, Decimal)):
            return Decimal(str(value))
        cleaned = re.sub(r"[^0-9,.-]", "", str(value)).strip()
        if not cleaned:
            return None
        # Support both "," and "." as thousands/decimal separators.
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(",", "") if cleaned.rfind(".") > cleaned.rfind(",") else cleaned.replace(".", "").replace(",", ".")
        elif "," in cleaned:
            tail = cleaned.rsplit(",", 1)[-1]
            cleaned = cleaned.replace(",", ".") if len(tail) <= 2 else cleaned.replace(",", "")
        elif "." in cleaned:
            tail = cleaned.rsplit(".", 1)[-1]
            if len(tail) > 2:
                cleaned = cleaned.replace(".", "")
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _norm_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def _norm_id(value: Any) -> str:
    """Whitespace-free uppercase key for ids (invoice, container, seal, batch)."""
    return re.sub(r"\s+", "", str(value or "")).upper()


def _norm_entity(value: Any) -> str:
    """casefold + strip punctuation + drop legal-entity suffix tokens (R04)."""
    text = re.sub(r"[.,()]", " ", _norm_text(value))
    return " ".join(t for t in text.split() if t not in _ENTITY_SUFFIXES)


def _norm_unit(value: Any) -> str:
    """kg/kgs -> kg, drums -> drum, m3 -> cbm (lowercase)."""
    text = _norm_text(value)
    if text in {"m3", "m³"}:
        return "cbm"
    if text.endswith("s") and len(text) > 1:
        text = text[:-1]
    return text


def _norm_place(value: Any) -> str:
    """Port/location key: casefold, drop punctuation, apply alias map."""
    text = re.sub(r"[.,;:]", " ", _norm_text(value))
    text = re.sub(r"\s+", " ", text).strip()
    return PORT_ALIASES.get(text, text)


def _similar(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _within_ratio(a: Optional[Decimal], b: Optional[Decimal], tol: float) -> bool:
    """Relative tolerance: |a-b| <= tol * max(|a|,|b|). Missing value -> True."""
    if a is None or b is None:
        return True
    hi = max(abs(a), abs(b))
    if hi == 0:
        return True
    return abs(a - b) <= Decimal(str(tol)) * hi


def _norm_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _doc_type(doc: dict[str, Any] | None) -> str:
    return str(_value(doc, "document_type", "unknown") or "unknown").lower()


def _items(doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    value = _value(doc, "items", []) or []
    return [i for i in value if isinstance(i, dict)] if isinstance(value, list) else []


def _containers_bl(bl: dict[str, Any] | None) -> list[dict[str, Any]]:
    value = _value(bl, "containers", []) or []
    return [c for c in value if isinstance(c, dict)] if isinstance(value, list) else []


def _containers_pl(pl: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Container Summary when present, otherwise grouped PL items (spec §1.3)."""
    summary = _value(pl, "container_summary", []) or []
    summary = [c for c in summary if isinstance(c, dict) and _norm_id(c.get("container_no"))]
    if summary:
        return summary
    groups: dict[str, dict[str, Any]] = {}
    for item in _items(pl):
        cid = _norm_id(item.get("container_no"))
        if not cid:
            continue
        g = groups.setdefault(cid, {
            "container_no": item.get("container_no"),
            "seal_no": item.get("seal_no"),
            "package_unit": item.get("package_unit"),
            "quantity": Decimal(0), "net_weight": Decimal(0), "gross_weight": Decimal(0),
            "_has_qty": False, "_has_net": False, "_has_gross": False,
        })
        q = _number(item.get("quantity"))
        if q is not None:
            g["quantity"] += q
            g["_has_qty"] = True
        n = _number(item.get("net_weight"))
        if n is not None:
            g["net_weight"] += n
            g["_has_net"] = True
        gr = _number(item.get("gross_weight"))
        if gr is not None:
            g["gross_weight"] += gr
            g["_has_gross"] = True
        if not g.get("seal_no"):
            g["seal_no"] = item.get("seal_no")
    return list(groups.values())


def _src(doc_type: str, doc: dict[str, Any], field: str) -> dict[str, Any]:
    """Evidence entry: value + page/quote from field_evidence when available."""
    out: dict[str, Any] = {"document": doc_type, "value": _value(doc, field)}
    evidence_map = _value(doc, "field_evidence", {}) or {}
    entries = evidence_map.get(field) or []
    if entries and isinstance(entries[0], dict):
        if entries[0].get("page") is not None:
            out["page"] = entries[0]["page"]
        if entries[0].get("quote"):
            out["quote"] = str(entries[0]["quote"])[:200]
    return out


def _dec_sum(values: list[Optional[Decimal]]) -> Optional[Decimal]:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present, Decimal(0))


# ---------------------------------------------------------------------------
# Pairing helpers
# ---------------------------------------------------------------------------
def _pair_containers(
    pl_rows: list[dict[str, Any]], bl_rows: list[dict[str, Any]]
) -> tuple[list[tuple[dict, dict, str]], list[dict], list[dict]]:
    """Pair PL/BL containers: exact container_no first, seal_no fallback.

    Returns (pairs, unmatched_pl, unmatched_bl). Unmatched rows are reported
    by R09; pairing via seal keeps R10-R12 evaluable when R09 fires.
    """
    pairs: list[tuple[dict, dict, str]] = []
    used_bl: set[int] = set()

    bl_by_id = {}
    for idx, row in enumerate(bl_rows):
        cid = _norm_id(row.get("container_no"))
        if cid:
            bl_by_id.setdefault(cid, (idx, row))

    matched_pl: set[int] = set()
    for pidx, prow in enumerate(pl_rows):
        cid = _norm_id(prow.get("container_no"))
        if cid and cid in bl_by_id:
            bidx, brow = bl_by_id[cid]
            if bidx not in used_bl:
                pairs.append((prow, brow, "container_no"))
                matched_pl.add(pidx)
                used_bl.add(bidx)

    bl_by_seal = {}
    for idx, row in enumerate(bl_rows):
        if idx in used_bl:
            continue
        seal = _norm_id(row.get("seal_no"))
        if seal:
            bl_by_seal.setdefault(seal, (idx, row))

    for pidx, prow in enumerate(pl_rows):
        if pidx in matched_pl:
            continue
        seal = _norm_id(prow.get("seal_no"))
        if seal and seal in bl_by_seal:
            bidx, brow = bl_by_seal[seal]
            pairs.append((prow, brow, "seal_no"))
            matched_pl.add(pidx)
            used_bl.add(bidx)

    unmatched_pl = [r for i, r in enumerate(pl_rows) if i not in matched_pl]
    unmatched_bl = [r for i, r in enumerate(bl_rows) if i not in used_bl]
    return pairs, unmatched_pl, unmatched_bl


def _line_key(item: dict[str, Any]) -> str:
    """Pairing key for CI/PL lines: batch_no, fallback description+qty+unit."""
    batch = _norm_id(item.get("batch_no"))
    if batch:
        return f"B|{batch}"
    qty = _number(item.get("quantity"))
    qty_s = str(qty.quantize(Decimal("0.01"))) if qty is not None else ""
    return (
        f"D|{_norm_text(item.get('product_description'))}"
        f"|{qty_s}|{_norm_unit(item.get('package_unit'))}"
    )


def _pair_lines(
    ci_items: list[dict[str, Any]], pl_items: list[dict[str, Any]]
) -> dict[str, Any]:
    """Pair CI/PL lines by batch (fallback desc+qty). Detects duplicates."""
    ci_map: dict[str, list[dict]] = {}
    pl_map: dict[str, list[dict]] = {}
    for item in ci_items:
        ci_map.setdefault(_line_key(item), []).append(item)
    for item in pl_items:
        pl_map.setdefault(_line_key(item), []).append(item)

    dup_ci = [k for k, rows in ci_map.items() if len(rows) > 1]
    dup_pl = [k for k, rows in pl_map.items() if len(rows) > 1]

    pairs = [(ci_map[k][0], pl_map[k][0]) for k in ci_map.keys() & pl_map.keys()]
    ci_only = [k for k in ci_map.keys() - pl_map.keys()]
    pl_only = [k for k in pl_map.keys() - ci_map.keys()]
    return {
        "pairs": pairs,
        "ci_only": [ci_map[k][0] for k in ci_only],
        "pl_only": [pl_map[k][0] for k in pl_only],
        "dup_ci_keys": dup_ci,
        "dup_pl_keys": dup_pl,
    }


def _important_tokens(text: str) -> set[str]:
    """Numeric/spec tokens of a description: 36-38, 220kg, 0.5, 220..."""
    return set(re.findall(r"[0-9][0-9a-z.%/-]*", _norm_text(text)))


def _norm_desc(text: str) -> str:
    """Description equality key: casefold, punctuation -> single spaces."""
    return re.sub(r"[^0-9a-z]+", " ", _norm_text(text)).strip()


def _compare_descriptions(a: str, b: str) -> str:
    """'PASS' | 'REVIEW' | 'FAIL' for one description pair (R05)."""
    if _norm_desc(a) == _norm_desc(b):
        return "PASS"
    ta, tb = _important_tokens(a), _important_tokens(b)
    if ta and ta == tb:
        return "REVIEW"
    if ta <= tb or tb <= ta:
        return "REVIEW"
    return "FAIL"


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
def validate_documents(documents: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate extracted CI/PL/BL dictionaries; missing documents are allowed."""
    by_type: dict[str, dict[str, Any]] = {}
    for doc in documents:
        dtype = _doc_type(doc)
        if dtype in {CI, PL, BL}:
            by_type[dtype] = doc

    ci, pl, bl = by_type.get(CI), by_type.get(PL), by_type.get(BL)
    findings: list[Finding] = []

    def add(rule_id, severity, status, message, docs, evidence):
        findings.append(Finding(rule_id, severity, status, message, docs, evidence))

    # ---- R01 missing_document -------------------------------------------
    missing_docs = [t for t in REQUIRED_DOCS if t not in by_type]
    if missing_docs:
        add("R01", "HIGH", "FAIL",
            "Thiếu chứng từ bắt buộc trong bộ: "
            + ", ".join(DOC_LABEL[t] for t in missing_docs) + ".",
            missing_docs,
            {"required": list(REQUIRED_DOCS), "present": sorted(by_type.keys()),
             "missing": missing_docs})
    else:
        add("R01", "LOW", "PASS", "Đủ 3 chứng từ CI, PL, BL trong bộ.",
            list(REQUIRED_DOCS), {"present": sorted(by_type.keys())})

    # ---- R02 missing_required_field -------------------------------------
    for dtype, doc in by_type.items():
        missing = [
            (field, critical)
            for field, critical in REQUIRED_FIELDS[dtype]
            if not _has_value(doc, field)
        ]
        if missing:
            for field, critical in missing:
                add("R02", "HIGH" if critical else "MEDIUM", "FAIL",
                    f"Thiếu trường bắt buộc '{field}' trên {DOC_LABEL[dtype]}.",
                    [dtype], {"field": field, "document": dtype})
        else:
            add("R02", "LOW", "PASS",
                f"Đủ trường bắt buộc trên {DOC_LABEL[dtype]}.",
                [dtype], {"document": dtype})

    # ---- R03 invoice_reference_mismatch ---------------------------------
    if ci and pl:
        a, b = _value(ci, "invoice_no"), _value(pl, "invoice_reference_no")
        if a and b:
            ok = _norm_id(a) == _norm_id(b)
            add("R03", "HIGH" if not ok else "LOW", "FAIL" if not ok else "PASS",
                f"Số invoice {'khớp' if ok else 'không khớp'} sau chuẩn hóa: "
                f"CI '{a}' vs PL '{b}'.",
                [CI, PL],
                {"invoice_no": [_src(CI, ci, "invoice_no"),
                                _src(PL, pl, "invoice_reference_no")]})

    # ---- R04 party_information_mismatch ---------------------------------
    _check_party("người bán / shipper",
                 {dt: ("seller_name", "seller_address") for dt in (CI, PL)}
                 | {BL: ("shipper_name", "shipper_address")},
                 by_type, add)
    _check_party("người mua / consignee",
                 {dt: ("buyer_name", "buyer_address") for dt in (CI, PL)}
                 | {BL: ("consignee_name", "consignee_address")},
                 by_type, add)

    # ---- R05 product_description_mismatch -------------------------------
    _check_descriptions(ci, pl, bl, add)

    # ---- R06 quantity_mismatch (totals) ---------------------------------
    _check_totals(
        "R06", "Tổng số lượng",
        {CI: ("total_quantity", "total_package_unit"),
         PL: ("total_packages", "total_package_unit"),
         BL: ("total_packages", "total_package_unit")},
        by_type, add, exact=True, tol=0.0,
    )

    # ---- R07 net_weight_mismatch (CI vs PL) -----------------------------
    _check_pair_weight("R07", "Tổng net weight", CI, "total_net_weight",
                       PL, "total_net_weight", ci, pl, add)

    # ---- R08 gross_weight_mismatch (3 pairs) ----------------------------
    gross_values = [
        (dt, doc, _number(_value(doc, "total_gross_weight")))
        for dt, doc in ((CI, ci), (PL, pl), (BL, bl))
        if doc and _value(doc, "total_gross_weight") is not None
    ]
    if len(gross_values) >= 2:
        bad_pairs = []
        for i in range(len(gross_values)):
            for j in range(i + 1, len(gross_values)):
                d1, _, v1 = gross_values[i]
                d2, _, v2 = gross_values[j]
                if not _within_ratio(v1, v2, WEIGHT_TOLERANCE_RATIO):
                    diff = abs(v1 - v2)
                    pct = (diff / max(abs(v1), abs(v2)) * 100) if max(abs(v1), abs(v2)) else Decimal(0)
                    bad_pairs.append(f"{d1}={v1} vs {d2}={v2} (chênh {pct:.2f}%)")
        docs_present = [d for d, _, _ in gross_values]
        if bad_pairs:
            add("R08", "HIGH", "FAIL",
                "Tổng gross weight giữa các chứng từ chênh lệch vượt dung sai "
                f"{WEIGHT_TOLERANCE_RATIO * 100}%: " + "; ".join(bad_pairs) + ".",
                docs_present,
                {"values": {d: float(v) for d, _, v in gross_values},
                 "tolerance_ratio": WEIGHT_TOLERANCE_RATIO,
                 "fields": [_src(d, doc, "total_gross_weight") for d, doc, _ in gross_values]})
        else:
            add("R08", "LOW", "PASS", "Tổng gross weight khớp giữa các chứng từ.",
                docs_present,
                {"values": {d: float(v) for d, _, v in gross_values}})

    # ---- R09-R12 per-container ------------------------------------------
    _check_containers(pl, bl, add)

    # ---- R13 / R14 ports -------------------------------------------------
    _check_pair_text("R13", "Cảng xếp hàng (port of loading)",
                     ci, "port_of_loading", bl, "port_of_loading", add)
    _check_pair_text("R14", "Cảng dỡ hàng (port of discharge)",
                     ci, "port_of_discharge", bl, "port_of_discharge", add)

    # ---- R15 invoice line amount: unit_price x basis == line_amount ------
    calc_bad = []
    calc_checked = 0
    if ci:
        for idx, item in enumerate(_items(ci), start=1):
            price = _number(item.get("unit_price"))
            amount = _number(item.get("line_amount"))
            if price is None or amount is None:
                continue
            calc_checked += 1
            basis_name = "quantity"
            basis = _number(item.get("quantity"))
            price_basis = _norm_text(item.get("price_basis"))
            if "/kg" in price_basis or price_basis.endswith("/g"):
                basis, basis_name = _number(item.get("net_weight")), "net_weight"
            if basis is None:
                continue
            expected = (price * basis).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if abs(expected - amount) > MONEY_ABS_TOLERANCE:
                calc_bad.append(
                    {"line": idx, "basis": basis_name, "price": float(price),
                     "expected": float(expected), "actual": float(amount)})
    if calc_checked:
        if calc_bad:
            add("R15", "HIGH", "FAIL",
                f"{len(calc_bad)} dòng CI có số tiền không khớp đơn giá × "
                "khối lượng sau làm tròn.",
                [CI], {"bad_lines": calc_bad,
                       "money_tolerance": str(MONEY_ABS_TOLERANCE)})
        else:
            add("R15", "LOW", "PASS",
                "Số tiền từng dòng CI khớp đơn giá × khối lượng.", [CI],
                {"checked_lines": calc_checked})

    # ---- R16 total amount -----------------------------------------------
    if ci:
        amounts = [_number(i.get("line_amount")) for i in _items(ci)]
        total = _number(_value(ci, "total_amount"))
        if total is not None and any(a is not None for a in amounts):
            s = _dec_sum(amounts)
            if abs(s - total) > MONEY_ABS_TOLERANCE:
                add("R16", "HIGH", "FAIL",
                    f"Tổng line_amount ({s}) khác total_amount ({total}) của CI.",
                    [CI], {"sum_line_amount": float(s), "total_amount": float(total)})
            else:
                add("R16", "LOW", "PASS", "Tổng line_amount khớp total_amount của CI.",
                    [CI], {"sum_line_amount": float(s), "total_amount": float(total)})

    # ---- R17 / R18 CI internal weight totals -----------------------------
    _check_ci_weight_total(ci, add)

    # ---- R19 packing list totals ----------------------------------------
    if pl:
        problems = []
        qty_sum = _dec_sum([_number(i.get("quantity")) for i in _items(pl)])
        net_sum = _dec_sum([_number(i.get("net_weight")) for i in _items(pl)])
        gross_sum = _dec_sum([_number(i.get("gross_weight")) for i in _items(pl)])
        total_qty = _number(_value(pl, "total_packages"))
        total_net = _number(_value(pl, "total_net_weight"))
        total_gross = _number(_value(pl, "total_gross_weight"))
        if qty_sum is not None and total_qty is not None and qty_sum != total_qty:
            problems.append(f"số lượng {qty_sum} ≠ {total_qty}")
        if net_sum is not None and total_net is not None and not _within_ratio(net_sum, total_net, WEIGHT_TOLERANCE_RATIO):
            problems.append(f"net weight {net_sum} ≠ {total_net}")
        if gross_sum is not None and total_gross is not None and not _within_ratio(gross_sum, total_gross, WEIGHT_TOLERANCE_RATIO):
            problems.append(f"gross weight {gross_sum} ≠ {total_gross}")
        if problems:
            add("R19", "HIGH", "FAIL",
                "Tổng các dòng không bằng tổng khai báo trên PL: "
                + "; ".join(problems) + ".", [PL],
                {"sum_quantity": str(qty_sum), "sum_net_weight": str(net_sum),
                 "sum_gross_weight": str(gross_sum),
                 "total_packages": str(total_qty), "total_net_weight": str(total_net),
                 "total_gross_weight": str(total_gross)})
        elif qty_sum is not None or net_sum is not None:
            add("R19", "LOW", "PASS", "Tổng các dòng khớp tổng khai báo trên PL.",
                [PL], {"sum_quantity": str(qty_sum)})

    # ---- R20 PL container summary ---------------------------------------
    _check_pl_container_summary(pl, add)

    # ---- R21 BL totals ----------------------------------------------------
    if bl:
        problems = []
        qty_sum = _dec_sum([_number(c.get("quantity")) for c in _containers_bl(bl)])
        gross_sum = _dec_sum([_number(c.get("gross_weight")) for c in _containers_bl(bl)])
        total_qty = _number(_value(bl, "total_packages"))
        total_gross = _number(_value(bl, "total_gross_weight"))
        if qty_sum is not None and total_qty is not None and qty_sum != total_qty:
            problems.append(f"số lượng {qty_sum} ≠ {total_qty}")
        if gross_sum is not None and total_gross is not None and not _within_ratio(gross_sum, total_gross, WEIGHT_TOLERANCE_RATIO):
            problems.append(f"gross weight {gross_sum} ≠ {total_gross}")
        if problems:
            add("R21", "HIGH", "FAIL",
                "Tổng theo container không bằng tổng khai báo trên BL: "
                + "; ".join(problems) + ".", [BL],
                {"sum_quantity": str(qty_sum), "sum_gross_weight": str(gross_sum),
                 "total_packages": str(total_qty), "total_gross_weight": str(total_gross)})
        elif qty_sum is not None or gross_sum is not None:
            add("R21", "LOW", "PASS", "Tổng theo container khớp tổng khai báo trên BL.",
                [BL], {"sum_quantity": str(qty_sum), "sum_gross_weight": str(gross_sum)})

    # ---- R22 / R26 line pairing (shared) --------------------------------
    if ci and pl:
        line_result = _pair_lines(_items(ci), _items(pl))
        _check_batches(line_result, ci, pl, add)
        _check_line_items(line_result, ci, pl, add)

    # ---- R23 shipping marks ---------------------------------------------
    if ci and pl:
        a, b = _value(ci, "shipping_marks"), _value(pl, "shipping_marks")
        if a and b:
            ok = _norm_text(a) == _norm_text(b)
            add("R23", "MEDIUM" if not ok else "LOW", "FAIL" if not ok else "PASS",
                f"Shipping marks {'khớp' if ok else 'khác'} sau chuẩn hóa: "
                f"CI '{a}' vs PL '{b}'.", [CI, PL],
                {"shipping_marks": [_src(CI, ci, "shipping_marks"),
                                    _src(PL, pl, "shipping_marks")]})

    # ---- R24 date relations ---------------------------------------------
    _check_date_relations(ci, pl, bl, add)

    # ---- R25 measurement (only when both sides have data) ----------------
    if pl and bl:
        a = _number(_value(pl, "measurement_cbm"))
        b = _number(_value(bl, "total_measurement_cbm"))
        if a is not None and b is not None:
            ok = _within_ratio(a, b, MEASUREMENT_TOLERANCE_RATIO)
            add("R25", "MEDIUM" if not ok else "LOW", "FAIL" if not ok else "PASS",
                f"Measurement {'khớp' if ok else 'chênh vượt dung sai'}: "
                f"PL {a} CBM vs BL {b} CBM.", [PL, BL],
                {"measurement_cbm": [_src(PL, pl, "measurement_cbm"),
                                     _src(BL, bl, "total_measurement_cbm")],
                 "tolerance_ratio": MEASUREMENT_TOLERANCE_RATIO})

    # ---- Summary ----------------------------------------------------------
    counts = {s: sum(1 for f in findings if f.status == s) for s in ("FAIL", "REVIEW", "PASS")}
    risk = "HIGH" if any(f.severity == "HIGH" and f.status in {"FAIL", "REVIEW"} for f in findings) else (
        "MEDIUM" if any(f.status in {"FAIL", "REVIEW"} for f in findings) else "LOW")
    return {
        "risk_level": risk,
        "summary": counts,
        "findings": [f.to_dict() for f in findings],
        "disclaimer": "Đây là cờ cảnh báo dựa trên quy tắc, không phải kết luận gian lận. "
                      "Cần người có thẩm quyền rà soát trước khi sử dụng bộ chứng từ cho "
                      "nghiệp vụ tiếp theo.",
    }


def _has_value(doc: dict[str, Any], field: str) -> bool:
    """R02 presence check: scalar non-empty, list non-empty."""
    value = _value(doc, field, None)
    if value is None:
        return False
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, str):
        return value.strip() != ""
    return True

# ---------------------------------------------------------------------------
# Rule helpers
# ---------------------------------------------------------------------------
_SEV_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_STATUS_RANK = {"PASS": 0, "REVIEW": 1, "FAIL": 2}


def _worst(sev: str, status: str, cur: tuple[str, str]) -> tuple[str, str]:
    """Keep the most severe (severity, status) seen so far."""
    if (_SEV_RANK.get(sev, 0), _STATUS_RANK.get(status, 0)) > (
            _SEV_RANK.get(cur[0], 0), _STATUS_RANK.get(cur[1], 0)):
        return (sev, status)
    return cur


def _check_party(label: str, fields: dict[str, tuple[str, str]],
                 by_type: dict[str, dict], add) -> None:
    """R04 — one finding per party (seller or buyer): worst across pairs."""
    name_entries, addr_entries = [], []
    for dtype, doc in by_type.items():
        if dtype not in fields:
            continue
        n_field, a_field = fields[dtype]
        nv, av = _value(doc, n_field), _value(doc, a_field)
        if nv:
            name_entries.append((dtype, n_field, nv))
        if av:
            addr_entries.append((dtype, a_field, av))

    if len(name_entries) < 2:
        return

    worst = ("LOW", "PASS")
    name_ratios, addr_ratios = [], []
    worst_detail = ""

    def _eval(entries, normalizer, threshold, kind, out_ratios):
        nonlocal worst, worst_detail
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                (d1, f1, v1), (d2, f2, v2) = entries[i], entries[j]
                n1, n2 = normalizer(v1), normalizer(v2)
                ratio = _similar(n1, n2)
                out_ratios.append({"pair": f"{d1}~{d2}", "ratio": round(ratio, 3)})
                if n1 == n2:
                    continue
                if ratio >= threshold:
                    sev, status = "MEDIUM", "REVIEW"
                else:
                    sev, status = "HIGH", "FAIL"
                prev = worst
                worst = _worst(sev, status, worst)
                if worst != prev:
                    worst_detail = (
                        f"{kind} '{v1}' ({d1}) khác '{v2}' ({d2}) "
                        f"(độ tương đồng {ratio:.0%}).")

    _eval(name_entries, _norm_entity, NAME_REVIEW_THRESHOLD, "Tên", name_ratios)
    _eval(addr_entries, _norm_text, ADDRESS_REVIEW_THRESHOLD, "Địa chỉ", addr_ratios)

    docs = sorted({d for d, _, _ in name_entries} | {d for d, _, _ in addr_entries})
    evidence = {
        "name": [_src(d, by_type[d], f) for d, f, _ in name_entries],
        "address": [_src(d, by_type[d], f) for d, f, _ in addr_entries],
        "name_ratios": name_ratios, "address_ratios": addr_ratios,
    }
    sev, status = worst
    if status == "PASS":
        message = f"Thông tin {label} khớp giữa các chứng từ."
    elif status == "REVIEW":
        message = (f"Thông tin {label} gần giống giữa các chứng từ, cần review: "
                   + worst_detail)
    else:
        message = f"Thông tin {label} khác nhau giữa các chứng từ: " + worst_detail
    add("R04", sev, status, message, docs, evidence)


def _check_descriptions(ci, pl, bl, add) -> None:
    """R05 — CI↔PL paired by lines, BL at goods-level. One aggregated finding."""
    if not ci:
        return
    results: list[tuple[str, str]] = []  # (status, detail)

    if pl:
        pairing = _pair_lines(_items(ci), _items(pl))
        for c_item, p_item in pairing["pairs"]:
            d1, d2 = c_item.get("product_description"), p_item.get("product_description")
            if not d1 or not d2:
                continue
            results.append((_compare_descriptions(str(d1), str(d2)),
                            f"CI '{d1}' vs PL '{d2}'"))

    if bl:
        bl_descs = [str(c.get("description")) for c in _containers_bl(bl)
                    if c.get("description")]
        if bl_descs:
            for c_item in _items(ci):
                d1 = c_item.get("product_description")
                if not d1:
                    continue
                best = max(bl_descs, key=lambda d2: _similar(_norm_text(str(d1)),
                                                             _norm_text(d2)))
                results.append((_compare_descriptions(str(d1), best),
                                f"CI '{d1}' vs BL '{best}'"))

    if not results:
        return
    worst_status, worst_detail = "PASS", ""
    for res, detail in results:
        if _STATUS_RANK[res] > _STATUS_RANK[worst_status]:
            worst_status, worst_detail = res, detail
        elif not worst_detail:
            worst_detail = detail

    docs = [t for t, d in ((CI, ci), (PL, pl), (BL, bl)) if d]
    if worst_status == "PASS":
        add("R05", "LOW", "PASS",
            "Mô tả hàng hóa khớp giữa các chứng từ sau chuẩn hóa.",
            docs, {"compared_pairs": len(results)})
    else:
        sev = "MEDIUM" if worst_status == "REVIEW" else "HIGH"
        prefix = ("Mô tả hàng hóa khác cách diễn đạt nhưng cùng thuộc tính quan trọng: "
                  if worst_status == "REVIEW"
                  else "Mô tả hàng hóa thiếu thuộc tính quan trọng: ")
        add("R05", sev, worst_status, prefix + worst_detail + ".",
            docs, {"worst_pair": worst_detail, "compared_pairs": len(results)})


def _check_totals(rule_id: str, label: str,
                  fields: dict[str, tuple[str, str]],
                  by_type: dict[str, dict], add, exact: bool, tol: float) -> None:
    """R06 — compare totals across documents (value + normalized unit)."""
    entries = []
    for dtype, doc in by_type.items():
        if dtype not in fields:
            continue
        value_field, unit_field = fields[dtype]
        value = _number(_value(doc, value_field))
        if value is None:
            continue
        entries.append((dtype, value, _norm_unit(_value(doc, unit_field))))
    if len(entries) < 2:
        return

    bad = []
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            d1, v1, u1 = entries[i]
            d2, v2, u2 = entries[j]
            same_value = v1 == v2 if exact else _within_ratio(v1, v2, tol)
            if not same_value or (u1 and u2 and u1 != u2):
                bad.append(f"{d1}={v1} {u1} vs {d2}={v2} {u2}")
    docs = [d for d, _, _ in entries]
    evidence = {"values": {d: float(v) for d, v, _ in entries},
                "units": {d: u for d, _, u in entries}}
    if bad:
        add(rule_id, "HIGH", "FAIL",
            f"{label} không khớp giữa các chứng từ: " + "; ".join(bad) + ".",
            docs, evidence)
    else:
        add(rule_id, "LOW", "PASS", f"{label} khớp giữa các chứng từ.", docs, evidence)

def _check_pair_weight(rule_id: str, label: str,
                       d1: str, f1: str, d2: str, f2: str,
                       doc1, doc2, add) -> None:
    """R07 — one weight pair with relative tolerance."""
    if not doc1 or not doc2:
        return
    v1 = _number(_value(doc1, f1))
    v2 = _number(_value(doc2, f2))
    if v1 is None or v2 is None:
        return
    ok = _within_ratio(v1, v2, WEIGHT_TOLERANCE_RATIO)
    evidence = {f1: [_src(d1, doc1, f1)], f2: [_src(d2, doc2, f2)],
                "tolerance_ratio": WEIGHT_TOLERANCE_RATIO}
    if ok:
        add(rule_id, "LOW", "PASS", f"{label} khớp giữa {d1} và {d2}.",
            [d1, d2], evidence)
    else:
        pct = abs(v1 - v2) / max(abs(v1), abs(v2)) * 100
        add(rule_id, "HIGH", "FAIL",
            f"{label} chênh {pct:.2f}% (vượt dung sai "
            f"{WEIGHT_TOLERANCE_RATIO * 100}%): {d1}={v1} vs {d2}={v2}.",
            [d1, d2], evidence)


def _check_containers(pl, bl, add) -> None:
    """R09, R10, R11, R12 — per-container comparison with pairing fallback."""
    if not pl or not bl:
        return
    pl_rows = _containers_pl(pl)
    bl_rows = _containers_bl(bl)
    if not pl_rows or not bl_rows:
        return

    pairs, unmatched_pl, unmatched_bl = _pair_containers(pl_rows, bl_rows)

    # R09 set difference.
    pl_ids = {r for r in (_norm_id(c.get("container_no")) for c in pl_rows) if r}
    bl_ids = {r for r in (_norm_id(c.get("container_no")) for c in bl_rows) if r}
    missing_in_bl = sorted(pl_ids - bl_ids)
    missing_in_pl = sorted(bl_ids - pl_ids)
    if missing_in_bl or missing_in_pl:
        add("R09", "HIGH", "FAIL",
            "Danh sách container không khớp giữa PL và BL"
            + (f"; chỉ có ở PL: {', '.join(missing_in_bl)}" if missing_in_bl else "")
            + (f"; chỉ có ở BL: {', '.join(missing_in_pl)}" if missing_in_pl else "")
            + ".", [PL, BL],
            {"pl_containers": sorted(pl_ids), "bl_containers": sorted(bl_ids),
             "missing_in_bl": missing_in_bl, "missing_in_pl": missing_in_pl})
    else:
        add("R09", "LOW", "PASS", "Danh sách container khớp giữa PL và BL.",
            [PL, BL], {"containers": sorted(pl_ids)})

    if not pairs:
        return

    # R10 seal per paired container.
    seal_bad = []
    for prow, brow, how in pairs:
        s1, s2 = _norm_id(prow.get("seal_no")), _norm_id(brow.get("seal_no"))
        if how == "container_no" and s1 and s2 and s1 != s2:
            seal_bad.append(f"{prow.get('container_no')}: PL {s1} vs BL {s2}")
    if seal_bad:
        add("R10", "HIGH", "FAIL",
            "Seal number của cùng container không khớp: " + "; ".join(seal_bad) + ".",
            [PL, BL], {"pairs": [{"pl": p.get("container_no"), "bl": b.get("container_no"),
                                  "matched_by": h} for p, b, h in pairs]})
    else:
        add("R10", "LOW", "PASS", "Seal number khớp theo từng container.",
            [PL, BL], {"pairs": [{"pl": p.get("container_no"), "bl": b.get("container_no"),
                                  "matched_by": h} for p, b, h in pairs]})

    # R11 gross weight per paired container.
    gross_bad = []
    for prow, brow, _ in pairs:
        v1 = _number(prow.get("gross_weight"))
        v2 = _number(brow.get("gross_weight"))
        if v1 is None or v2 is None:
            continue
        if not _within_ratio(v1, v2, WEIGHT_TOLERANCE_RATIO):
            gross_bad.append(f"{prow.get('container_no')}: {v1} vs {v2}")
    if gross_bad:
        add("R11", "HIGH", "FAIL",
            "Gross weight từng container chênh vượt dung sai "
            f"{WEIGHT_TOLERANCE_RATIO * 100}%: " + "; ".join(gross_bad) + ".",
            [PL, BL], {"bad": gross_bad})
    else:
        add("R11", "LOW", "PASS", "Gross weight khớp theo từng container.",
            [PL, BL], {"pairs_checked": len(pairs)})

    # R12 quantity per paired container.
    qty_bad = []
    for prow, brow, _ in pairs:
        v1 = _number(prow.get("quantity"))
        v2 = _number(brow.get("quantity"))
        u1 = _norm_unit(prow.get("package_unit"))
        u2 = _norm_unit(brow.get("package_unit"))
        if v1 is None or v2 is None:
            continue
        if v1 != v2 or (u1 and u2 and u1 != u2):
            qty_bad.append(f"{prow.get('container_no')}: {v1} {u1} vs {v2} {u2}")
    if qty_bad:
        add("R12", "HIGH", "FAIL",
            "Số lượng kiện theo từng container không khớp: "
            + "; ".join(qty_bad) + ".", [PL, BL], {"bad": qty_bad})
    else:
        add("R12", "LOW", "PASS", "Số lượng kiện khớp theo từng container.",
            [PL, BL], {"pairs_checked": len(pairs)})


def _check_pair_text(rule_id: str, label: str,
                     doc1, field1: str, doc2, field2: str, add) -> None:
    """R13/R14 — normalized place comparison (ports)."""
    if not doc1 or not doc2:
        return
    v1, v2 = _value(doc1, field1), _value(doc2, field2)
    if not v1 or not v2:
        return
    ok = _norm_place(v1) == _norm_place(v2)
    evidence = {field1: [_src(CI, doc1, field1)], field2: [_src(BL, doc2, field2)]}
    if ok:
        add(rule_id, "LOW", "PASS", f"{label} khớp giữa CI và BL.", [CI, BL], evidence)
    else:
        add(rule_id, "HIGH", "FAIL",
            f"{label} khác nhau sau chuẩn hóa: CI '{v1}' vs BL '{v2}'.",
            [CI, BL], evidence)

def _check_ci_weight_total(ci, add) -> None:
    """R17 net / R18 gross — Σ dòng vs tổng khai báo trên CI."""
    if not ci:
        return
    for rule_id, field, label in (
        ("R17", "net_weight", "net weight"),
        ("R18", "gross_weight", "gross weight"),
    ):
        values = [_number(item.get(field)) for item in _items(ci)]
        present = [v for v in values if v is not None]
        total = _number(_value(ci, f"total_{field}"))
        if not present or total is None:
            # R18: sample CI has no per-line gross -> skip (spec §3.2).
            continue
        s = sum(present, Decimal(0))
        ok = _within_ratio(s, total, WEIGHT_TOLERANCE_RATIO)
        if ok:
            add(rule_id, "LOW", "PASS",
                f"Tổng {label} các dòng khớp tổng khai báo trên CI.",
                [CI], {"sum": str(s), "declared": str(total)})
        else:
            pct = abs(s - total) / max(abs(s), abs(total)) * 100
            add(rule_id, "HIGH", "FAIL",
                f"Tổng {label} các dòng ({s}) khác tổng khai báo ({total}) "
                f"trên CI, chênh {pct:.2f}%.", [CI],
                {"sum": str(s), "declared": str(total),
                 "tolerance_ratio": WEIGHT_TOLERANCE_RATIO})


def _check_pl_container_summary(pl, add) -> None:
    """R20 — Σ items theo container vs Container Summary (skip khi thiếu)."""
    if not pl:
        return
    summary = _value(pl, "container_summary", []) or []
    summary = [c for c in summary if isinstance(c, dict) and _norm_id(c.get("container_no"))]
    if not summary:
        return  # Container Summary vắng mặt -> skip theo spec.

    grouped: dict[str, dict[str, Any]] = {}
    for item in _items(pl):
        cid = _norm_id(item.get("container_no"))
        if not cid:
            continue
        g = grouped.setdefault(cid, {"quantity": Decimal(0), "net_weight": Decimal(0),
                                     "gross_weight": Decimal(0), "has": False})
        g["has"] = True
        for field in ("quantity", "net_weight", "gross_weight"):
            v = _number(item.get(field))
            if v is not None:
                g[field] += v

    problems = []
    summary_ids = set()
    for row in summary:
        cid = _norm_id(row.get("container_no"))
        summary_ids.add(cid)
        g = grouped.get(cid)
        if g is None:
            problems.append(f"container {row.get('container_no')} có ở summary nhưng không có dòng hàng")
            continue
        for field, label in (("quantity", "số lượng"),
                             ("net_weight", "net weight"),
                             ("gross_weight", "gross weight")):
            declared = _number(row.get(field))
            if declared is None or not g["has"]:
                continue
            tol = 0.0 if field == "quantity" else WEIGHT_TOLERANCE_RATIO
            if field == "quantity":
                same = g[field] == declared
            else:
                same = _within_ratio(g[field], declared, tol)
            if not same:
                problems.append(
                    f"{row.get('container_no')}: {label} dòng hàng {g[field]} ≠ summary {declared}")
    for cid, g in grouped.items():
        if cid not in summary_ids:
            problems.append(f"container {cid} có dòng hàng nhưng thiếu ở summary")

    if problems:
        add("R20", "HIGH", "FAIL",
            "Container Summary không khớp tổng hợp dòng hàng trên PL: "
            + "; ".join(problems) + ".", [PL], {"problems": problems})
    else:
        add("R20", "LOW", "PASS",
            "Container Summary khớp tổng hợp dòng hàng theo container.",
            [PL], {"summary_containers": sorted(summary_ids)})


def _check_batches(result: dict[str, Any], ci, pl, add) -> None:
    """R22 — batch_no of paired lines (skip lines without batch)."""
    checked = 0
    bad = []
    for c_item, p_item in result["pairs"]:
        b1, b2 = c_item.get("batch_no"), p_item.get("batch_no")
        if not b1 or not b2:
            continue
        checked += 1
        if _norm_id(b1) != _norm_id(b2):
            bad.append(f"dòng {c_item.get('line_no')}: CI {b1} vs PL {b2}")
    if bad:
        add("R22", "HIGH", "FAIL",
            "Batch number của dòng hàng tương ứng không khớp: "
            + "; ".join(bad) + ".", [CI, PL], {"bad": bad})
    elif checked:
        add("R22", "LOW", "PASS",
            "Batch number khớp giữa CI và PL theo từng dòng.",
            [CI, PL], {"checked_pairs": checked})

def _check_line_items(result: dict[str, Any], ci, pl, add) -> None:
    """R26 — missing / duplicate lines between CI and PL."""
    problems = []
    if result["dup_ci_keys"]:
        problems.append("trùng dòng trong CI: " + ", ".join(result["dup_ci_keys"]))
    if result["dup_pl_keys"]:
        problems.append("trùng dòng trong PL: " + ", ".join(result["dup_pl_keys"]))
    if result["ci_only"]:
        missing = [str(_value(i, "batch_no") or _value(i, "product_description"))
                   for i in result["ci_only"]]
        problems.append("thiếu dòng ở PL: " + ", ".join(missing))
    if result["pl_only"]:
        extra = [str(_value(i, "batch_no") or _value(i, "product_description"))
                 for i in result["pl_only"]]
        problems.append("thừa dòng so với CI: " + ", ".join(extra))

    evidence = {
        "paired": len(result["pairs"]),
        "missing_in_pl": [str(_value(i, "batch_no")) for i in result["ci_only"]],
        "missing_in_ci": [str(_value(i, "batch_no")) for i in result["pl_only"]],
        "duplicates_ci": result["dup_ci_keys"],
        "duplicates_pl": result["dup_pl_keys"],
    }
    if problems:
        add("R26", "HIGH", "FAIL",
            "Dòng hàng CI/PL bị thiếu hoặc trùng khi đối chiếu: "
            + "; ".join(problems) + ".", [CI, PL], evidence)
    else:
        add("R26", "LOW", "PASS",
            f"Đủ {len(result['pairs'])} dòng hàng, không trùng lặp giữa CI và PL.",
            [CI, PL], evidence)


def _check_date_relations(ci, pl, bl, add) -> None:
    """R24 — evaluate every configured relation (DATE_RELATIONS)."""
    docs_by_type = {CI: ci, PL: pl, BL: bl}
    for rel_id, (ldoc, lfield), (rdoc, rfield), op, severity, violated_status in DATE_RELATIONS:
        left_doc, right_doc = docs_by_type.get(ldoc), docs_by_type.get(rdoc)
        if not left_doc or not right_doc:
            continue
        raw_l, raw_r = _value(left_doc, lfield), _value(right_doc, rfield)
        dl, dr = _norm_date(raw_l), _norm_date(raw_r)
        if dl is None or dr is None:
            continue  # thiếu ngày -> skip relation (đã do R02 báo)

        if op == "==":
            ok = dl == dr
            op_text = "phải bằng"
        elif op == ">=":
            ok = dl >= dr
            op_text = "phải lớn hơn hoặc bằng"
        elif op == "<=":
            ok = dl <= dr
            op_text = "phải nhỏ hơn hoặc bằng"
        else:
            continue

        evidence = {
            "relation_id": rel_id,
            "left": _src(ldoc, left_doc, lfield),
            "right": _src(rdoc, right_doc, rfield),
        }
        involved = sorted({ldoc, rdoc})
        if ok:
            add("R24", "LOW", "PASS",
                f"[{rel_id}] Ngày {ldoc}.{lfield}={dl.isoformat()} "
                f"{op_text} {rdoc}.{rfield}={dr.isoformat()}.",
                involved, evidence)
        else:
            add("R24", severity, violated_status,
                f"[{rel_id}] Ngày không nhất quán: {ldoc}.{lfield}={dl.isoformat()} "
                f"không {op_text} {rdoc}.{rfield}={dr.isoformat()}.",
                involved, evidence)











