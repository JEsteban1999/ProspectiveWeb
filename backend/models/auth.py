"""Authentication and user management models.

Matches prospective/auth/auth_manager.py and prospective/db/models.py (User table).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

UserRole = Literal["admin", "medico", "residente", "viewer"]


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, description="Username or email")
    password: str = Field(..., min_length=6, description="Password (never logged)")


class LoginResponse(BaseModel):
    access_token: str = Field(..., description="JWT bearer token — include in Authorization header")
    token_type: str = Field("bearer", description="Always 'bearer'")
    user: "UserInfo"
    expires_in: int = Field(..., description="Token lifetime in seconds")


class UserInfo(BaseModel):
    """Public user data returned after login and in /me endpoint."""

    id: int
    username: str
    full_name: str
    role: UserRole
    institution: str = Field("", description="Hospital or institution name")
    avatar_initials: str = Field(
        ..., description="Two-letter initials for the avatar widget (e.g. 'JN')"
    )


class UserCreateRequest(BaseModel):
    """Admin-only: create a new user account."""

    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    full_name: str
    role: UserRole
    institution: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)
