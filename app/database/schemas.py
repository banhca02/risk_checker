
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class JobStatusUpdate(BaseModel):
    status: str


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str | None
    status: str
    created_at: datetime
    completed_at: datetime | None
    risk_level: str | None = None
    validation_summary: dict[str, Any] | None = None
    compared_at: datetime | None = None
    # Aggregates used by the history dashboard.
    document_count: int = 0


class JobSummaryOut(JobOut):
    """Job row enriched with document counts for the dashboard."""

    extracted_count: int = 0
    issue_count: int = 0


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    filename: str
    document_type: str
    file_path: str
    page_count: int | None
    read_status: str
    created_at: datetime


class ExtractionCreate(BaseModel):
    extracted_data: dict[str, Any]
    evidence: dict[str, Any] | list[Any] | None = None
    extraction_status: str = "SUCCESS"
    model_name: str | None = None


class ExtractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    extracted_data: dict[str, Any]
    evidence: dict[str, Any] | list[Any] | None
    extraction_status: str
    model_name: str | None
    created_at: datetime


class IssueStatusUpdate(BaseModel):
    status: str


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    rule_code: str
    severity: str
    message: str
    compared_values: dict[str, Any] | None
    evidence: dict[str, Any] | list[Any] | None
    status: str
    created_at: datetime