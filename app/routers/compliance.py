"""Compliance and audit API endpoints."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
import logging

from app.database import get_db
from app.schemas.compliance import AuditLogResponse, ComplianceReportResponse
from app.services.compliance_service import ComplianceService
from app.services.auth_service import require_admin

router = APIRouter()
logger = logging.getLogger(__name__)


def get_admin_user(request: Request, db: Session = Depends(get_db)):
    """Dependency to require admin role for compliance endpoints."""
    return require_admin(request, db)


@router.get("/audit-logs", response_model=AuditLogResponse)
async def get_audit_logs(
    request: Request,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
    admin_user: dict = Depends(get_admin_user)
):
    """Get audit logs with optional filters. Requires admin role."""
    compliance_service = ComplianceService(db)

    logs = compliance_service.get_audit_logs(
        start_date=start_date,
        end_date=end_date,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        limit=limit
    )

    return AuditLogResponse(
        total=len(logs),
        logs=logs
    )


@router.get("/report", response_model=ComplianceReportResponse)
async def generate_compliance_report(
    request: Request,
    report_type: str = Query(..., pattern="^(phi_access|user_activity|document_processing)$"),
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
    format: str = Query(default="json", pattern="^(json|csv|pdf)$"),
    db: Session = Depends(get_db),
    admin_user: dict = Depends(get_admin_user)
):
    """Generate compliance report. Requires admin role."""
    compliance_service = ComplianceService(db)

    report = compliance_service.generate_report(
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        format=format,
        generated_by="current_user"
    )

    return report


@router.get("/phi-access-summary")
async def get_phi_access_summary(
    request: Request,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    admin_user: dict = Depends(get_admin_user)
):
    """Get summary of PHI access for compliance dashboard. Requires admin role."""
    compliance_service = ComplianceService(db)
    return compliance_service.get_phi_access_summary(start_date, end_date)


@router.get("/user-activity")
async def get_user_activity(
    request: Request,
    user_id: Optional[str] = None,
    days: int = Query(default=30, le=365),
    db: Session = Depends(get_db),
    admin_user: dict = Depends(get_admin_user)
):
    """Get user activity report. Requires admin role."""
    compliance_service = ComplianceService(db)
    return compliance_service.get_user_activity(user_id, days)
