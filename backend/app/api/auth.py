"""
api/auth.py
────────────────────────────────────────────────────────────
Authentication endpoints — fully DB-backed.

POST /auth/register  – create a new user account
POST /auth/login     – issue JWT tokens
POST /auth/logout    – client-side token discard (stateless)
GET  /auth/profile   – return current user info
"""

from __future__ import annotations

import re
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import get_logger
from app.core.security import (
    TokenData,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database import crud
from app.database.database import get_db
from app.database.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserProfileResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = get_logger("api.auth")

# Simple email regex (RFC 5322 lightweight version)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

VALID_ROLES = {"guardian", "doctor", "admin"}


# ── Helpers ───────────────────────────────────────────────

def _validate_email(email: str) -> None:
    if not _EMAIL_RE.match(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid email address.",
        )


def _validate_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Role must be one of: {', '.join(sorted(VALID_ROLES))}.",
        )


# ── Register ──────────────────────────────────────────────

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Create a new user account.

    Collects all required personal and professional details at sign-up:
      - Credentials: username, email, password
      - Personal: full_name, role, phone
      - Professional (doctors): specialization, hospital, license_number
      - Address: address, city, state, country

    Returns the created UserResponse (no sensitive fields).
    """
    # ── Validate inputs ───────────────────────────────────
    if body.password != body.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Passwords do not match.",
        )
    _validate_email(body.email)
    _validate_role(body.role)

    # ── Uniqueness checks ─────────────────────────────────
    if await crud.username_exists(db, body.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already taken.",
        )
    if await crud.email_exists(db, body.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    # ── Create user ───────────────────────────────────────
    user_data = {
        "username":       body.username.strip(),
        "email":          body.email.strip().lower(),
        "hashed_password": hash_password(body.password),
        "full_name":      body.full_name.strip(),
        "role":           body.role,
        "phone":          body.phone,
        "specialization": body.specialization,
        "hospital":       body.hospital,
        "license_number": body.license_number,
        "address":        body.address,
        "city":           body.city,
        "state":          body.state,
        "country":        body.country,
        "is_active":      True,
    }
    user = await crud.create_user(db, user_data)
    await db.commit()
    await db.refresh(user)

    logger.info("New user registered: '%s' (role=%s)", user.username, user.role)
    return user


# ── Login ─────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse, summary="Login and get JWT tokens")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate with username (or email) and password.

    Returns:
        access_token:  Short-lived JWT (60 minutes).
        refresh_token: Long-lived JWT (7 days).
    """
    # Allow login with either username or email
    user = await crud.get_user_by_username(db, body.username)
    if not user:
        user = await crud.get_user_by_email(db, body.username)

    if not user or not verify_password(body.password, user.hashed_password):
        logger.warning("Failed login attempt for '%s'", body.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated.",
        )

    token_data = {"sub": user.username, "role": user.role, "user_id": user.id}
    access_token  = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Stamp last_login (non-fatal if it fails)
    try:
        await crud.update_last_login(db, user.id)
        await db.commit()
    except Exception:
        pass

    logger.info("User '%s' logged in (role=%s)", user.username, user.role)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Logout ────────────────────────────────────────────────

@router.post("/logout", summary="Logout (invalidate client token)")
async def logout(current_user: TokenData = Depends(get_current_user)):
    """
    Logout endpoint.

    Since JWTs are stateless, the client discards the token.
    This endpoint exists for audit logging.
    """
    logger.info("User '%s' logged out", current_user.sub)
    return {"success": True, "message": "Logged out successfully."}


# ── Profile ───────────────────────────────────────────────

@router.get("/profile", response_model=UserProfileResponse, summary="Get current user profile")
async def get_profile(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's full profile from the database."""
    user = await crud.get_user_by_username(db, current_user.sub)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    return UserProfileResponse(
        username=user.username,
        role=user.role,
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        specialization=user.specialization,
        hospital=user.hospital,
        city=user.city,
        country=user.country,
    )


# ── Token Refresh ─────────────────────────────────────────

class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=TokenResponse, summary="Refresh access token")
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """
    Exchange a valid refresh token for a new access + refresh token pair.

    The backend is stateless (JWT), so any non-expired refresh token that
    was signed with the current JWT_SECRET is accepted.  The client should
    call this automatically when it receives a 401 on any protected endpoint.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token_data = decode_token(body.refresh_token)
    except HTTPException:
        raise credentials_exc

    # Re-validate user still exists and is active
    user = await crud.get_user_by_username(db, token_data.sub)
    if not user or not user.is_active:
        raise credentials_exc

    # Issue a fresh pair
    payload = {"sub": user.username, "role": user.role, "user_id": user.id}
    new_access  = create_access_token(payload)
    new_refresh = create_refresh_token(payload)

    logger.info("Tokens refreshed for user '%s'", user.username)
    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Email Verification ────────────────────────────────────

@router.get("/verify-email", summary="Verify email address via token link")
async def verify_email(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm an email verification link.

    Currently the backend does not send verification emails, so this
    endpoint accepts any valid JWT and returns a success response so the
    frontend VerifyEmail page does not error out.  When email verification
    is implemented, generate a short-lived signed token per-user here.
    """
    try:
        token_data = decode_token(token)
        user = await crud.get_user_by_username(db, token_data.sub)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        return {"success": True, "message": f"Email verified for {user.username}."}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification link.",
        )




@router.get("/me", response_model=UserResponse, summary="Get full current user record")
async def get_me(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full user record (all non-sensitive fields) for the logged-in user."""
    user = await crud.get_user_by_username(db, current_user.sub)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user
