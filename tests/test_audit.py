"""Tests for audit logging service."""

import pytest
from datetime import datetime, timedelta
from app.services.audit_service import AuditService
from app.models.audit_log import AuditLog


class TestAuditService:
    """Test suite for audit service."""

    def test_log_action_basic(self, db):
        """Test basic audit log creation."""
        service = AuditService(db)

        service.log_action(
            user_id="user-123",
            user_email="user@example.com",
            action="VIEW",
            resource_type="DOCUMENT",
            resource_id="456",
            success=True
        )

        # Check log was created
        logs = db.query(AuditLog).all()
        assert len(logs) == 1
        assert logs[0].user_id == "user-123"
        assert logs[0].action == "VIEW"
        assert logs[0].resource_type == "DOCUMENT"
        assert logs[0].success is True

    def test_log_action_with_phi(self, db):
        """Test audit log with PHI access tracking."""
        service = AuditService(db)

        service.log_action(
            user_id="user-123",
            user_email="user@example.com",
            action="VIEW",
            resource_type="DOCUMENT",
            resource_id="789",
            phi_accessed=["patient_name", "date_of_birth", "ssn"],
            success=True
        )

        log = db.query(AuditLog).first()
        import json
        phi_fields = json.loads(log.phi_accessed)
        assert "patient_name" in phi_fields
        assert "date_of_birth" in phi_fields
        assert "ssn" in phi_fields

    def test_sanitize_request_body(self, db):
        """Test that sensitive fields are redacted in logs."""
        service = AuditService(db)

        request_body = {
            "username": "john",
            "password": "secret123",
            "ssn": "123-45-6789",
            "data": "normal data"
        }

        sanitized = service._sanitize_request_body(request_body)

        assert sanitized["password"] == "[REDACTED]"
        assert sanitized["ssn"] == "[REDACTED]"
        assert sanitized["username"] == "john"
        assert sanitized["data"] == "normal data"

    def test_log_failed_action(self, db):
        """Test logging a failed action."""
        service = AuditService(db)

        service.log_action(
            user_id="user-123",
            user_email="user@example.com",
            action="DELETE",
            resource_type="USER",
            success=False,
            failure_reason="Insufficient permissions"
        )

        log = db.query(AuditLog).first()
        assert log.success is False
        assert log.failure_reason == "Insufficient permissions"

    def test_get_user_activity(self, db):
        """Test retrieving user activity."""
        service = AuditService(db)

        # Create multiple log entries
        for i in range(5):
            service.log_action(
                user_id="user-123",
                user_email="user@example.com",
                action=f"ACTION_{i}",
                resource_type="DOCUMENT",
                success=True
            )

        activity = service.get_user_activity("user-123", limit=10)
        assert len(activity) == 5

    def test_check_suspicious_activity_normal(self, db):
        """Test normal user activity is not flagged."""
        service = AuditService(db)

        # Create normal level of PHI access
        for i in range(5):
            service.log_action(
                user_id="user-123",
                user_email="user@example.com",
                action="VIEW",
                resource_type="DOCUMENT",
                resource_id=str(i),
                phi_accessed=["patient_name"],
                success=True
            )

        is_suspicious = service.check_suspicious_activity("user-123")
        assert is_suspicious is False
