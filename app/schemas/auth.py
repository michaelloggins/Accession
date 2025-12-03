"""Authentication schemas."""

from pydantic import BaseModel, EmailStr
from typing import Optional


class LoginRequest(BaseModel):
    """Login request schema. MFA is handled by Azure AD SSO."""
    email: EmailStr
    password: str


class UserInfo(BaseModel):
    """User information in login response."""
    id: str
    email: str
    full_name: str
    role: str


class LoginResponse(BaseModel):
    """Login response schema."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserInfo


class LogoutResponse(BaseModel):
    """Logout response schema."""
    message: str
    session_terminated: bool


class TokenData(BaseModel):
    """JWT token data."""
    user_id: str
    email: str
    role: str
    exp: int
