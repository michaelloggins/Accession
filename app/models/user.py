"""User model for authentication and authorization."""

from sqlalchemy import Column, String, DateTime, Boolean, Integer, Index, Text
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    """User model for system users."""

    __tablename__ = "users"

    id = Column(String(100), primary_key=True)  # Azure AD Object ID or local UUID
    email = Column(String(255), unique=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    first_name = Column(String(100), nullable=True)  # Given name from Entra ID
    last_name = Column(String(100), nullable=True)   # Family name from Entra ID
    role = Column(String(50), nullable=False)

    # Status
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime, nullable=True)

    # Entra ID / Azure AD fields
    entra_id = Column(String(100), unique=True, nullable=True, index=True)  # Azure AD Object ID (GUID)
    entra_upn = Column(String(255), nullable=True)  # User Principal Name from Entra ID
    auth_provider = Column(String(50), default="local")  # "local" or "entra_id"
    last_synced_at = Column(DateTime, nullable=True)  # Last SCIM sync timestamp
    photo_url = Column(Text, nullable=True)  # Profile photo as data URI (base64)

    # Security
    mfa_enabled = Column(Boolean, default=False)
    failed_login_attempts = Column(Integer, default=0)
    account_locked_until = Column(DateTime, nullable=True)

    # Break Glass Authentication (emergency access when SSO is unavailable)
    hashed_password = Column(String(255), nullable=True)  # bcrypt hash
    is_break_glass = Column(Boolean, default=False)  # True for break glass accounts only

    # Audit
    created_at = Column(DateTime, server_default=func.now())
    created_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    deactivated_at = Column(DateTime, nullable=True)
    deactivated_by = Column(String(100), nullable=True)

    __table_args__ = (
        Index("idx_email", "email"),
        Index("idx_role", "role"),
        Index("idx_is_active", "is_active"),
        Index("idx_entra_id", "entra_id"),
        Index("idx_auth_provider", "auth_provider"),
    )
