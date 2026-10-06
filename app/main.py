from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.document_reader import read_document
from app.services.extractor import detect_document_type, extract_structured_data
from app.services.schemas import DocumentType
from app.services.validation import validate_documents
from app.routers import jobs, documents, issues, extractation

load_dotenv()

app = FastAPI(
    title="Import Document Risk Checker",
    description="Cross-document consistency checks for CI / PL / BL shipments.",
    version="0.1.0",
)

app.include_router(jobs.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(issues.router, prefix="/api")
app.include_router(extractation.router, prefix="/api")

class DetectResponse(BaseModel):
    filename: str
    document_type: DocumentType
    page_count: int
    text_preview: str

class ValidationRequest(BaseModel):
    documents: list[dict]

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/documents/extract")
async def extract_document(file: UploadFile = File(...)):
    """Read and classify a file, then extract the matching Pydantic schema."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".txt", ".md"}:
        raise HTTPException(400, "Only PDF, TXT, and MD are supported in this MVP.")

    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        temp_path = tmp.name

    try:
        doc = read_document(
            temp_path,
            use_ocr_fallback=os.getenv("ENABLE_OCR_FALLBACK", "false").lower() == "true",
        )
        result = extract_structured_data(doc)
        return {
            "filename": file.filename or "uploaded",
            "page_count": len(doc.pages),
            "page_sources": [
                {"page": p.page_number, "source": p.source, "characters": len(p.text)}
                for p in doc.pages
            ],
            "extracted_data": result.model_dump(mode="json"),
        }
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc
    finally:
        Path(temp_path).unlink(missing_ok=True)

@app.post("/audit/validate")
def validate_audit(payload: ValidationRequest):
    """Step 5: deterministic cross-document rules; accepts extracted_data objects."""
    documents = []
    for item in payload.documents:
        # Accept either raw extraction objects or the wrapper returned by /documents/extract.
        extracted = item.get("extracted_data", item) if isinstance(item, dict) else item
        if isinstance(extracted, dict):
            documents.append(extracted)
    return validate_documents(documents)
