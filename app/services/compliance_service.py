"""Compliance and reporting service."""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
import json
import uuid
import logging

from app.models.audit_log import AuditLog
from app.schemas.compliance import (
    AuditLogItem,
    ComplianceReportResponse,
    ReportSummary
)

logger = logging.getLogger(__name__)


class ComplianceService:
    """Service for compliance reporting and audit log management."""

    def __init__(self, db: Session):
        self.db = db

    def get_audit_logs(
        self,
        start_date: datetime = None,
        end_date: datetime = None,
        user_id: str = None,
        action: str = None,
        resource_type: str = None,
        limit: int = 100
    ) -> list:
        """Get filtered audit logs."""
        query = self.db.query(AuditLog)

        if start_date:
            query = query.filter(AuditLog.timestamp >= start_date)

        if end_date:
            query = query.filter(AuditLog.timestamp <= end_date)

        if user_id:
            query = query.filter(AuditLog.user_id == user_id)

        if action:
            query = query.filter(AuditLog.action == action)

        if resource_type:
            query = query.filter(AuditLog.resource_type == resource_type)

        logs = query.order_by(AuditLog.timestamp.desc()).limit(limit).all()

        return [
            AuditLogItem(
                timestamp=log.timestamp,
                user_email=log.user_email,
                action=log.action,
                resource=f"{log.resource_type}/{log.resource_id}",
                phi_accessed=json.loads(log.phi_accessed) if log.phi_accessed else None,
                success=log.success,
                ip_address=log.user_ip
            )
            for log in logs
        ]

    def generate_report(
        self,
        report_type: str,
        start_date: datetime,
        end_date: datetime,
        format: str,
        generated_by: str
    ) -> ComplianceReportResponse:
        """Generate a compliance report."""
        report_id = f"RPT-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        # Calculate summary statistics based on report type
        if report_type == "phi_access":
            summary = self._generate_phi_access_summary(start_date, end_date)
        elif report_type == "user_activity":
            summary = self._generate_user_activity_summary(start_date, end_date)
        elif report_type == "document_processing":
            summary = self._generate_document_processing_summary(start_date, end_date)
        else:
            summary = ReportSummary(
                total_phi_accesses=0,
                unique_users=0,
                unique_documents=0
            )

        # In production, generate actual report file and upload to blob storage
        download_url = None

        return ComplianceReportResponse(
            report_id=report_id,
            report_type=report_type,
            period=f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            generated_at=datetime.utcnow(),
            generated_by=generated_by,
            summary=summary,
            download_url=download_url
        )

    def _generate_phi_access_summary(self, start_date: datetime, end_date: datetime) -> ReportSummary:
        """Generate PHI access summary."""
        phi_accesses = (
            self.db.query(AuditLog)
            .filter(
                AuditLog.timestamp >= start_date,
                AuditLog.timestamp <= end_date,
                AuditLog.phi_accessed.isnot(None)
            )
            .all()
        )

        unique_users = set()
        unique_documents = set()

        for log in phi_accesses:
            unique_users.add(log.user_id)
            if log.resource_type == "DOCUMENT" and log.resource_id:
                unique_documents.add(log.resource_id)

        return ReportSummary(
            total_phi_accesses=len(phi_accesses),
            unique_users=len(unique_users),
            unique_documents=len(unique_documents)
        )

    def _generate_user_activity_summary(self, start_date: datetime, end_date: datetime) -> ReportSummary:
        """Generate user activity summary."""
        logs = (
            self.db.query(AuditLog)
            .filter(
                AuditLog.timestamp >= start_date,
                AuditLog.timestamp <= end_date
            )
            .all()
        )

        unique_users = set()
        unique_documents = set()
        phi_count = 0

        for log in logs:
            unique_users.add(log.user_id)
            if log.resource_type == "DOCUMENT" and log.resource_id:
                unique_documents.add(log.resource_id)
            if log.phi_accessed:
                phi_count += 1

        return ReportSummary(
            total_phi_accesses=phi_count,
            unique_users=len(unique_users),
            unique_documents=len(unique_documents)
        )

    def _generate_document_processing_summary(self, start_date: datetime, end_date: datetime) -> ReportSummary:
        """Generate document processing summary."""
        # This would query the documents table
        return ReportSummary(
            total_phi_accesses=0,
            unique_users=0,
            unique_documents=0
        )

    def get_phi_access_summary(self, start_date: datetime = None, end_date: datetime = None) -> dict:
        """Get summary of PHI access for compliance dashboard."""
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)

        if not end_date:
            end_date = datetime.utcnow()

        summary = self._generate_phi_access_summary(start_date, end_date)

        return {
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "total_phi_accesses": summary.total_phi_accesses,
            "unique_users": summary.unique_users,
            "unique_documents": summary.unique_documents
        }

    def get_user_activity(self, user_id: str = None, days: int = 30) -> dict:
        """Get user activity report."""
        start_date = datetime.utcnow() - timedelta(days=days)

        query = self.db.query(AuditLog).filter(AuditLog.timestamp >= start_date)

        if user_id:
            query = query.filter(AuditLog.user_id == user_id)

        logs = query.all()

        # Aggregate by action type
        action_counts = {}
        for log in logs:
            if log.action not in action_counts:
                action_counts[log.action] = 0
            action_counts[log.action] += 1

        return {
            "period_days": days,
            "total_actions": len(logs),
            "actions_by_type": action_counts,
            "user_id": user_id
        }
