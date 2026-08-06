"""Authentication router — real JWT login/me (Session D)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from models import (
    LoginRequest, LoginResponse, UserInfo,
    SignupRequest, SignupResponse, PendingUser,
    UserAdminInfo, UserUpdate,
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

# Profile photo + CV uploaded at signup. Stored OUTSIDE the public /data mount
# (these are personal documents) and served only through admin-authenticated
# endpoints below.
_USER_FILES = Path("user_files")
_MAX_UPLOAD_BYTES = 6 * 1024 * 1024   # 6 MB


async def _save_user_upload(upload: UploadFile, subdir: str, user_id: int) -> str:
    """Persist an uploaded profile file; return its stored path. Raises on size."""
    data = await upload.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el máximo de 6 MB.")
    suffix = Path(upload.filename or "").suffix.lower()[:10]
    dest_dir = _USER_FILES / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{user_id}{suffix}"
    dest.write_bytes(data)
    return str(dest)


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
        has_photo=bool(user.photo_path and Path(user.photo_path).exists()),
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

    from services.audit import audit_append, ACT_LOGIN
    audit_append(ACT_LOGIN, {"role": user.role}, username=user.username)

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


@router.get(
    "/me/photo",
    summary="Download the current user's profile photo",
    description="Serves the authenticated user's own profile photo (404 if none).",
)
async def get_my_photo(
    current_user: Annotated[User, Depends(require_user)],
) -> FileResponse:
    if not current_user.photo_path or not Path(current_user.photo_path).exists():
        raise HTTPException(status_code=404, detail="Sin foto de perfil.")
    return FileResponse(current_user.photo_path)


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
    db: Annotated[Session, Depends(get_db)],
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    national_id: str = Form(""),
    professional_id: str = Form(""),
    specialty: str = Form(""),
    university: str = Form(""),
    hospital: str = Form(""),
    position: str = Form(""),
    orcid: str = Form(""),
    photo: UploadFile | None = File(None),
    cv: UploadFile | None = File(None),
) -> SignupResponse:
    user, err = create_pending_user(
        db, username=username, password=password, full_name=full_name,
        national_id=national_id, professional_id=professional_id, specialty=specialty,
        university=university, hospital=hospital, position=position, orcid=orcid,
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)

    # Store the optional profile photo / CV named by the new user's id.
    changed = False
    if photo is not None and photo.filename:
        user.photo_path = await _save_user_upload(photo, "photos", user.id)
        changed = True
    if cv is not None and cv.filename:
        user.cv_path = await _save_user_upload(cv, "cv", user.id)
        changed = True
    if changed:
        db.commit()

    return SignupResponse(
        status="pending",
        message=(
            "Solicitud enviada. Un administrador revisará tu cuenta y podrás "
            "iniciar sesión en cuanto sea aprobada."
        ),
    )


# ── Admin: serve a pending user's uploaded photo / CV ──────────────────────── #

@router.get(
    "/pending/{user_id}/photo",
    summary="Download a pending user's profile photo (admin)",
)
async def get_pending_photo(
    user_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    user = db.get(User, user_id)
    if user is None or not user.photo_path or not Path(user.photo_path).exists():
        raise HTTPException(status_code=404, detail="Sin foto de perfil.")
    return FileResponse(user.photo_path)


@router.get(
    "/pending/{user_id}/cv",
    summary="Download a pending user's CV (admin)",
)
async def get_pending_cv(
    user_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    user = db.get(User, user_id)
    if user is None or not user.cv_path or not Path(user.cv_path).exists():
        raise HTTPException(status_code=404, detail="Sin CV adjunto.")
    p = Path(user.cv_path)
    return FileResponse(p, filename=f"CV_{user.username}{p.suffix}")


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
        has_photo=bool(u.photo_path),
        has_cv=bool(u.cv_path),
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


# ── Admin: full user management ────────────────────────────────────────────── #

def _user_to_admin(u: User) -> UserAdminInfo:
    return UserAdminInfo(
        id=u.id,
        username=u.username,
        full_name=u.full_name,
        role=u.role if u.role in ("admin", "medico", "residente", "viewer") else "viewer",
        status=u.status,
        is_active=u.is_active,
        specialty=u.specialty,
        hospital=u.hospital,
        has_photo=bool(u.photo_path),
        has_cv=bool(u.cv_path),
        created_at=u.created_at.isoformat() if u.created_at else "",
    )


@router.get(
    "/users",
    response_model=list[UserAdminInfo],
    summary="List all users (admin)",
)
async def list_users(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[UserAdminInfo]:
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [_user_to_admin(u) for u in users]


@router.put(
    "/users/{user_id}",
    response_model=UserAdminInfo,
    summary="Update a user (admin)",
)
async def update_user(
    user_id: int,
    req: UserUpdate,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> UserAdminInfo:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")

    # Lockout guards: an admin can't strip their own admin role or deactivate
    # themselves (would lock them out of the panel they're using).
    if user.id == admin.id:
        if req.role is not None and req.role != "admin":
            raise HTTPException(status_code=400, detail="No puedes quitarte tu propio rol de administrador.")
        if req.is_active is False:
            raise HTTPException(status_code=400, detail="No puedes desactivar tu propia cuenta.")

    if req.full_name is not None:
        user.full_name = req.full_name.strip()
    if req.role is not None:
        user.role = req.role
    if req.is_active is not None:
        user.is_active = req.is_active
        user.status = User.STATUS_ACTIVE if req.is_active else User.STATUS_REJECTED
    db.commit()
    db.refresh(user)
    logger.info("User updated by admin — id=%d role=%s active=%s", user.id, user.role, user.is_active)
    return _user_to_admin(user)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user (admin)",
)
async def delete_user(
    user_id: int,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propia cuenta.")
    # Don't delete the last active admin.
    if user.role == "admin":
        other_admins = db.query(User).filter(
            User.role == "admin", User.is_active == True, User.id != user_id  # noqa: E712
        ).count()
        if other_admins == 0:
            raise HTTPException(status_code=400, detail="No puedes eliminar al último administrador.")
    # Patients created by this user are kept (created_by → dangling is tolerated;
    # the FK is nullable). Detach them to be clean.
    from services.db_models import Patient
    db.query(Patient).filter(Patient.created_by == user_id).update({"created_by": None})
    db.delete(user)
    db.commit()
    logger.info("User deleted by admin — id=%d username=%s", user_id, user.username)
