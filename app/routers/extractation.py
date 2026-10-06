import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.database import crud
from app.database.models import Document
from app.services.document_reader import read_document
from app.services.extractor import (
    DEFAULT_MODEL,
    detect_document_type,
    extract_structured_data,
)
from app.services.schemas import DocumentType
from app.services.validation import validate_documents

router = APIRouter(prefix="/AI", tags=["AI Extraction & Validation"])

# Canonical lowercase keys expected by app.services.validation.
REQUIRED_DOCUMENT_TYPES = {
    DocumentType.COMMERCIAL_INVOICE.value,
    DocumentType.PACKING_LIST.value,
    DocumentType.BILL_OF_LADING.value,
}

# A cross-document comparison needs at least this many distinct recognised types.
MIN_TYPES_FOR_COMPARISON = 2

# app.services.validation keys documents by lowercase type; the DB column
# (documents_document_type_check) only accepts UPPERCASE. Both are derived here.
_UPPERCASE_TO_LOWERCASE = {dtype.name: dtype.value for dtype in DocumentType}
_LOWERCASE_TO_UPPERCASE = {dtype.value: dtype.name for dtype in DocumentType}


def _reject_if_reviewing(run_id: UUID | None) -> None:
    """Block mutations while the client is browsing a previous compare run.

    The UI passes run_id when it shows history; the server refuses the write so
    read-only mode is enforced here and not only in the UI.
    """
    if run_id is not None:
        raise HTTPException(
            409,
            detail=(
                "Đang ở chế độ xem lịch sử kiểm tra nên không thể thêm hoặc xóa "
                "chứng từ. Quay lại lần kiểm tra mới nhất để chỉnh sửa bộ chứng từ."
            ),
        )


def _ocr_fallback_enabled() -> bool:
    return os.getenv("ENABLE_OCR_FALLBACK", "false").lower() == "true"


def _normalize_document_type(value: object) -> str:
    """Map DocumentType / 'INVOICE' / 'invoice' to the lowercase validation key."""
    raw = str(getattr(value, "value", value) or DocumentType.UNKNOWN.value)
    return _UPPERCASE_TO_LOWERCASE.get(raw.upper(), raw.lower())


def _to_db_document_type(value: object) -> str:
    """Map any document type to UPPERCASE, as required by the DB CHECK constraint."""
    return _LOWERCASE_TO_UPPERCASE.get(
        _normalize_document_type(value), DocumentType.UNKNOWN.name
    )


# validation_issues_severity_check allows LOW/MEDIUM/HIGH/CRITICAL only.
_DB_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _to_db_severity(value: object) -> str:
    """Coerce a finding severity to one the DB accepts (validation.py also uses INFO)."""
    severity = str(value or "").upper()
    return severity if severity in _DB_SEVERITIES else "MEDIUM"


def _page_sources(doc) -> list[dict]:
    return [
        {"page": p.page_number, "source": p.source, "characters": len(p.text)}
        for p in doc.pages
    ]


def inspect_existing_document(document: Document):
    """Read a stored file and classify it via service/extractor."""
    file_path = Path(document.file_path)

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Stored file not found: {document.filename}",
        )

    try:
        doc = read_document(
            str(file_path),
            use_ocr_fallback=_ocr_fallback_enabled(),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Cannot read {document.filename}: {exc}"
        ) from exc

    if not doc.full_text.strip():
        raise HTTPException(
            status_code=422,
            detail=f"No readable text in {document.filename}. This may be a "
            "scanned PDF; enable OCR fallback or use a vision model.",
        )

    doc_type = detect_document_type(doc.full_text)

    return doc, doc_type

@router.get("/jobs/{job_id}/runs")
def list_runs(job_id: UUID, db: Session = Depends(get_db)):
    """Compare history for a job, newest first."""
    if not crud.get_job(db, job_id):
        raise HTTPException(404, "Job not found")

    runs = []
    for run in crud.list_audit_runs(db, job_id):
        issues = crud.list_run_issues(db, run.id)
        by_severity: dict[str, int] = {}
        for issue in issues:
            by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        runs.append({
            "id": str(run.id),
            "run_number": run.run_number,
            "risk_level": run.risk_level,
            "summary": run.summary or {},
            "created_at": run.created_at,
            "model_name": run.model_name,
            "issue_count": len(issues),
            "issue_count_by_severity": by_severity,
            "documents_used": run.documents_used or [],
            "unsupported_count": len(run.unsupported_documents or []),
        })
    return {"job_id": str(job_id), "runs": runs}


