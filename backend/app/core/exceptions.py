"""
core/exceptions.py
──────────────────
Centralised custom exception hierarchy.

All business-logic errors raise these typed exceptions.
The global exception handler in main.py converts them to consistent JSON responses.
"""

from __future__ import annotations


class ECGGuardianError(Exception):
    """Base exception for all application errors."""
    status_code: int = 500
    detail: str = "An unexpected error occurred."

    def __init__(self, detail: str | None = None):
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


# ── Resource errors ───────────────────────────────────────

class NotFoundError(ECGGuardianError):
    """Requested resource does not exist."""
    status_code = 404
    detail = "Resource not found."


class AlreadyExistsError(ECGGuardianError):
    """Resource already exists (duplicate)."""
    status_code = 409
    detail = "Resource already exists."


# ── Validation errors ─────────────────────────────────────

class ValidationError(ECGGuardianError):
    """Input failed domain-level validation."""
    status_code = 422
    detail = "Validation failed."


# ── Auth errors ───────────────────────────────────────────

class AuthenticationError(ECGGuardianError):
    """Invalid credentials."""
    status_code = 401
    detail = "Authentication failed."


class AuthorizationError(ECGGuardianError):
    """Insufficient permissions."""
    status_code = 403
    detail = "Access denied."


# ── Serial / hardware errors ──────────────────────────────

class SerialConnectionError(ECGGuardianError):
    """Serial port could not be opened or was lost."""
    status_code = 503
    detail = "Serial device unavailable."


class SerialReadError(ECGGuardianError):
    """Error reading data from serial port."""
    status_code = 503
    detail = "Serial read failure."


# ── Signal processing errors ──────────────────────────────

class SignalProcessingError(ECGGuardianError):
    """Error in signal processing pipeline."""
    status_code = 500
    detail = "Signal processing failure."


# ── Database errors ───────────────────────────────────────

class DatabaseError(ECGGuardianError):
    """Database operation failed."""
    status_code = 500
    detail = "Database operation failed."


# ── Session errors ────────────────────────────────────────

class SessionError(ECGGuardianError):
    """ECG session management error."""
    status_code = 400
    detail = "Session error."
