"""
main.py
────────
FastAPI application entry point.

Responsibilities:
  - Configure the FastAPI app with metadata
  - Register all API routers
  - Define lifespan (startup/shutdown) handler
  - Register global exception handlers
  - Configure CORS for the React frontend
  - Start the ECGService and APScheduler
"""

from __future__ import annotations

import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import ECGGuardianError
from app.core.logger import get_logger
from app.database.database import close_db, init_db
from app.scheduler.weekly_reminder import setup_scheduler
from app.services.ecg_service import ecg_service

# API routers
from app.api.auth          import router as auth_router
from app.api.patients      import router as patients_router
from app.api.ecg           import router as ecg_router
from app.api.heart_rate    import router as hr_router
from app.api.alerts        import router as alerts_router
from app.api.weekly_health import router as health_router
from app.api.reports       import router as reports_router
from app.api.websocket     import router as ws_router
from app.api.patient_route import router as dashboard_router
from app.api.risk          import router as risk_router
from app.api.location      import router as location_router

logger = get_logger("app.main")


# ── Lifespan (startup / shutdown) ─────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Startup:
      1. Initialise database (create tables)
      2. Seed default patient if missing
      3. Start ECGService (serial + processing + WebSocket broadcast)
      4. Start APScheduler background jobs

    Shutdown:
      1. Stop ECGService (close session, serial port)
      2. Stop scheduler
      3. Close DB connections
    """
    # ── Startup ───────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(" ECG Guardian Backend  v%s  starting…", settings.APP_VERSION)
    logger.info("=" * 60)

    # 1. Database
    await init_db()

    # 2. Seed default admin user and demo patient
    await _seed_default_admin()
    await _seed_default_patient()

    # 3. ECG service
    await ecg_service.start()

    # 4. Set default patient on the ECG service (session opens when hardware connects)
    await _set_ecg_service_patient()

    # 5. Scheduler
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info("APScheduler started with %d jobs", len(scheduler.get_jobs()))

    logger.info("ECG Guardian is ready. Docs: http://%s:%d/docs", settings.HOST, settings.PORT)

    yield  # ← application runs here

    # ── Shutdown ──────────────────────────────────────────
    logger.info("ECG Guardian shutting down…")
    await ecg_service.stop()
    scheduler.shutdown(wait=False)
    await close_db()
    logger.info("Shutdown complete.")


async def _seed_default_admin() -> None:
    """
    Create a default admin account on first startup so the app is usable
    without needing to register first.

    Default credentials:
      username : admin
      password : admin123
      role     : admin

    These are printed as a warning so operators change them immediately.
    """
    from app.database.database import AsyncSessionLocal
    from app.database import crud
    from app.core.security import hash_password

    async with AsyncSessionLocal() as db:
        if not await crud.username_exists(db, "admin"):
            await crud.create_user(db, {
                "username":        "admin",
                "email":           "admin@ecgguardian.local",
                "hashed_password": hash_password("admin123"),
                "full_name":       "System Administrator",
                "role":            "admin",
                "is_active":       True,
            })
            await db.commit()
            logger.warning(
                "⚠  Default admin account created  (username=admin  password=admin123). "
                "Change this immediately in production!"
            )


async def _seed_default_patient() -> None:
    """Insert the default demo patient if the database is empty."""
    from app.database.database import AsyncSessionLocal
    from app.database import crud

    async with AsyncSessionLocal() as db:
        existing = await crud.get_patient(db, "P-001")
        if not existing:
            await crud.create_patient(db, {
                "patient_id":        "P-001",
                "name":              "Arjun Sharma",
                "age":               45,
                "dob":               "1980-04-15",
                "gender":            "Male",
                "blood_group":       "B+",
                "height":            "172 cm",
                "weight":            "74 kg",
                # Guardian
                "guardian_name":     "Priya Sharma",
                "guardian_phone":    "+91 98765 43210",
                "guardian_relation": "Wife",
                # Patient contact
                "phone":             "+91 98765 43210",
                "emergency_contact": "+91 98765 43210",
                # Doctor
                "doctor_name":       "Dr. Ramesh Iyer",
                "doctor_hospital":   "Apollo Hospital, Bangalore",
                "doctor_phone":      "+91 80 2345 6789",
                # Ambulance
                "ambulance_name":    "City Ambulance Services",
                "ambulance_phone":   "+91 98001 12345",
                # Medical
                "diseases":          "Hypertension; Type 2 Diabetes",
                "medications":       "Metoprolol 50 mg; Metformin 500 mg",
                "allergies":         "Penicillin",
                "notes":             "Patient has a history of mild arrhythmia. Regular ECG monitoring advised.",
                # Address
                "address":           "12, Koramangala 3rd Block, Bangalore, Karnataka 560034",
                "location":          "12.9352,77.6245",
                "location_address":  "12, Koramangala 3rd Block, Bangalore",
                "maps_link":         "https://maps.google.com/?q=12.9352,77.6245",
            })
            await db.commit()
            logger.info("Default patient P-001 seeded.")


async def _set_ecg_service_patient() -> None:
    """Tell ECGService which patient to monitor (first in DB, or P-001 fallback)."""
    from app.database.database import AsyncSessionLocal
    from app.database import crud

    async with AsyncSessionLocal() as db:
        patients = await crud.get_all_patients(db)
        if patients:
            ecg_service.set_patient_id(patients[0].patient_id)
            logger.info(
                "ECGService default patient set to %s — "
                "session will open when ESP32 connects",
                patients[0].patient_id,
            )


# ── Application factory ────────────────────────────────────

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.APP_TITLE,
        version=settings.APP_VERSION,
        description=settings.APP_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ── CORS ──────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",    # Vite dev server (local)
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://192.168.30.122:5173",  # Network access for other devices on same WiFi
        ],
        # Allow any *.ngrok-free.app subdomain so the frontend ngrok tunnel
        # is always permitted regardless of which URL it was assigned.
        # Update this regex if you switch to a different tunnelling service.
        allow_origin_regex=r"https://[a-zA-Z0-9-]+\.ngrok-free\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────
    app.include_router(auth_router)
    app.include_router(patients_router)
    app.include_router(ecg_router)
    app.include_router(hr_router)
    app.include_router(alerts_router)
    app.include_router(health_router)
    app.include_router(reports_router)
    app.include_router(ws_router)
    app.include_router(dashboard_router)
    app.include_router(risk_router)
    app.include_router(location_router)
    # ESP32 WiFi device endpoint (/ws/device) — owned by WiFiManager via ECGService
    app.include_router(ecg_service.device_router)

    # ── Global exception handlers ─────────────────────────

    @app.exception_handler(ECGGuardianError)
    async def ecg_exception_handler(request: Request, exc: ECGGuardianError):
        """Convert domain exceptions to structured JSON responses."""
        logger.error("Domain error [%d]: %s", exc.status_code, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "message": exc.detail, "data": None},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """Catch-all for unhandled exceptions."""
        logger.critical("Unhandled exception: %s\n%s", exc, traceback.format_exc())
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "message": "Internal server error.", "data": None},
        )

    # ── Health check ──────────────────────────────────────

    @app.get("/health", tags=["System"], summary="Health check")
    async def health_check():
        """Returns 200 OK when the server is running."""
        return {
            "status":             "ok",
            "version":            settings.APP_VERSION,
            "monitoring":         ecg_service.is_monitoring,
            "is_recording":       ecg_service.is_recording,
            "connected":          ecg_service.is_connected,
            # hardware_connected = True only when a real ESP32 is sending data
            "hardware_connected": ecg_service.is_connected,
        }

    return app


# ── Entry point ────────────────────────────────────────────
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
