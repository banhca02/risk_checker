
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.database import crud, schemas

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("", response_model=schemas.JobOut, status_code=201)
def create_job(
    payload: schemas.JobCreate,
    db: Session = Depends(get_db),
):
    return crud.create_job(db, payload.name)


@router.get("", response_model=list[schemas.JobSummaryOut])
def get_job_history(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Job history for the dashboard, with document and issue counts."""
    jobs = crud.list_jobs(db, limit, offset)
    return [
        schemas.JobSummaryOut(
            id=job.id,
            name=job.name,
            status=job.status,
            created_at=job.created_at,
            completed_at=job.completed_at,
            risk_level=job.risk_level,
            validation_summary=job.validation_summary,
            compared_at=job.compared_at,
            document_count=crud.count_documents(db, job.id),
            extracted_count=crud.count_extractions(db, job.id),
            issue_count=crud.count_issues(db, job.id),
        )
        for job in jobs
    ]


@router.get("/{job_id}", response_model=schemas.JobOut)
def get_job_detail(job_id: UUID, db: Session = Depends(get_db)):
    """Detail payload for the job page, read from DB without re-running AI."""
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    return schemas.JobOut(
        id=job.id,
        name=job.name,
        status=job.status,
        created_at=job.created_at,
        completed_at=job.completed_at,
        risk_level=job.risk_level,
        validation_summary=job.validation_summary,
        compared_at=job.compared_at,
        document_count=crud.count_documents(db, job.id),
    )


@router.patch("/{job_id}/status", response_model=schemas.JobOut)
def change_job_status(
    job_id: UUID,
    payload: schemas.JobStatusUpdate,
    db: Session = Depends(get_db),
):
    allowed = {"PENDING", "PROCESSING", "COMPLETED", "FAILED"}
    if payload.status not in allowed:
        raise HTTPException(400, "Invalid job status")

    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    return crud.update_job_status(db, job, payload.status)


@router.delete("/{job_id}", status_code=204)
def remove_job(job_id: UUID, db: Session = Depends(get_db)):
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    crud.delete_job(db, job)