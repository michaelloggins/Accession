"""Audit logging service for HIPAA compliance."""

from datetime import datetime
from sqlalchemy.orm import Session
import json
import logging

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    """Service for audit logging and PHI access tracking."""

    def __init__(self, db: Session):
        self.db = db
        self._config_cache = {}

    def _get_config(self, key: str, default: any = None) -> any:
        """Get configuration value with caching."""
        if key not in self._config_cache:
            try:
                from app.services.config_service import ConfigService
                config_service = ConfigService(self.db)
                self._config_cache[key] = config_service.get(key, default)
            except Exception:
                return default
        return self._config_cache.get(key, default)

    def _get_config_bool(self, key: str, default: bool = True) -> bool:
        """Get boolean configuration value."""
        try:
            from app.services.config_service import ConfigService
            config_service = ConfigService(self.db)
            return config_service.get_bool(key, default)
        except Exception:
            return default

    def log_action(
        self,
        user_id: str,
        user_email: str,
        action: str,
        resource_type: str,
        resource_id: str = None,
        phi_accessed: list = None,
        http_method: str = None,
        endpoint: str = None,
        request_body: dict = None,
        response_status: int = None,
        success: bool = True,
        failure_reason: str = None,
        user_ip: str = None,
        user_agent: str = None,
        session_id: str = None
    ):
        """Log an action for audit trail."""
        try:
            # Check if audit logging is enabled
            if not self._get_config_bool("AUDIT_LOG_ENABLED", True):
                return

            # Check if we should only log failures
            if self._get_config_bool("AUDIT_LOG_FAILED_ONLY", False) and success:
                return

            # Check if this action should be logged
            allowed_actions = self._get_config("AUDIT_LOG_ACTIONS", "")
            if allowed_actions:
                action_list = [a.strip().upper() for a in allowed_actions.split(",")]
                if action.upper() not in action_list:
                    return

            # Check PHI tracking setting
            if not self._get_config_bool("AUDIT_LOG_PHI_ACCESS", True):
                phi_accessed = None

            # Check IP tracking setting
            if not self._get_config_bool("AUDIT_IP_TRACKING", True):
                user_ip = None

            # Check user agent tracking setting
            if not self._get_config_bool("AUDIT_USER_AGENT_TRACKING", True):
                user_agent = None

            # Sanitize request body (remove sensitive data)
            sanitized_body = None
            if request_body and self._get_config_bool("AUDIT_LOG_REQUEST_BODY", False):
                sanitized_body = self._sanitize_request_body(request_body)

            audit_log = AuditLog(
                user_id=user_id,
                user_email=user_email,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                phi_accessed=json.dumps(phi_accessed) if phi_accessed else None,
                http_method=http_method,
                endpoint=endpoint,
                request_body=json.dumps(sanitized_body) if sanitized_body else None,
                response_status=response_status,
                success=success,
                failure_reason=failure_reason,
                user_ip=user_ip,
                user_agent=user_agent,
                session_id=session_id
            )

            self.db.add(audit_log)
            self.db.commit()

            logger.info(
                f"Audit log: {user_email} {action} {resource_type}/{resource_id} - "
                f"{'SUCCESS' if success else 'FAILURE'}"
            )

            # Check for suspicious activity
            if not success or (phi_accessed and len(phi_accessed) > 0):
                self._check_and_alert(user_id, action)

        except Exception as e:
            logger.error(f"Failed to create audit log: {e}")
            # Don't raise - audit logging should not break the application

    def _check_and_alert(self, user_id: str, action: str):
        """Check for suspicious activity and send alert if needed."""
        try:
            threshold = int(self._get_config("PHI_ACCESS_ALERT_THRESHOLD", "50"))
            if self.check_suspicious_activity(user_id, threshold):
                alert_email = self._get_config("AUDIT_ALERT_EMAIL", "")
                if alert_email:
                    logger.warning(
                        f"ALERT: Suspicious activity detected for user {user_id}. "
                        f"Alert would be sent to {alert_email}"
                    )
                    # TODO: Implement email alerting
        except Exception as e:
            logger.error(f"Error checking suspicious activity: {e}")

    def _sanitize_request_body(self, body: dict) -> dict:
        """Remove sensitive data from request body for logging."""
        sensitive_fields = [
            "password",
            "ssn",
            "social_security_number",
            "credit_card",
            "card_number",
            "cvv",
            "secret",
            "token"
        ]

        sanitized = body.copy()

        for field in sensitive_fields:
            if field in sanitized:
                sanitized[field] = "[REDACTED]"

        return sanitized

    def get_user_activity(self, user_id: str, limit: int = 100) -> list:
        """Get recent activity for a specific user."""
        logs = (
            self.db.query(AuditLog)
            .filter(AuditLog.user_id == user_id)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
            .all()
        )
        return logs

    def get_phi_access_count(self, user_id: str, start_date: datetime = None) -> int:
        """Count PHI access for a user within a time period."""
        query = self.db.query(AuditLog).filter(
            AuditLog.user_id == user_id,
            AuditLog.phi_accessed.isnot(None)
        )

        if start_date:
            query = query.filter(AuditLog.timestamp >= start_date)

        return query.count()

    def check_suspicious_activity(self, user_id: str, threshold: int = None) -> bool:
        """Check if user has suspicious PHI access patterns."""
        from datetime import timedelta

        if threshold is None:
            threshold = int(self._get_config("PHI_ACCESS_ALERT_THRESHOLD", "50"))

        # Count PHI accesses in last hour
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        count = self.get_phi_access_count(user_id, one_hour_ago)

        if count > threshold:
            logger.warning(
                f"Suspicious activity detected: User {user_id} accessed "
                f"{count} PHI records in 1 hour"
            )
            return True

        return False
