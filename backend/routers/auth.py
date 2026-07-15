"""Authentication router — real JWT login/me (Session D)."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from models import (
    LoginRequest, LoginResponse, UserInfo,
    SignupRequest, SignupResponse, PendingUser,
)
from services.database import get_db
from services.auth_service import (
    ACCESS_TOKEN_EXPIRE_MIN,
    AuthError,
    approve_user,
    authenticate_user,
    create_access_token,
    create_pending_user,
    get_pending_users,
    reject_user,
    require_admin,
    require_user,
)
from services.db_models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_to_info(user: User) -> UserInfo:
    """Map ORM User → Pydantic UserInfo."""
    initials = "".join(
        part[0].upper()
        for part in user.full_name.split()
        if part
    )[:2] or user.username[:2].upper()

    return UserInfo(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        institution=user.institution,
        avatar_initials=initials,
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login and obtain JWT token",
    description=(
        "Authenticates with username + password and returns a signed JWT.\n\n"
        "Include the token in subsequent requests as:\n"
        "`Authorization: Bearer <token>`\n\n"
        "Default credentials on first run: **admin / admin123**."
    ),
)
async def login(
    req: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    try:
        user = authenticate_user(db, req.username, req.password)
    except AuthError as exc:
        # Account exists but is blocked (pending approval / rejected / disabled)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(subject=user.username)

    logger.info("Login OK — user=%s role=%s", user.username, user.role)

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MIN * 60,
        user=_user_to_info(user),
    )


@router.get(
    "/me",
    response_model=UserInfo,
    summary="Get current authenticated user",
    description="Returns the profile of the user identified by the Bearer token.",
)
async def me(
    current_user: Annotated[User, Depends(require_user)],
) -> UserInfo:
    return _user_to_info(current_user)


# ── Self-registration (public) ─────────────────────────────────────────────── #

@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a new account",
    description=(
        "Public self-registration. Creates a **pending** account that an "
        "administrator must approve before the user can log in."
    ),
)
async def signup(
    req: SignupRequest,
    db: Annotated[Session, Depends(get_db)],
) -> SignupResponse:
    user, err = create_pending_user(db, **req.model_dump())
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    return SignupResponse(
        status="pending",
        message=(
            "Solicitud enviada. Un administrador revisará tu cuenta y podrás "
            "iniciar sesión en cuanto sea aprobada."
        ),
    )


# ── Admin: pending-account review ──────────────────────────────────────────── #

def _pending_to_api(u: User) -> PendingUser:
    return PendingUser(
        id=u.id,
        username=u.username,
        full_name=u.full_name,
        national_id=u.national_id,
        professional_id=u.professional_id,
        specialty=u.specialty,
        university=u.university,
        hospital=u.hospital,
        position=u.position,
        orcid=u.orcid,
        created_at=u.created_at.isoformat() if u.created_at else "",
    )


@router.get(
    "/pending",
    response_model=list[PendingUser],
    summary="List pending account requests (admin)",
    description="Returns all self-registrations awaiting approval. Admin only.",
)
async def list_pending(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[PendingUser]:
    return [_pending_to_api(u) for u in get_pending_users(db)]


@router.post(
    "/pending/{user_id}/approve",
    summary="Approve a pending account (admin)",
    description="Activates the account so the user can log in. Admin only.",
)
async def approve(
    user_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    ok, err = approve_user(db, user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
    return {"status": "active"}


@router.post(
    "/pending/{user_id}/reject",
    summary="Reject a pending account (admin)",
    description="Marks the request as rejected; the user cannot log in. Admin only.",
)
async def reject(
    user_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    ok, err = reject_user(db, user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err)
    return {"status": "rejected"}
