"""Integration configuration models."""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import secrets
import hashlib


class Integration(Base):
    """External integration configuration."""

    __tablename__ = "integrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)

    # Integration type
    integration_type = Column(String(50), nullable=False)
    # Types: rest_api, csv_upload, csv_pickup, m365_email, monday_com, webhook_inbound

    # Status: pending, active, inactive, error
    status = Column(String(20), default="pending")

    # Configuration stored as JSON
    config = Column(JSON, nullable=True)
    # REST API: {url, method, headers, auth_type, auth_config}
    # CSV Upload: {column_mapping, delimiter, encoding}
    # CSV Pickup: {storage_path, poll_interval, column_mapping}
    # M365 Email: {tenant_id, client_id, mailbox, folder}
    # Monday.com: {board_id, webhook_url}

    # Field mapping configuration (maps external fields to our document fields)
    field_mapping = Column(JSON, nullable=True)

    # MCP configuration if applicable
    mcp_enabled = Column(Boolean, default=False)
    mcp_server_name = Column(String(100), nullable=True)

    # Sample data for testing
    sample_payload = Column(Text, nullable=True)
    sample_result = Column(JSON, nullable=True)
    last_sample_test = Column(DateTime, nullable=True)

    # Statistics
    total_received = Column(Integer, default=0)
    total_processed = Column(Integer, default=0)
    total_errors = Column(Integer, default=0)
    last_received_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    last_error_at = Column(DateTime, nullable=True)

    # Audit fields
    created_at = Column(DateTime, server_default=func.now())
    created_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    updated_by = Column(String(100), nullable=True)

    # Relationship to API keys
    api_keys = relationship("ApiKey", back_populates="integration", cascade="all, delete-orphan")

    # Integration type constants
    TYPE_REST_API = "rest_api"
    TYPE_CSV_UPLOAD = "csv_upload"
    TYPE_CSV_PICKUP = "csv_pickup"
    TYPE_M365_EMAIL = "m365_email"
    TYPE_MONDAY_COM = "monday_com"
    TYPE_WEBHOOK_INBOUND = "webhook_inbound"
    TYPE_LIMS = "lims"
    TYPE_AZURE_SERVICES = "azure_services"

    VALID_TYPES = [
        TYPE_REST_API,
        TYPE_CSV_UPLOAD,
        TYPE_CSV_PICKUP,
        TYPE_M365_EMAIL,
        TYPE_MONDAY_COM,
        TYPE_WEBHOOK_INBOUND,
        TYPE_LIMS,
        TYPE_AZURE_SERVICES,
    ]

    # Status constants
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_ERROR = "error"

    VALID_STATUSES = [STATUS_PENDING, STATUS_ACTIVE, STATUS_INACTIVE, STATUS_ERROR]

    def is_data_flow_allowed(self) -> bool:
        """Check if data from this integration should be processed into the data stream."""
        return self.status == self.STATUS_ACTIVE

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "integration_type": self.integration_type,
            "status": self.status,
            "config": self.config,
            "field_mapping": self.field_mapping,
            "mcp_enabled": self.mcp_enabled,
            "mcp_server_name": self.mcp_server_name,
            "sample_payload": self.sample_payload,
            "sample_result": self.sample_result,
            "last_sample_test": self.last_sample_test.isoformat() if self.last_sample_test else None,
            "total_received": self.total_received,
            "total_processed": self.total_processed,
            "total_errors": self.total_errors,
            "last_received_at": self.last_received_at.isoformat() if self.last_received_at else None,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ApiKey(Base):
    """API keys for external integrations to authenticate with this system."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)

    # The key itself (hashed for storage, prefix stored for identification)
    key_prefix = Column(String(8), nullable=False)  # First 8 chars for identification
    key_hash = Column(String(64), nullable=False)  # SHA-256 hash of full key

    # Associated integration (optional - key can be general purpose)
    integration_id = Column(Integer, ForeignKey("integrations.id"), nullable=True)
    integration = relationship("Integration", back_populates="api_keys")

    # Permissions/scopes
    scopes = Column(JSON, nullable=True)
    # e.g., ["documents:create", "documents:read", "integrations:webhook"]

    # Status
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)

    # Usage tracking
    last_used_at = Column(DateTime, nullable=True)
    last_used_ip = Column(String(45), nullable=True)
    usage_count = Column(Integer, default=0)

    # Rate limiting
    rate_limit_per_minute = Column(Integer, default=60)
    rate_limit_per_day = Column(Integer, default=10000)

    # Audit fields
    created_at = Column(DateTime, server_default=func.now())
    created_by = Column(String(100), nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(100), nullable=True)

    # Default scopes
    SCOPE_DOCUMENTS_CREATE = "documents:create"
    SCOPE_DOCUMENTS_READ = "documents:read"
    SCOPE_WEBHOOK_RECEIVE = "integrations:webhook"
    SCOPE_ADMIN = "admin"

    @staticmethod
    def generate_key() -> tuple:
        """
        Generate a new API key.

        Returns:
            Tuple of (full_key, prefix, hash)
            The full_key should be shown once to the user and never stored.
        """
        # Generate a secure random key: dk_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
        random_part = secrets.token_hex(24)  # 48 characters
        full_key = f"dk_live_{random_part}"

        # Get prefix for identification
        prefix = full_key[:8]

        # Hash for storage
        key_hash = hashlib.sha256(full_key.encode()).hexdigest()

        return full_key, prefix, key_hash

    @staticmethod
    def hash_key(key: str) -> str:
        """Hash an API key for comparison."""
        return hashlib.sha256(key.encode()).hexdigest()

    def verify_key(self, key: str) -> bool:
        """Verify if a provided key matches this API key."""
        return self.key_hash == self.hash_key(key)

    def is_valid(self) -> bool:
        """Check if the API key is currently valid."""
        from datetime import datetime

        if not self.is_active:
            return False

        if self.revoked_at is not None:
            return False

        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False

        return True

    def has_scope(self, scope: str) -> bool:
        """Check if the key has a specific scope."""
        if not self.scopes:
            return False
        if self.SCOPE_ADMIN in self.scopes:
            return True
        return scope in self.scopes

    def to_dict(self, include_key: bool = False, full_key: str = None) -> dict:
        """Convert to dictionary for API response."""
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "key_prefix": self.key_prefix,
            "integration_id": self.integration_id,
            "scopes": self.scopes,
            "is_active": self.is_active,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "usage_count": self.usage_count,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "rate_limit_per_day": self.rate_limit_per_day,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

        # Only include the full key on creation
        if include_key and full_key:
            result["key"] = full_key

        return result


class IntegrationLog(Base):
    """Log of integration activity for debugging and auditing."""

    __tablename__ = "integration_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    integration_id = Column(Integer, ForeignKey("integrations.id"), nullable=False)

    # Event type: received, processed, error, test
    event_type = Column(String(20), nullable=False)

    # Request/response data (sanitized - no PHI)
    request_summary = Column(Text, nullable=True)
    response_summary = Column(Text, nullable=True)

    # Status and error info
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)

    # Document created (if any)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)

    # Timing
    created_at = Column(DateTime, server_default=func.now())
    processing_time_ms = Column(Integer, nullable=True)
