"""JWT authentication helpers + FastAPI dependencies — Session D.

Token format: Bearer JWT (HS256).
Secret key: env var JWT_SECRET or auto-generated and persisted to data/jwt_secret.txt.

Dependencies (for use in FastAPI endpoint signatures)
-----------------------------------------------------
get_optional_user(db, credentials)  -> User | None   (never raises)
get_current_user(user)              -> User | None   (never raises)
require_user(user)                  -> User          (raises HTTP 401)
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from services.database import SessionLocal, get_db
from services.db_models import User

logger = logging.getLogger(__name__)

# ── JWT configuration ──────────────────────────────────────────────────────── #

ALGORITHM               = "HS256"
ACCESS_TOKEN_EXPIRE_MIN = 60 * 24   # 24 hours

_SECRET_FILE = Path(__file__).resolve().parents[1] / "data" / "jwt_secret.txt"


def _load_or_generate_secret() -> str:
    if env := os.environ.get("JWT_SECRET"):
        return env
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text().strip()
    key = secrets.token_hex(32)
    _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SECRET_FILE.write_text(key)
    logger.info("Generated new JWT secret key at %s", _SECRET_FILE)
    return key


SECRET_KEY = _load_or_generate_secret()

# ── Password hashing ───────────────────────────────────────────────────────── #

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return _pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


# ── User queries ───────────────────────────────────────────────────────────── #

def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username, User.is_active == True).first()


class AuthError(Exception):
    """Raised on login when the account exists but cannot sign in (pending/rejected)."""


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    """Return User on success, None on bad credentials.

    Raises AuthError with a user-facing message when the account exists but its
    status blocks login (pending approval / rejected).
    """
    # Look up regardless of is_active so we can explain *why* login is blocked.
    user = db.query(User).filter(User.username == username.strip()).first()
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None

    status_val = getattr(user, "status", User.STATUS_ACTIVE)
    if status_val == User.STATUS_PENDING:
        raise AuthError(
            "Tu cuenta está pendiente de aprobación. Un administrador debe "
            "activarla antes de que puedas iniciar sesión."
        )
    if status_val == User.STATUS_REJECTED:
        raise AuthError("Tu solicitud de registro fue rechazada. Contacta al administrador.")
    if not user.is_active:
        raise AuthError("Cuenta desactivada. Contacta al administrador.")
    return user


# ── Self-registration + admin approval ─────────────────────────────────────── #

def create_pending_user(db: Session, **fields) -> tuple[User | None, str]:
    """Create a pending (inactive) account from a self-registration request."""
    username = str(fields.get("username", "")).strip()
    password = str(fields.get("password", ""))
    if len(username) < 3:
        return None, "El nombre de usuario debe tener al menos 3 caracteres."
    if len(password) < 8:
        return None, "La contraseña debe tener al menos 8 caracteres."
    if db.query(User).filter(User.username == username).first() is not None:
        return None, f"El usuario '{username}' ya existe."

    user = User(
        username        = username,
        hashed_password = get_password_hash(password),
        full_name       = str(fields.get("full_name", "")).strip(),
        role            = "medico",
        institution     = str(fields.get("hospital", "")).strip(),
        is_active       = False,
        status          = User.STATUS_PENDING,
        national_id     = str(fields.get("national_id", "")).strip(),
        professional_id = str(fields.get("professional_id", "")).strip(),
        specialty       = str(fields.get("specialty", "")).strip(),
        university       = str(fields.get("university", "")).strip(),
        hospital        = str(fields.get("hospital", "")).strip(),
        position        = str(fields.get("position", "")).strip(),
        orcid           = str(fields.get("orcid", "")).strip(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("Signup request created: %s (%s)", username, user.specialty)
    return user, ""


def get_pending_users(db: Session) -> list[User]:
    return (
        db.query(User)
        .filter(User.status == User.STATUS_PENDING)
        .order_by(User.created_at)
        .all()
    )


def approve_user(db: Session, user_id: int) -> tuple[bool, str]:
    user = db.get(User, user_id)
    if user is None:
        return False, "Usuario no encontrado."
    user.is_active = True
    user.status = User.STATUS_ACTIVE
    db.commit()
    logger.info("User approved: %s", user.username)
    return True, ""


def reject_user(db: Session, user_id: int) -> tuple[bool, str]:
    user = db.get(User, user_id)
    if user is None:
        return False, "Usuario no encontrado."
    user.status = User.STATUS_REJECTED
    user.is_active = False
    db.commit()
    logger.info("User rejected: %s", user.username)
    return True, ""


# ── JWT creation / parsing ─────────────────────────────────────────────────── #

def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT with sub=subject and exp claim."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MIN)
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT.  Raises JWTError on failure."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# ── FastAPI security scheme ────────────────────────────────────────────────── #

# auto_error=False → returns None instead of 403 when no token is present
_bearer = HTTPBearer(auto_error=False)


def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    """Extract and verify the JWT from the Authorization header.

    Returns the User on success, None when no/invalid token is provided.
    Never raises — callers decide whether auth is mandatory.
    """
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
        username: str = payload.get("sub", "")
        if not username:
            return None
        return get_user_by_username(db, username)
    except JWTError:
        return None


def get_current_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User | None:
    """Alias of get_optional_user (explicit naming for endpoint signatures)."""
    return user


def require_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    """Dependency that enforces authentication.  Raises HTTP 401 if no valid token."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required — provide a valid Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_admin(
    user: Annotated[User, Depends(require_user)],
) -> User:
    """Dependency that enforces the admin role.  Raises HTTP 403 otherwise."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador.",
        )
    return user


# ── DB seeding ─────────────────────────────────────────────────────────────── #

def seed_default_user(db: Session) -> None:
    """Create default admin account on first run (only if no users exist).

    Credentials: admin / admin123
    Change via POST /api/auth/change-password after first login.
    """
    if db.query(User).count() > 0:
        return
    admin = User(
        username        = "admin",
        hashed_password = get_password_hash("admin123"),
        full_name       = "Administrador",
        role            = "admin",
        institution     = "Clinica UniNavarra",
    )
    db.add(admin)
    db.commit()
    logger.warning(
        "Default admin account created (username=admin password=admin123). "
        "Change it immediately in production."
    )
