# ECG Guardian — Backend

AI-based real-time ECG monitoring system built with **FastAPI**, **SQLAlchemy (async)**, **SQLite / PostgreSQL**, **XGBoost**, and **Twilio WhatsApp**.

Reads raw ECG signals from an **ESP32 + AD8232** hardware sensor over WiFi WebSocket, processes them in real-time, detects arrhythmias, predicts cardiac risk via an ML model, and pushes live data to the React frontend.

---

## Architecture

```
ESP32 (AD8232, 192 Hz)
    │  WiFi WebSocket  /ws/device
    ▼
WiFiManager  ──sample callback──▶  ECGService
                                       │
                 ┌─────────────────────┼──────────────────────┐
                 ▼                     ▼                       ▼
         DB flush loop          Analysis loop            WS broadcast loop
         (every 1 s)            (every 2 s)              (~25 fps, 40 ms)
                 │                     │                       │
          ECGSample rows        BPM + Arrhythmia        Frontend /ws/ecg
          HeartRate rows        XGBoost M2 risk
          RiskPrediction        Alert engine
                                       │
                              Twilio WhatsApp
                              (5-min cooldown)
```

---

## Features

| # | Feature | Endpoint(s) |
|---|---------|-------------|
| 1 | **JWT Auth** — register, login, refresh, profile | `POST /auth/register` `POST /auth/login` `POST /auth/refresh` `GET /auth/profile` |
| 2 | **Patient CRUD** — full demographics, location | `GET/POST /patients` `GET/PUT/DELETE /patients/{id}` |
| 3 | **Live ECG stream** — WiFi WebSocket, 192 Hz | `WS /ws/ecg` `WS /ws/device` |
| 4 | **Signal processing** — bandpass + notch filter, R-peak detection, BPM | `GET /ecg/live` `GET /bpm/live` |
| 5 | **Arrhythmia detection** — rule-based (Pan-Tompkins + HRV) | included in WS broadcast |
| 6 | **XGBoost ML risk** — 5-class AAMI beat classification, SDNN/RMSSD, 0-100 score | `GET /patients/{id}/risk` |
| 7 | **Alert engine** — 10 alert types, 60 s engine cooldown | `GET /alerts` `POST /alerts/{id}/resolve` |
| 8 | **WhatsApp alerts** — Twilio, 5-min cooldown, 3 retry attempts, admin management | `GET/DELETE /alerts/cooldowns` |
| 9 | **Patient location** — save/update/clear GPS coords + Google Maps link | `GET/PUT/DELETE /patients/{id}/location` |
| 10 | **Weekly health records** — BP, blood sugar, weight (upsert) | `GET/POST /weekly-health` |
| 11 | **PDF reports** — per-session and merged multi-session, BPM chart, health chart | `GET /reports/pdf/{session_id}` `GET /reports/pdf/all` |
| 12 | **ECG history** — list sessions, session detail | `GET /ecg/history` `GET /ecg/session/{id}` |
| 13 | **Start / Stop recording** — explicit user-triggered DB session | `POST /ecg/start` `POST /ecg/stop` |
| 14 | **Scheduler** — sample cleanup (6 h), daily summary, SQLite backup (24 h), BP reminder | background tasks |
| 15 | **Health check** | `GET /health` |

---

## Cooldown System

Two independent cooldown layers prevent alert flooding:

```
Analysis loop (every 2 s)
  └─► AlertEngine._should_fire()          60 s engine-level cooldown
          │  passes
          └─► DB alert row written (always)
              └─► TwilioWhatsAppService.dispatch()
                      └─► _last_sent[(patient_id, alert_type)] check   300 s WhatsApp cooldown
                              │  passes → stamp cooldown → send
                              └─► Exponential back-off: 2 s → 4 s → 8 s retries
```

- **Engine cooldown** resets when a new monitoring session starts.
- **Twilio cooldown** survives session restarts (lives on the singleton).
- Admin can inspect / reset cooldowns via `GET /alerts/cooldowns` and `DELETE /alerts/cooldowns`.

---

## Alert Types

| Type | Severity | Trigger |
|------|----------|---------|
| `HIGH_HR` | warning | BPM ≥ 100 |
| `CRITICAL_HR` | critical | BPM ≥ 150 |
| `LOW_HR` | warning | BPM ≤ 60 |
| `CRITICAL_LOW_HR` | critical | BPM ≤ 40 |
| `IRREGULAR_RHYTHM` | warning | RR CV > 0.30 (possible AFib) |
| `POOR_SIGNAL` | warning | Signal quality < 30% |
| `LEAD_OFF` | critical | Flatline detected |
| `DEVICE_DISCONNECT` | critical | ESP32 WiFi disconnected |
| `VENTRICULAR_BEAT` | critical | XGBoost majority label = V |
| `HIGH_RISK_SCORE` | warning/critical | XGBoost risk score ≥ 45/100 |

