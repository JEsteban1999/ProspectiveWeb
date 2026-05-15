"""Authentication router — real JWT login/me (Session D)."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from models import LoginRequest, LoginResponse, UserInfo
from services.database import get_db
from services.auth_service import (
    ACCESS_TOKEN_EXPIRE_MIN,
    authenticate_user,
    create_access_token,
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
    user = authenticate_user(db, req.username, req.password)
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
