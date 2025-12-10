"""Code audit result model for storing security and quality audit findings."""

from sqlalchemy import Column, String, DateTime, Boolean, Integer, Text, Index, JSON
from sqlalchemy.sql import func
from app.database import Base


class CodeAuditResult(Base):
    """Stores results from code security and quality audits."""

    __tablename__ = "code_audit_results"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    run_id = Column(String(36), nullable=False, index=True)  # UUID for grouping issues from same run
    timestamp = Column(DateTime, server_default=func.now(), nullable=False)

    # Audit category
    category = Column(String(50), nullable=False)  # owasp, hipaa, performance, dead_code, ada, opswat

    # Issue details
    severity = Column(String(20), nullable=False)  # CRITICAL, HIGH, MEDIUM, LOW
    issue = Column(Text, nullable=False)
    location = Column(String(500), nullable=True)  # file:line or general description
    mitigation = Column(Text, nullable=True)

    # Resolution tracking
    resolution_status = Column(String(20), nullable=False, default="pending")  # pending, mitigated, risk_approved
    resolution_notes = Column(Text, nullable=True)  # Notes about resolution
    resolved_by = Column(String(100), nullable=True)  # User who resolved
    resolved_at = Column(DateTime, nullable=True)  # When resolved

    # Additional metadata
    extra_data = Column(JSON, nullable=True)  # For category-specific data (regulation, count, status)

    # Run metadata
    triggered_by = Column(String(100), nullable=True)  # user email or "scheduled"

    __table_args__ = (
        Index("idx_audit_run", "run_id"),
        Index("idx_audit_timestamp", "timestamp"),
        Index("idx_audit_category", "category"),
        Index("idx_audit_severity", "severity"),
        Index("idx_audit_resolution", "resolution_status"),
    )


class CodeAuditSchedule(Base):
    """Configuration for scheduled code audits."""

    __tablename__ = "code_audit_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    enabled = Column(Boolean, default=False, nullable=False)
    frequency = Column(String(20), nullable=False, default="weekly")  # daily, weekly, monthly
    day_of_week = Column(Integer, nullable=True, default=1)  # 0=Sunday, 1=Monday, etc.
    time_utc = Column(String(5), nullable=False, default="02:00")  # HH:MM format
    categories = Column(JSON, nullable=False)  # List of categories to audit
    email_notify = Column(Boolean, default=False, nullable=False)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    updated_by = Column(String(100), nullable=True)


class CodeAuditJob(Base):
    """Background job tracking for code audits."""

    __tablename__ = "code_audit_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    job_id = Column(String(36), nullable=False, unique=True, index=True)  # UUID for job tracking
    run_id = Column(String(36), nullable=True)  # Links to CodeAuditResult.run_id when complete
    status = Column(String(20), nullable=False, default="queued")  # queued, running, completed, failed
    progress = Column(Integer, nullable=False, default=0)  # 0-100 percent
    categories = Column(JSON, nullable=False)  # Categories being audited
    triggered_by = Column(String(100), nullable=True)  # User who triggered or "scheduled"
    error_message = Column(Text, nullable=True)  # Error details if failed
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_job_status", "status"),
    )