@router.get("/jobs/{job_id}/runs/{run_id}")
def get_run(job_id: UUID, run_id: UUID, db: Session = Depends(get_db)):
    """Full detail of one compare run."""
    run = crud.get_audit_run(db, job_id, run_id)
    if not run:
        raise HTTPException(404, "Audit run not found")

    issues = crud.list_run_issues(db, run.id)
    by_severity: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for issue in issues:
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        by_rule[issue.rule_code] = by_rule.get(issue.rule_code, 0) + 1

    return {
        "run": {
            "id": str(run.id),
            "run_number": run.run_number,
            "risk_level": run.risk_level,
            "summary": run.summary or {},
            "report": run.report,
            "documents_used": run.documents_used or [],
            "unsupported_documents": run.unsupported_documents or [],
            "warnings": run.warnings or [],
            "document_snapshot": run.document_snapshot or [],
            "model_name": run.model_name,
            "created_at": run.created_at,
        },
        "issues": [
            {
                "id": str(i.id),
                "rule_code": i.rule_code,
                "severity": i.severity,
                "message": i.message,
                "compared_values": i.compared_values,
                "evidence": i.evidence,
                "status": i.status,
                "created_at": i.created_at,
            }
            for i in issues
        ],
        "issue_totals": {
            "total": len(issues),
            "by_severity": by_severity,
            "by_rule": by_rule,
        },
    }


@router.get("/jobs/{job_id}/report")
def get_job_report(
    job_id: UUID,
    run_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
):
    """Audit report for a job.

    Without run_id this returns the latest compare run. Passing run_id replays a
    previous run so history can be reviewed without re-running the AI.
    """
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if run_id is not None:
        run = crud.get_audit_run(db, job_id, run_id)
        if not run:
            raise HTTPException(404, "Audit run not found")
        run_issues = crud.list_run_issues(db, run.id)
        issues = run_issues
        has_report = True
        report = run.report
        run_meta = {
            "id": str(run.id),
            "run_number": run.run_number,
            "created_at": run.created_at,
            "model_name": run.model_name,
        }
        risk_level = run.risk_level
    else:
        run = crud.get_latest_audit_run(db, job_id)
        issues = crud.list_issues(db, job_id)
        has_report = run is not None
        report = run.report if run else None
        run_meta = (
            {
                "id": str(run.id),
                "run_number": run.run_number,
                "created_at": run.created_at,
                "model_name": run.model_name,
            }
            if run
            else None
        )
        risk_level = run.risk_level if run else job.risk_level

    by_severity: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for issue in issues:
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        by_rule[issue.rule_code] = by_rule.get(issue.rule_code, 0) + 1
        by_status[issue.status] = by_status.get(issue.status, 0) + 1

    documents = []
    for document in crud.list_documents(db, job_id):
        extraction = crud.get_latest_successful_extraction(db, document.id)
        documents.append({
            "id": str(document.id),
            "filename": document.filename,
            "document_type": document.document_type,
            "read_status": document.read_status,
            "page_count": document.page_count,
            "created_at": document.created_at,
            "extracted_data": (extraction.extracted_data if extraction else None),
            "evidence": (extraction.evidence if extraction else None),
            "model_name": (extraction.model_name if extraction else None),
            "extracted_at": (extraction.created_at if extraction else None),
        })

    return {
        "job": {
            "id": str(job.id),
            "name": job.name,
            "status": job.status,
            "created_at": job.created_at,
            "completed_at": job.completed_at,
            "risk_level": risk_level,
            "validation_summary": job.validation_summary,
            "compared_at": job.compared_at,
        },
        "has_report": has_report,
        "viewing_run_id": str(run_id) if run_id is not None else None,
        "is_history": run_id is not None,
        "run": run_meta,
        "run_count": crud.count_issues(db, job_id) and len(crud.list_audit_runs(db, job_id)) or 0,
        "report": report,
        "issues": [
            {
                "id": str(i.id),
                "rule_code": i.rule_code,
                "severity": i.severity,
                "message": i.message,
                "compared_values": i.compared_values,
                "evidence": i.evidence,
                "status": i.status,
                "created_at": i.created_at,
            }
            for i in issues
        ],
        "issue_totals": {
            "total": len(issues),
            "by_severity": by_severity,
            "by_rule": by_rule,
            "by_status": by_status,
        },
        "documents": documents,
    }


