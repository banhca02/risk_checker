from __future__ import annotations

import json
import os
from typing import Type

from openai import OpenAI
from pydantic import BaseModel

from app.services.schemas import (
    CommonDocumentData, DocumentType, CommercialInvoiceData, PackingListData,
    BillOfLadingData
)
from app.services.document_reader import ReadDocument
from dotenv import load_dotenv

load_dotenv()
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")


SCHEMA_BY_TYPE: dict[DocumentType, Type[CommonDocumentData]] = {
    DocumentType.COMMERCIAL_INVOICE: CommercialInvoiceData,
    DocumentType.PACKING_LIST: PackingListData,
    DocumentType.BILL_OF_LADING: BillOfLadingData,
}


def _client() -> OpenAI:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in .env")
        
    return OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )


def detect_document_type(text: str, model: str = DEFAULT_MODEL) -> DocumentType:
    """Classify a document using its text. Keep UNKNOWN if classification is unclear."""
    client = _client()
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify the shipment document as exactly one of: "
                    "commercial_invoice, packing_list, bill_of_lading, unknown. "
                    "Return JSON only: "
                    '{"document_type":"...","reason":"..."}. '
                    "Use the visible document title (COMMERCIAL INVOICE, PACKING LIST, "
                    "BILL OF LADING) and content. If ambiguous, use unknown."
                ),
            },
            {"role": "user", "content": text[:30000]},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    try:
        return DocumentType(payload.get("document_type", "unknown"))
    except ValueError:
        return DocumentType.UNKNOWN


def extract_structured_data(
    document: ReadDocument,
    document_type: DocumentType | None = None,
    model: str = DEFAULT_MODEL,
) -> CommonDocumentData:
    """
    Step 3: ask the LLM for structured data, then validate the response with Pydantic.
    The model must not invent missing values. Evidence should cite page + source quote.
    """
    text = document.full_text
    if not text.strip():
        raise ValueError(
            "No readable text found. This may be a scanned PDF; enable OCR fallback "
            "or use a vision model."
        )

    detected_type = document_type or detect_document_type(text, model=model)
    if detected_type == DocumentType.UNKNOWN:
        raise ValueError("Could not confidently classify document type.")

    schema_cls = SCHEMA_BY_TYPE[detected_type]
    client = _client()

    # OpenAI's JSON schema structured output is used here. Keep model output limited
    # to the schema; Pydantic performs a second local validation after parsing.
    schema = schema_cls.model_json_schema()
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": f"{detected_type.value}_extraction",
                "strict": False,
                "schema": schema,
            },
        },
        messages=[
            {
                "role": "system",
                "content": (
                    "You extract structured fields from shipment documents "
                    "(Commercial Invoice, Packing List, Bill of Lading). "
                    "Return only information supported by the source. Never guess. "
                    "Use null for absent or unreadable scalar fields and [] for absent "
                    "lists. Keep monetary amounts, weights and quantities numeric "
                    "without thousand separators; put the unit in the *_unit / "
                    "price_basis fields (e.g. DRUMS, USD/KG). "
                    "Dates should be YYYY-MM-DD only when unambiguous; otherwise "
                    "preserve the source date in extraction_notes and set the date "
                    "field null. Preserve every line item and container row, keeping "
                    "container_no and seal_no attached to their own row. "
                    "For field_evidence, include the 1-based page and a short source "
                    "quote for important extracted values. Distinguish seller from "
                    "buyer, and shipper from consignee. "
                    "Do not confuse Commercial Invoice number with contract or "
                    "booking numbers."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Filename: {document.filename}\n"
                    f"Detected document type: {detected_type.value}\n\n"
                    f"DOCUMENT TEXT:\n{text[:50000]}"
                ),
            },
        ],
    )

    raw = response.choices[0].message.content
    if not raw:
        raise ValueError("LLM returned an empty response.")

    data = json.loads(raw)
    data["document_type"] = detected_type.value
    return schema_cls.model_validate(data)
