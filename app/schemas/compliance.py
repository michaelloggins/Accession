"""Compliance and audit schemas."""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class AuditLogItem(BaseModel):
    """Single audit log entry."""
    timestamp: datetime
    user_email: str
    action: str
    resource: str
    phi_accessed: Optional[List[str]] = None
    success: bool
    ip_address: Optional[str] = None


class AuditLogResponse(BaseModel):
    """Response for audit log query."""
    total: int
    logs: List[AuditLogItem]


class ReportSummary(BaseModel):
    """Summary statistics for compliance report."""
    total_phi_accesses: int
    unique_users: int
    unique_documents: int


class ComplianceReportResponse(BaseModel):
    """Response for compliance report generation."""
    report_id: str
    report_type: str
    period: str
    generated_at: datetime
    generated_by: str
    summary: ReportSummary
    download_url: Optional[str] = None
