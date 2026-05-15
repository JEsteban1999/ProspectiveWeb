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


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    """Return User on success, None on bad credentials."""
    user = get_user_by_username(db, username)
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


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
        institution     = "Clinica Universidad de Navarra",
    )
    db.add(admin)
    db.commit()
    logger.warning(
        "Default admin account created (username=admin password=admin123). "
        "Change it immediately in production."
    )
