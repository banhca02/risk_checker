
import os
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.database import crud, schemas

router = APIRouter(prefix="/documents", tags=["Documents"])

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./storage")).resolve()
ALLOWED_TYPES = {
    "COMMERCIAL_INVOICE",
    "PACKING_LIST",
    "BILL_OF_LADING",
    "UNKNOWN",
}


def _reject_if_reviewing(run_id: UUID | None) -> None:
    """Block writes while reviewing a previous compare run (history = read-only)."""
    if run_id is not None:
        raise HTTPException(
            409,
            detail=(
                "Đang ở chế độ xem lịch sử kiểm tra nên không thể thêm hoặc xóa "
                "chứng từ. Quay lại lần kiểm tra mới nhất để chỉnh sửa bộ chứng từ."
            ),
        )


@router.post("/upload", response_model=schemas.DocumentOut, status_code=201)
def upload_document(
    job_id: UUID = Form(...),
    document_type: str = Form("UNKNOWN"),
    file: UploadFile = File(...),
    run_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
):
    _reject_if_reviewing(run_id)
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if document_type not in ALLOWED_TYPES:
        raise HTTPException(400, "Invalid document_type")

    original_name = Path(file.filename or "upload.pdf").name
    if Path(original_name).suffix.lower() not in {".pdf", ".txt", ".md"}:
        raise HTTPException(400, "Only PDF, TXT and MD files are allowed")

    target_dir = STORAGE_DIR / "jobs" / str(job_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{__import__('uuid').uuid4().hex}_{original_name}"
    target_path = target_dir / stored_name

    try:
        with target_path.open("wb") as output:
            shutil.copyfileobj(file.file, output)

        document = crud.create_document(
            db=db,
            job_id=job_id,
            filename=original_name,
            document_type=document_type,
            file_path=str(target_path),
        )
        return document

    except Exception:
        target_path.unlink(missing_ok=True)
        raise HTTPException(500, "Failed to save document")

    finally:
        file.file.close()


@router.get("/by-job/{job_id}", response_model=list[schemas.DocumentOut])
def get_documents(job_id: UUID, db: Session = Depends(get_db)):
    if not crud.get_job(db, job_id):
        raise HTTPException(404, "Job not found")

    return crud.list_documents(db, job_id)


@router.get("/{document_id}", response_model=schemas.DocumentOut)
def get_document(document_id: UUID, db: Session = Depends(get_db)):
    document = crud.get_document(db, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    return document


@router.patch("/{document_id}/status", response_model=schemas.DocumentOut)
def change_document_status(
    document_id: UUID,
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    if status not in {"PENDING", "SUCCESS", "FAILED"}:
        raise HTTPException(400, "Invalid read_status")

    document = crud.get_document(db, document_id)
    if not document:
        raise HTTPException(404, "Document not found")

    return crud.update_document_status(db, document, status)


@router.get(
    "/{document_id}/extractions",
    response_model=list[schemas.ExtractionOut],
)
def get_extractions(
    document_id: UUID,
    db: Session = Depends(get_db),
):
    if not crud.get_document(db, document_id):
        raise HTTPException(404, "Document not found")

    return crud.list_extractions(db, document_id)


@router.post(
    "/{document_id}/extractions",
    response_model=schemas.ExtractionOut,
    status_code=201,
)
def save_extraction(
    document_id: UUID,
    payload: schemas.ExtractionCreate,
    db: Session = Depends(get_db),
):
    if not crud.get_document(db, document_id):
        raise HTTPException(404, "Document not found")

    return crud.create_extraction(
        db=db,
        document_id=document_id,
        extracted_data=payload.extracted_data,
        evidence=payload.evidence,
        extraction_status=payload.extraction_status,
        model_name=payload.model_name,
    )


@router.delete("/{document_id}", status_code=204)
def remove_document(
    document_id: UUID,
    run_id: UUID | None = Query(None),
    db: Session = Depends(get_db),
):
    """Delete a document, its extractions, and the stored file."""
    _reject_if_reviewing(run_id)
    document = crud.get_document(db, document_id)
    if not document:
        raise HTTPException(404, "Document not found")

    crud.delete_document(db, document)
    # Remove the physical file only after the DB commit succeeds.
    Path(document.file_path).unlink(missing_ok=True)


@router.get("/{document_id}/file")
def download_document_file(document_id: UUID, db: Session = Depends(get_db)):
    """Stream the stored file so the UI can preview it."""
    document = crud.get_document(db, document_id)
    if not document:
        raise HTTPException(404, "Document not found")

    path = Path(document.file_path)
    if not path.is_file():
        raise HTTPException(404, "Stored file is missing")

    media_types = {
        ".pdf": "application/pdf",
        ".txt": "text/plain; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
    }
    return FileResponse(
        path,
        media_type=media_types.get(path.suffix.lower(), "application/octet-stream"),
        filename=document.filename,
        # Without this, FileResponse sends Content-Disposition: attachment and the
        # browser downloads the file instead of rendering it inside the iframe.
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/{document_id}/text")
def get_document_text(document_id: UUID, db: Session = Depends(get_db)):
    """Extracted text preview, used by the viewer for TXT/MD files."""
    document = crud.get_document(db, document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    return {
        "id": str(document.id),
        "filename": document.filename,
        "document_type": document.document_type,
        "page_count": document.page_count,
        "read_status": document.read_status,
        "text_preview": document.text_preview or "",
        "page_sources": document.page_sources or [],
    }


@router.get("/{document_id}/extractions/latest", response_model=schemas.ExtractionOut)
def get_latest_extraction(
    document_id: UUID,
    db: Session = Depends(get_db),
):
    """Most recent successful extraction for the viewer panel."""
    if not crud.get_document(db, document_id):
        raise HTTPException(404, "Document not found")

    extraction = crud.get_latest_successful_extraction(db, document_id)
    if not extraction:
        raise HTTPException(404, "No successful extraction for this document")

    return extraction