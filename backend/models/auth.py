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
    has_photo: bool = Field(False, description="A profile photo is available at /api/auth/me/photo")


class UserCreateRequest(BaseModel):
    """Admin-only: create a new user account."""

    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    full_name: str
    role: UserRole
    institution: str = ""


class ChangePasswordRequest(BaseModel):
    """Self-service password change — the current one is required."""

    current_password: str
    new_password: str = Field(..., min_length=8)


class ResetPasswordRequest(BaseModel):
    """Admin resetting someone else's password (no current password needed)."""

    new_password: str = Field(..., min_length=8)


# ── Self-registration + admin approval ─────────────────────────────────────── #

class SignupRequest(BaseModel):
    """Public self-registration — creates a pending account for admin review."""

    username: str = Field(..., min_length=3, description="Desired username")
    password: str = Field(..., min_length=8, description="Password (min 8 chars)")
    full_name: str = Field(..., min_length=1, description="Full professional name")

    # Optional professional profile (shown to the admin during review)
    national_id: str = Field("", description="National ID / cédula")
    professional_id: str = Field("", description="Professional licence ID")
    specialty: str = Field("", description="Medical specialty")
    university: str = Field("", description="Affiliated university")
    hospital: str = Field("", description="Hospital / centre")
    position: str = Field("", description="Role / position")
    orcid: str = Field("", description="ORCID identifier")


class SignupResponse(BaseModel):
    status: str = Field(..., description="Always 'pending' on success")
    message: str = Field(..., description="Human-readable confirmation for the UI")


class PendingUser(BaseModel):
    """One pending registration request, shown in the admin approval panel."""

    id: int
    username: str
    full_name: str
    national_id: str = ""
    professional_id: str = ""
    specialty: str = ""
    university: str = ""
    hospital: str = ""
    position: str = ""
    orcid: str = ""
    has_photo: bool = Field(False, description="A profile photo was uploaded")
    has_cv: bool = Field(False, description="A CV document was uploaded")
    created_at: str = Field(..., description="ISO-8601 timestamp of the request")


class UserAdminInfo(BaseModel):
    """Full user record for the admin user-management panel."""

    id: int
    username: str
    full_name: str
    role: UserRole
    status: str = Field("", description="active | pending | rejected")
    is_active: bool = True
    specialty: str = ""
    hospital: str = ""
    has_photo: bool = False
    has_cv: bool = False
    created_at: str = ""


class UserUpdate(BaseModel):
    """Admin edit of a user account."""

    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
