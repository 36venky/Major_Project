"""
api/auth.py
────────────
Authentication endpoints.

POST /auth/login    – issue JWT tokens
POST /auth/logout   – client-side token discard (stateless)
GET  /auth/profile  – return current user info
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.core.logger import get_logger
from app.core.security import (
    TokenData, authenticate_user, create_access_token,
    create_refresh_token, get_current_user,
)
from app.database.schemas import LoginRequest, TokenResponse, UserProfileResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = get_logger("api.auth")

_USERS_META = {
    "admin":    {"full_name": "System Administrator", "role": "admin"},
    "doctor":   {"full_name": "Dr. Ramesh Kumar",     "role": "doctor"},
    "guardian": {"full_name": "Priya Sharma",          "role": "guardian"},
}


@router.post("/login", response_model=TokenResponse, summary="Login and get JWT tokens")
async def login(body: LoginRequest):
    """
    Authenticate with username and password.

    Returns:
        access_token:  Short-lived JWT (60 minutes).
        refresh_token: Long-lived JWT (7 days).

    Default credentials (development):
      - admin / admin123
      - doctor / doctor123
      - guardian / guardian123
    """
    user = authenticate_user(body.username, body.password)
    if not user:
        logger.warning("Failed login attempt for user '%s'", body.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_data = {"sub": user["username"], "role": user["role"]}
    access_token  = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info("User '%s' logged in (role=%s)", user["username"], user["role"])
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", summary="Logout (invalidate client token)")
async def logout(current_user: TokenData = Depends(get_current_user)):
    """
    Logout endpoint.

    Since JWTs are stateless, the client is responsible for discarding the token.
    This endpoint exists for API completeness and audit logging.
    """
    logger.info("User '%s' logged out", current_user.sub)
    return {"success": True, "message": "Logged out successfully."}


@router.get("/profile", response_model=UserProfileResponse, summary="Get current user profile")
async def get_profile(current_user: TokenData = Depends(get_current_user)):
    """Return the authenticated user's profile information."""
    meta = _USERS_META.get(current_user.sub, {})
    return UserProfileResponse(
        username=current_user.sub,
        role=current_user.role,
        full_name=meta.get("full_name", current_user.sub),
    )
