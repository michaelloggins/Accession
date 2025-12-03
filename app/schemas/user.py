"""User schemas."""

from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    """Schema for creating a new user."""
    id: str
    email: EmailStr
    full_name: str
    role: str


class UserUpdate(BaseModel):
    """Schema for updating a user."""
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """User response schema."""
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    last_login: Optional[datetime] = None
    mfa_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True
