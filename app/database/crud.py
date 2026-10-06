
from datetime import datetime, timezone
from uuid import UUID
import hashlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import (
    ProcessingJob,
    Document,
    DocumentExtraction,
    ValidationIssue,
    AuditRun,
)


# ---------- JOBS ----------

def create_job(db: Session, name: str) -> ProcessingJob:
    job = ProcessingJob(name=name, status="PENDING")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: UUID):
    return db.get(ProcessingJob, job_id)


def list_jobs(db: Session, limit: int = 20, offset: int = 0):
    stmt = (
        select(ProcessingJob)
        .order_by(ProcessingJob.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return db.scalars(stmt).all()


def save_audit_result(
    db: Session,
    job: ProcessingJob,
    risk_level: str,
    summary: dict,
    report: dict,
):
    """Persist the validation outcome so it can be reviewed without re-running AI."""
    job.risk_level = risk_level
    job.validation_summary = summary
    job.validation_report = report
    job.compared_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


def count_documents(db: Session, job_id: UUID) -> int:
    stmt = select(func.count(Document.id)).where(Document.job_id == job_id)
    return db.scalar(stmt) or 0


def count_extractions(db: Session, job_id: UUID) -> int:
    stmt = (
        select(func.count(DocumentExtraction.id))
        .join(Document, DocumentExtraction.document_id == Document.id)
        .where(Document.job_id == job_id)
    )
    return db.scalar(stmt) or 0


def count_issues(db: Session, job_id: UUID) -> int:
    stmt = select(func.count(ValidationIssue.id)).where(
        ValidationIssue.job_id == job_id
    )
    return db.scalar(stmt) or 0


def update_job_status(db: Session, job: ProcessingJob, status: str):
    job.status = status

    if status in ("COMPLETED", "FAILED"):
        job.completed_at = datetime.now(timezone.utc)
    else:
        job.completed_at = None

    db.commit()
    db.refresh(job)
    return job


def delete_job(db: Session, job: ProcessingJob):
    db.delete(job)
    db.commit()


# ---------- DOCUMENTS ----------

def create_document(
    db: Session,
    job_id: UUID,
    filename: str,
    document_type: str,
    file_path: str,
) -> Document:
    document = Document(
        job_id=job_id,
        filename=filename,
        document_type=document_type,
        file_path=file_path,
        read_status="PENDING",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def get_document(db: Session, document_id: UUID):
    return db.get(Document, document_id)


def list_documents(db: Session, job_id: UUID):
    stmt = (
        select(Document)
        .where(Document.job_id == job_id)
        .order_by(Document.created_at.asc())
    )
    return db.scalars(stmt).all()


def update_document_status(
    db: Session, document: Document, status: str
):
    document.read_status = status
    db.commit()
    db.refresh(document)
    return document


def delete_document(db: Session, document: Document):
    # Xóa metadata và extraction liên quan trong DB.
    # Không tự xóa file vật lý ở đây.
    db.delete(document)
    db.commit()


# ---------- EXTRACTIONS ----------

def create_extraction(
    db: Session,
    document_id: UUID,
    extracted_data: dict,
    evidence: dict | list | None = None,
    extraction_status: str = "SUCCESS",
    model_name: str | None = None,
):
    extraction = DocumentExtraction(
        document_id=document_id,
        extracted_data=extracted_data,
        evidence=evidence,
        extraction_status=extraction_status,
        model_name=model_name,
    )
    db.add(extraction)
    db.commit()
    db.refresh(extraction)
    return extraction


def list_extractions(db: Session, document_id: UUID):
    stmt = (
        select(DocumentExtraction)
        .where(DocumentExtraction.document_id == document_id)
        .order_by(DocumentExtraction.created_at.desc())
    )
    return db.scalars(stmt).all()


# ---------- VALIDATION ISSUES ----------

def list_issues(
    db: Session,
    job_id: UUID,
    status: str | None = None,
):
    stmt = select(ValidationIssue).where(
        ValidationIssue.job_id == job_id
    )

    if status:
        stmt = stmt.where(ValidationIssue.status == status)

    stmt = stmt.order_by(ValidationIssue.created_at.desc())
    return db.scalars(stmt).all()


def create_issue(
    db: Session,
    job_id: UUID,
    rule_code: str,
    severity: str,
    message: str,
    compared_values: dict | None = None,
    evidence: dict | list | None = None,
    audit_run_id: UUID | None = None,
):
    issue = ValidationIssue(
        job_id=job_id,
        audit_run_id=audit_run_id,
        rule_code=rule_code,
        severity=severity,
        message=message,
        compared_values=compared_values,
        evidence=evidence,
        status="OPEN",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue


def update_issue_status(
    db: Session, issue: ValidationIssue, status: str
):
    issue.status = status
    db.commit()
    db.refresh(issue)
    return issue


def get_issue(db: Session, issue_id: UUID):
    return db.get(ValidationIssue, issue_id)

def calculate_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def get_cached_document(db: Session, file_sha256: str):
    stmt = (
        select(Document)
        .where(Document.file_sha256 == file_sha256)
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def get_latest_successful_extraction(
    db: Session,
    document_id: UUID,
):
    stmt = (
        select(DocumentExtraction)
        .where(
            DocumentExtraction.document_id == document_id,
            DocumentExtraction.extraction_status == "SUCCESS",
        )
        .order_by(DocumentExtraction.created_at.desc())
        .limit(1)
    )
    return db.scalar(stmt)

# ---------- AUDIT RUNS (compare history) ----------

def next_run_number(db: Session, job_id: UUID) -> int:
    current = db.scalar(
        select(func.max(AuditRun.run_number)).where(AuditRun.job_id == job_id)
    )
    return (current or 0) + 1


def create_audit_run(
    db: Session,
    job_id: UUID,
    risk_level: str,
    summary: dict,
    report: dict,
    documents_used: list,
    unsupported_documents: list,
    warnings: list,
    document_snapshot: list,
    model_name: str | None = None,
) -> AuditRun:
    run = AuditRun(
        job_id=job_id,
        run_number=next_run_number(db, job_id),
        risk_level=risk_level,
        summary=summary,
        report=report,
        documents_used=documents_used,
        unsupported_documents=unsupported_documents,
        warnings=warnings,
        document_snapshot=document_snapshot,
        model_name=model_name,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def list_audit_runs(db: Session, job_id: UUID) -> list[AuditRun]:
    stmt = (
        select(AuditRun)
        .where(AuditRun.job_id == job_id)
        .order_by(AuditRun.run_number.desc())
    )
    return list(db.scalars(stmt).all())


def get_audit_run(db: Session, job_id: UUID, run_id: UUID) -> AuditRun | None:
    stmt = select(AuditRun).where(
        AuditRun.id == run_id, AuditRun.job_id == job_id
    )
    return db.scalar(stmt)


def get_latest_audit_run(db: Session, job_id: UUID) -> AuditRun | None:
    stmt = (
        select(AuditRun)
        .where(AuditRun.job_id == job_id)
        .order_by(AuditRun.run_number.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def list_run_issues(db: Session, run_id: UUID) -> list[ValidationIssue]:
    stmt = (
        select(ValidationIssue)
        .where(ValidationIssue.audit_run_id == run_id)
        .order_by(ValidationIssue.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def count_run_issues(db: Session, run_id: UUID) -> int:
    stmt = select(func.count(ValidationIssue.id)).where(
        ValidationIssue.audit_run_id == run_id
    )
    return db.scalar(stmt) or 0
