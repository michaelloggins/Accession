"""Pydantic schemas for request/response validation."""

from app.schemas.auth import LoginRequest, LoginResponse, LogoutResponse, TokenData
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentResponse,
    DocumentListResponse,
    ReviewRequest,
    ReviewResponse,
    RejectRequest,
    ExtractedData,
)
from app.schemas.compliance import AuditLogResponse, ComplianceReportResponse
from app.schemas.stats import StatsResponse
from app.schemas.user import UserCreate, UserResponse, UserUpdate

__all__ = [
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "TokenData",
    "DocumentUploadResponse",
    "DocumentResponse",
    "DocumentListResponse",
    "ReviewRequest",
    "ReviewResponse",
    "RejectRequest",
    "ExtractedData",
    "AuditLogResponse",
    "ComplianceReportResponse",
    "StatsResponse",
    "UserCreate",
    "UserResponse",
    "UserUpdate",
]
