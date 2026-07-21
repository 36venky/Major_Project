"""
core/security.py
────────────────
JWT authentication and password hashing utilities.

Roles:
  - admin    : Full access
  - doctor   : Read + write patient data, generate reports
  - guardian : Read patient data, update weekly health values

All protected endpoints use FastAPI Dependency Injection via `get_current_user`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import bcrypt as _bcrypt_lib
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger("api.security")

# ── OAuth2 token URL ──────────────────────────────────────
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Token payload model ───────────────────────────────────
class TokenData(BaseModel):
    sub: str               # username / user id
    role: str = "guardian"
    exp: Optional[datetime] = None


# ── Password utilities ────────────────────────────────────

def hash_password(plain: str) -> str:
    """Return bcrypt hash of a plain-text password."""
    return _bcrypt_lib.hashpw(plain.encode("utf-8"), _bcrypt_lib.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against its bcrypt hash."""
    return _bcrypt_lib.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── Default users (replace with DB-backed user store in production) ─
_USERS: dict[str, dict] = {
    "admin": {
        "username": "admin",
        "hashed_password": hash_password("admin123"),
        "role": "admin",
        "full_name": "System Administrator",
    },
    "doctor": {
        "username": "doctor",
        "hashed_password": hash_password("doctor123"),
        "role": "doctor",
        "full_name": "Dr. Ramesh Kumar",
    },
    "guardian": {
        "username": "guardian",
        "hashed_password": hash_password("guardian123"),
        "role": "guardian",
        "full_name": "Priya Sharma",
    },
}


# ── Token creation ────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a signed JWT access token.

    Args:
        data:          Payload dict (must include 'sub').
        expires_delta: Token lifetime. Defaults to configured value.

    Returns:
        Encoded JWT string.
    """
    payload = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload["exp"] = expire
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    logger.debug("Access token created for subject '%s'", data.get("sub"))
    return token


def create_refresh_token(data: dict) -> str:
    """Create a long-lived refresh token."""
    return create_access_token(
        data,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


# ── Token validation ──────────────────────────────────────

def decode_token(token: str) -> TokenData:
    """
    Decode and validate a JWT token.

    Raises:
        HTTPException 401 if token is invalid or expired.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        sub: Optional[str] = payload.get("sub")
        role: str = payload.get("role", "guardian")
        if sub is None:
            raise credentials_exc
        return TokenData(sub=sub, role=role)
    except JWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise credentials_exc


# ── User lookup ───────────────────────────────────────────

def authenticate_user(username: str, password: str) -> Optional[dict]:
    """
    Verify username and password against the user store.

    Returns the user dict on success, None on failure.
    """
    user = _USERS.get(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user


# ── FastAPI Dependencies ──────────────────────────────────

async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    """Dependency: extract and validate the current user from bearer token."""
    return decode_token(token)


async def require_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Dependency: restrict endpoint to admin role."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


async def require_doctor_or_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Dependency: restrict endpoint to doctor or admin role."""
    if current_user.role not in ("doctor", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor or admin access required")
    return current_user
