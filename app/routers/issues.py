
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.database import crud, schemas

router = APIRouter(prefix="/issues", tags=["Validation Issues"])


@router.get(
    "/by-job/{job_id}",
    response_model=list[schemas.IssueOut],
)
def get_issues(
    job_id: UUID,
    status: str | None = Query(None),
    db: Session = Depends(get_db),
):
    if not crud.get_job(db, job_id):
        raise HTTPException(404, "Job not found")

    if status and status not in {
        "OPEN", "REVIEWED", "RESOLVED", "DISMISSED"
    }:
        raise HTTPException(400, "Invalid issue status")

    return crud.list_issues(db, job_id, status)


@router.get("/{issue_id}", response_model=schemas.IssueOut)
def get_issue(issue_id: UUID, db: Session = Depends(get_db)):
    issue = crud.get_issue(db, issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")
    return issue


@router.patch("/{issue_id}/status", response_model=schemas.IssueOut)
def change_issue_status(
    issue_id: UUID,
    payload: schemas.IssueStatusUpdate,
    db: Session = Depends(get_db),
):
    if payload.status not in {
        "OPEN", "REVIEWED", "RESOLVED", "DISMISSED"
    }:
        raise HTTPException(400, "Invalid issue status")

    issue = crud.get_issue(db, issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")

    return crud.update_issue_status(db, issue, payload.status)