@router.post("/jobs/{job_id}/compare", status_code=201)
def compare_job(
    job_id: UUID,
    db: Session = Depends(get_db),
):
    """Extract every document in a job, persist results, then run cross-document rules."""
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")

    documents = crud.list_documents(db, job_id)

    if not documents:
        raise HTTPException(
            400,
            "This job has no uploaded documents.",
        )

    missing_files = [
        d.filename for d in documents
        if not Path(d.file_path).is_file()
    ]
    if missing_files:
        raise HTTPException(
            404,
            detail={
                "message": "Some stored files are missing.",
                "files": missing_files,
            },
        )

    crud.update_job_status(db, job, "PROCESSING")

    try:
        extracted_by_type: dict[str, dict] = {}
        # Documents outside the 3 supported types are skipped, not fatal.
        skipped: list[dict] = []

        for document in documents:
            # 1. Reuse a previously successful extraction when one exists.
            cached = crud.get_latest_successful_extraction(db, document.id)

            if cached is not None:
                data = cached.extracted_data
                doc_type = _normalize_document_type(
                    data.get("document_type") or document.document_type
                )
            else:
                # 2. Otherwise read, classify and extract through the services.
                doc, detected_type = inspect_existing_document(document)

                # A Bill of Lading / contract / receipt is not one of the 3 types
                # this schema covers. Skip it instead of failing the whole job.
                if detected_type == DocumentType.UNKNOWN:
                    document.document_type = "OTHER"
                    document.page_count = len(doc.pages)
                    document.text_preview = doc.full_text[:3000]
                    document.page_sources = _page_sources(doc)
                    crud.update_document_status(db, document, "SUCCESS")
                    skipped.append({
                        "filename": document.filename,
                        "document_id": str(document.id),
                        "reason": "Could not classify as commercial_invoice, packing_list or bill_of_lading.",
                    })
                    continue

                try:
                    result = extract_structured_data(
                        doc, document_type=detected_type, model=DEFAULT_MODEL
                    )
                except ValueError as exc:
                    raise HTTPException(
                        422, f"Extraction failed for {document.filename}: {exc}"
                    ) from exc

                data = result.model_dump(mode="json")
                doc_type = _normalize_document_type(result.document_type)

                crud.create_extraction(
                    db=db,
                    document_id=document.id,
                    extracted_data=data,
                    # The schema stores provenance under `field_evidence`.
                    evidence=data.get("field_evidence") or {},
                    extraction_status="SUCCESS",
                    model_name=DEFAULT_MODEL,
                )

                # The DB CHECK constraint only allows UPPERCASE document types.
                document.document_type = _to_db_document_type(result.document_type)
                document.page_count = len(doc.pages)
                document.text_preview = doc.full_text[:3000]
                document.page_sources = _page_sources(doc)
                crud.update_document_status(db, document, "SUCCESS")

            extracted_by_type[doc_type] = data

        # 3. A comparison needs at least 2 distinct, recognised document types.
        recognized_types = sorted(extracted_by_type)

        if len(recognized_types) < MIN_TYPES_FOR_COMPARISON:
            raise HTTPException(
                422,
                detail={
                    "message": (
                        f"Cần ít nhất {MIN_TYPES_FOR_COMPARISON} loại chứng từ "
                        "khác nhau để so sánh. Chỉ có thể so sánh khi có ít nhất "
                        f"{MIN_TYPES_FOR_COMPARISON} tài liệu thuộc các loại: "
                        "commercial_invoice, packing_list, bill_of_lading."
                    ),
                    "recognized_document_types": recognized_types,
                    "skipped_documents": skipped,
                    "documents_processed": len(documents),
                },
            )

        # Missing types are reported, but do not block the comparison:
        # validate_documents already flags them via DOC-001 / REVIEW.
        missing_types = sorted(REQUIRED_DOCUMENT_TYPES - set(extracted_by_type))
        warnings: list[str] = []
        if missing_types:
            warnings.append(
                "Thiếu chứng từ: " + ", ".join(missing_types)
                + ". Các rule liên quan sẽ được đánh dấu REVIEW vì thiếu dữ liệu."
            )
        if skipped:
            warnings.append(
                f"{len(skipped)} tài liệu không thuộc các loại được hỗ trợ "
                "nên đã bị bỏ qua, không dùng để so sánh."
            )

        # 4. Deterministic cross-document validation (service/validation).
        report = validate_documents(list(extracted_by_type.values()))

        # 5. Record this execution in audit_runs so previous runs stay reviewable.
        run = crud.create_audit_run(
            db=db,
            job_id=job_id,
            risk_level=report.get("risk_level", "LOW"),
            summary=report.get("summary", {}),
            report={
                **report,
                "documents_used": recognized_types,
                "missing_document_types": missing_types,
                "unsupported_documents": skipped,
                "warnings": warnings,
            },
            documents_used=recognized_types,
            unsupported_documents=skipped,
            warnings=warnings,
            # Snapshot names/types so history survives later file deletion.
            document_snapshot=[
                {"id": str(d.id), "filename": d.filename,
                 "document_type": d.document_type}
                for d in crud.list_documents(db, job_id)
            ],
            model_name=DEFAULT_MODEL,
        )

        # 6. Persist FAIL/REVIEW findings; PASS stays in the response only.
        persisted_issue_ids: list[str] = []
        for finding in report["findings"]:
            if finding["status"] == "PASS":
                continue
            issue = crud.create_issue(
                db=db,
                job_id=job_id,
                rule_code=finding["rule_id"],
                # validation.py may emit INFO, which the DB CHECK constraint rejects.
                severity=_to_db_severity(finding["severity"]),
                message=finding["message"],
                compared_values={
                    "documents": finding["documents"],
                    "status": finding["status"],
                },
                # `evidence` is NOT NULL in Postgres, so never pass None.
                evidence=finding["evidence"] or {},
                audit_run_id=run.id,
            )
            persisted_issue_ids.append(str(issue.id))

        # Persist the full report so the UI can reopen it without re-running AI.
        job = crud.update_job_status(db, job, "COMPLETED")
        crud.save_audit_result(
            db=db,
            job=job,
            risk_level=report.get("risk_level", "LOW"),
            summary=report.get("summary", {}),
            report={
                **report,
                "documents_used": recognized_types,
                "missing_document_types": missing_types,
                "unsupported_documents": skipped,
                "warnings": warnings,
            },
        )

        return {
            "job_id": str(job_id),
            "status": job.status,
            "documents_processed": len(documents),
            "documents_used": recognized_types,
            "missing_document_types": missing_types,
            # Files that are not one of the supported types (UNKNOWN after detection).
            "unsupported_documents": skipped,
            "warnings": warnings,
            "model": DEFAULT_MODEL,
            "validation": report,
            "persisted_issue_ids": persisted_issue_ids,
            "run": {
                "id": str(run.id),
                "run_number": run.run_number,
                "created_at": run.created_at,
            },
            "total_runs": len(crud.list_audit_runs(db, job_id)),
        }

    except HTTPException:
        db.rollback()
        failed_job = crud.get_job(db, job_id)
        if failed_job is not None:
            crud.update_job_status(db, failed_job, "FAILED")
        raise
    except Exception:
        db.rollback()
        failed_job = crud.get_job(db, job_id)
        if failed_job is not None:
            crud.update_job_status(db, failed_job, "FAILED")
        raise