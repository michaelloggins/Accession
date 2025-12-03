"""Audit log model for HIPAA compliance tracking."""

from sqlalchemy import Column, BigInteger, String, DateTime, Boolean, Integer, Text, Index
from sqlalchemy.sql import func
from app.database import Base


class AuditLog(Base):
    """Audit log for tracking all PHI access and system actions."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    timestamp = Column(DateTime, server_default=func.now())

    # User information
    user_id = Column(String(100), nullable=False)
    user_email = Column(String(255), nullable=False)
    user_ip = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)

    # Action details
    action = Column(String(50), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(100), nullable=True)

    # PHI access tracking
    phi_accessed = Column(Text, nullable=True)  # JSON array of field names

    # Request details
    http_method = Column(String(10), nullable=True)
    endpoint = Column(String(500), nullable=True)
    request_body = Column(Text, nullable=True)  # Sanitized
    response_status = Column(Integer, nullable=True)

    # Results
    success = Column(Boolean, nullable=False)
    failure_reason = Column(Text, nullable=True)

    # Session
    session_id = Column(String(100), nullable=True)

    __table_args__ = (
        Index("idx_timestamp", "timestamp"),
        Index("idx_user_id", "user_id"),
        Index("idx_resource", "resource_type", "resource_id"),
        Index("idx_action", "action"),
    )