---

## Project Structure

```
backend/
├── main.py                     # FastAPI app factory + lifespan + routers
├── run.py                      # Development server launcher (Windows asyncio fix)
├── config.yaml                 # All runtime-configurable values
├── requirements.txt            # Pinned Python dependencies
│
├── app/
│   ├── api/                    # HTTP + WebSocket route handlers
│   │   ├── auth.py             # JWT auth endpoints
│   │   ├── patients.py         # Patient CRUD
│   │   ├── ecg.py              # ECG start/stop/history/live
│   │   ├── heart_rate.py       # BPM live + history
│   │   ├── alerts.py           # Alerts + WhatsApp cooldown management
│   │   ├── weekly_health.py    # BP / blood sugar / weight records
│   │   ├── reports.py          # PDF generation (single + merged)
│   │   ├── risk.py             # Risk prediction history
│   │   ├── location.py         # Patient GPS location
│   │   ├── patient_route.py    # /patient (active) + /device status
│   │   └── websocket.py        # WS /ws/ecg (frontend stream)
│   │
│   ├── alerts/
│   │   ├── alert_engine.py     # Rule-based alert evaluator + cooldown
│   │   └── notification.py     # In-process notification dispatcher
│   │
│   ├── core/
│   │   ├── config.py           # Settings (YAML + .env)
│   │   ├── exceptions.py       # Typed exception hierarchy
│   │   ├── logger.py           # Rotating file loggers per subsystem
│   │   └── security.py         # JWT encode/decode, password hash, RBAC deps
│   │
│   ├── database/
│   │   ├── database.py         # Async engine + session factory + migrations
│   │   ├── models.py           # SQLAlchemy ORM models (11 tables)
│   │   ├── schemas.py          # Pydantic v2 request/response schemas
│   │   └── crud.py             # All DB access (no business logic)
│   │
│   ├── processing/
│   │   ├── signal_filter.py    # Butterworth bandpass + 50 Hz notch
│   │   ├── r_peak_detection.py # Pan-Tompkins R-peak detector
│   │   ├── heart_rate.py       # BPM calculation + rolling estimator
│   │   ├── signal_quality.py   # SNR proxy + flatline + clipping detection
│   │   └── arrhythmia.py       # Rule-based rhythm classifier
│   │
│   ├── scheduler/
│   │   ├── weekly_reminder.py  # APScheduler job registration
│   │   └── cleanup.py          # Scheduled job implementations
│   │
│   ├── serial/
│   │   └── wifi_manager.py     # ESP32 WiFi WebSocket device manager
│   │
│   └── services/
│       ├── ecg_service.py      # Core ECG pipeline singleton
│       ├── prediction_service.py # XGBoost M2 risk prediction
│       ├── patient_service.py  # Patient business logic
│       ├── report_service.py   # ReportLab PDF generation
│       └── twilio_service.py   # WhatsApp alert dispatch + cooldown
│
└── tests/
    ├── conftest.py             # In-memory SQLite fixtures + test users
    ├── test_api.py             # REST API integration tests (15 tests)
    ├── test_cooldown.py        # Alert cooldown tests (30 tests)
    ├── test_database.py        # CRUD unit tests (7 tests)
    ├── test_serial_mock.py     # WiFi device manager tests (12 tests)
    └── test_signal_processing.py # Signal processing unit tests (27 tests)
```

---

## Database Schema

| Table | Purpose |
|-------|---------|
| `users` | App accounts (admin / doctor / guardian) |
| `patients` | Demographics, contacts, medical info, location |
| `ecg_sessions` | Monitoring session metadata + BPM aggregates |
| `ecg_samples` | Raw ADC samples (retained 48 h, then auto-purged) |
| `heart_rate` | Time-series BPM readings |
| `alerts` | Clinical alerts from the alert engine |
| `alert_logs` | WhatsApp dispatch log (sent / failed per recipient) |
| `weekly_health` | BP, blood sugar, weight entries |
| `doctor_notes` | Clinical notes |
| `risk_predictions` | XGBoost prediction history |

---

## Getting Started

### Prerequisites
- Python 3.11+
- ESP32 with AD8232 ECG shield running `ESP32/ESP32.ino`

### Install

```bash
cd backend
pip install -r requirements.txt
```

### Configure

Copy `.env.example` to `.env` and fill in:

