
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    Integer,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Text
from app.database import Base


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # Audit outcome, written when /AI/jobs/{id}/compare completes.
    risk_level: Mapped[str | None] = mapped_column(String(20))
    validation_summary: Mapped[dict | None] = mapped_column(JSONB)
    validation_report: Mapped[dict | None] = mapped_column(JSONB)
    compared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    issues: Mapped[list["ValidationIssue"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    runs: Mapped[list["AuditRun"]] = relationship(
        back_populates="job", cascade="all, delete-orphan",
        order_by="AuditRun.run_number",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_processing_jobs_status",
        ),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="UNKNOWN"
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    read_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["ProcessingJob"] = relationship(back_populates="documents")
    extractions: Mapped[list["DocumentExtraction"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    file_sha256: Mapped[str | None] = mapped_column(
        String(64), index=True
    )
    text_preview: Mapped[str | None] = mapped_column(Text)
    page_sources: Mapped[dict | list | None] = mapped_column(JSONB)


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    extracted_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict | list | None] = mapped_column(JSONB)
    extraction_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    model_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    document: Mapped["Document"] = relationship(back_populates="extractions")


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Which compare run produced this issue (None for manual issues).
    audit_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_runs.id", ondelete="CASCADE"),
        index=True,
    )
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="MEDIUM"
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    compared_values: Mapped[dict | None] = mapped_column(JSONB)
    evidence: Mapped[dict | list | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="OPEN"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["ProcessingJob"] = relationship(back_populates="issues")
    audit_run: Mapped["AuditRun | None"] = relationship(
        back_populates="issues"
    )

class AuditRun(Base):
    """One compare execution. Kept so previous runs stay reviewable."""

    __tablename__ = "audit_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str | None] = mapped_column(String(20))
    summary: Mapped[dict | None] = mapped_column(JSONB)
    report: Mapped[dict] = mapped_column(JSONB, nullable=False)
    documents_used: Mapped[list | None] = mapped_column(JSONB)
    unsupported_documents: Mapped[list | None] = mapped_column(JSONB)
    warnings: Mapped[list | None] = mapped_column(JSONB)
    # filename + document_type at run time, so history survives file deletion.
    document_snapshot: Mapped[list | None] = mapped_column(JSONB)
    model_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["ProcessingJob"] = relationship(back_populates="runs")
    issues: Mapped[list["ValidationIssue"]] = relationship(
        back_populates="audit_run", cascade="all, delete-orphan"
    )