```env
# Required — change before deploying
JWT_SECRET=your-secret-here

# Optional — SQLite is used by default
DATABASE_TYPE=postgresql
DATABASE_URL=postgresql+asyncpg://...

# Optional — WhatsApp alerts
TWILIO_ACCOUNT_SID=ACxxxx
TWILIO_AUTH_TOKEN=xxxx
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_COOLDOWN_SECONDS=300
```

### Run

```bash
# Development (Windows — fixes asyncio DNS for asyncpg)
python run.py

# Production
uvicorn main:app --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

### Default credentials (seeded on first run)
| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin123` | admin |

**Change the admin password immediately in production.**

---

## Running Tests

```bash
cd backend
python -m pytest tests/ -v
```

| Test file | Tests | Coverage |
|-----------|-------|---------|
| `test_api.py` | 15 | Auth, patient CRUD, weekly health, alerts, health check |
| `test_cooldown.py` | 30 | Engine cooldown, Twilio cooldown, management endpoints |
| `test_database.py` | 7 | Patient, session, alert, weekly health CRUD |
| `test_serial_mock.py` | 12 | ADC validation, WiFiManager lifecycle |
| `test_signal_processing.py` | 27 | Filter, R-peak, BPM, quality, arrhythmia |
| **Total** | **91** | **100% passing** |

---

## Signal Processing Pipeline

```
Raw ADC (0–4095, 192 Hz)
  └─► Butterworth bandpass  0.5–40 Hz   (removes baseline wander + HF noise)
        └─► 50 Hz IIR notch              (removes power-line interference)
              └─► Pan-Tompkins R-peak detection
                    └─► BPM from RR intervals
                          └─► HRV: SDNN, RMSSD
                                └─► Arrhythmia classification (rule-based)
                                      └─► XGBoost beat classification (ML)
```

## XGBoost ML Pipeline (M2)

- **Input:** 190-sample beat window (90 before + 100 after R-peak), z-score normalised
- **Model:** XGBoost trained on MIT-BIH Arrhythmia Database
- **Classes (AAMI):** N (Normal), S (Supraventricular), V (Ventricular), F (Fusion), Q (Unknown)
- **Output:** majority beat class, confidence %, SDNN/RMSSD, abnormal beat %, risk score 0–100
- **Cadence:** every 2 seconds on the live ECG buffer
- **Model file:** `../M2/saved_models/ecg_xgboost.json`

> ⚠️ The 0–100 risk score is a **prototype/educational metric** — not a clinically validated diagnostic.

---

## WebSocket Protocol

Connect: `ws://localhost:8000/ws/ecg?token=<access_token>`

### Live ECG frame (hardware connected)
```json
{
  "timestamp": "2026-10-08T12:00:00Z",
  "ecg": 2048.0,
  "bpm": 74,
  "quality": "Good",
  "quality_pct": 88,
  "status": "Normal Sinus Rhythm",
  "session_id": "S-ABC12345",
  "is_recording": true,
  "analysis": {
    "rhythm": "Normal Sinus Rhythm",
    "confidence": 97,
    "riskLevel": "Low",
    "xgbBpm": 73.5,
    "xgbRiskScore": 12,
    "xgbRiskLabel": "Low",
    "xgbBeatClass": "N",
    "sdnn": 42.1,
    "rmssd": 38.7,
    "riskPrediction": { ... }
  }
}
```

### No hardware frame
```json
{ "type": "no_data", "connected": false, "message": "No hardware connected..." }
```

### WhatsApp status frame
```json
{ "type": "whatsapp_status", "status": "sent", "phone": "+917...", "alert_type": "HIGH_HR" }
```

---

## User Roles

| Role | Permissions |
|------|------------|
| `admin` | Full access including delete patient, reset cooldowns |
| `doctor` | Read/write patient data, generate reports |
| `guardian` | Read patient data, update weekly health |

---

## Logs

Logs are written to `backend/logs/`:

| File | Contents |
|------|---------|
| `backend.log` | General application events |
| `api.log` | HTTP request/response |
| `alerts.log` | Alert engine fires, cooldown suppression |
| `serial.log` | ESP32 connection events, sample counts |
| `database.log` | DB operations |

All logs rotate at 10 MB, keeping 5 backups.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | `change-me` | **Change in production** |
| `JWT_ALGORITHM` | `HS256` | Token signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `DATABASE_TYPE` | `sqlite` | `sqlite` or `postgresql` |
| `DATABASE_URL` | — | PostgreSQL connection URL (asyncpg) |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `TWILIO_ACCOUNT_SID` | — | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | — | Twilio auth token |
| `TWILIO_WHATSAPP_FROM` | — | `whatsapp:+14155238886` |
| `WHATSAPP_COOLDOWN_SECONDS` | `300` | 5-minute WhatsApp cooldown |

---

*ECG Guardian — Educational Prototype. Not for clinical use without physician supervision.*
