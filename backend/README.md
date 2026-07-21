# ECG Guardian – Backend

AI-based real-time ECG monitoring backend built with **FastAPI**, **SQLAlchemy (async)**, and **SQLite**. It reads ECG signals from hardware over serial (or generates synthetic data when hardware is unavailable), processes the signal, calculates heart rate, detects arrhythmias, predicts cardiac risk, and pushes live data to a React frontend via WebSocket.

---

## Features

- **Live ECG streaming** – reads from a serial device (Arduino/ESP32 on COM6 @ 115200 baud) or falls back to a mock generator
- **Signal processing** – Butterworth band-pass filter (0.5–40 Hz), R-peak detection, SNR-based signal quality scoring
- **Heart rate & arrhythmia detection** – BPM calculation from RR intervals with clinical alert thresholds
- **Cardiac risk prediction** – ML-based risk scoring stored per patient
- **Alert engine** – generates warnings/critical alerts; dispatches WhatsApp notifications via Twilio
- **Patient management** – full CRUD with demographics, medications, allergies, emergency contacts
- **Weekly health tracking** – blood pressure, blood sugar, weight logs with scheduled reminders
- **PDF report generation** – per-patient session summaries via ReportLab
- **WebSocket broadcast** – ~25 fps live ECG + BPM stream to connected frontends
- **JWT authentication** – access + refresh token flow with bcrypt password hashing
- **APScheduler jobs** – data retention cleanup, daily summaries, weekly BP reminders

---

## Tech Stack

| Layer | Library |
|---|---|
| Web framework | FastAPI 0.115, Uvicorn |
| Database | SQLite + SQLAlchemy 2.0 (async via aiosqlite) |
| Validation | Pydantic v2, pydantic-settings |
| Signal processing | NumPy, SciPy |
| Auth | python-jose (JWT), passlib (bcrypt) |
| Notifications | Twilio (WhatsApp) |
| Scheduler | APScheduler 3.10 |
| PDF | ReportLab |
| Serial I/O | pyserial |
| Config | PyYAML + python-dotenv |
| Testing | pytest, pytest-asyncio, httpx |

---

## Project Structure

```
backend/
├── main.py                  # FastAPI app factory & lifespan
├── run.py                   # Dev server launcher
├── config.yaml              # All runtime configuration (no hardcoded values)
├── requirements.txt
├── .env                     # Secrets (not committed)
│
├── app/
│   ├── api/                 # Route handlers
│   │   ├── auth.py          # Login / token refresh
│   │   ├── patients.py      # Patient CRUD
│   │   ├── ecg.py           # ECG session control
│   │   ├── heart_rate.py    # Heart rate history
│   │   ├── alerts.py        # Alert management
│   │   ├── weekly_health.py # Weekly health metrics
│   │   ├── reports.py       # PDF report generation
│   │   ├── risk.py          # Cardiac risk predictions
│   │   ├── websocket.py     # WS live stream endpoint
│   │   └── patient_route.py # Dashboard aggregated data
│   │
│   ├── core/
│   │   ├── config.py        # Settings singleton (YAML + .env)
│   │   ├── security.py      # JWT helpers, password hashing
│   │   ├── exceptions.py    # Domain exception classes
│   │   └── logger.py        # Rotating file + console logger
│   │
│   ├── database/
│   │   ├── database.py      # Async engine, session factory
│   │   ├── models.py        # SQLAlchemy ORM models
│   │   ├── schemas.py       # Pydantic request/response schemas
│   │   └── crud.py          # Database operations
│   │
│   ├── processing/
│   │   ├── signal_filter.py     # Butterworth band-pass filter
│   │   ├── r_peak_detection.py  # Pan-Tompkins-inspired R-peak detector
│   │   ├── heart_rate.py        # BPM calculation from RR intervals
│   │   ├── signal_quality.py    # SNR-based quality scoring
│   │   └── arrhythmia.py        # Arrhythmia classification
│   │
│   ├── services/
│   │   ├── ecg_service.py        # Orchestrates serial → process → broadcast
│   │   ├── patient_service.py    # Patient business logic
│   │   ├── prediction_service.py # ML risk prediction
│   │   ├── report_service.py     # PDF generation
│   │   └── twilio_service.py     # WhatsApp alert dispatch
│   │
│   ├── alerts/
│   │   ├── alert_engine.py   # Threshold evaluation & alert creation
│   │   └── notification.py   # Notification dispatch coordinator
│   │
│   ├── serial/
│   │   ├── serial_reader.py  # Async serial port reader + mock generator
│   │   └── serial_manager.py # Connection lifecycle management
│   │
│   └── scheduler/
│       ├── cleanup.py          # Old ECG data retention job
│       └── weekly_reminder.py  # Scheduled health reminders
│
├── data/
│   └── ecg_guardian.db      # SQLite database (auto-created on first run)
│
├── logs/                    # Rotating log files (auto-created)
│   ├── backend.log
│   ├── api.log
│   ├── alerts.log
│   ├── serial.log
│   └── database.log
│
└── tests/
    └── conftest.py
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- (Optional) Arduino/ESP32 sending ECG data at 115200 baud over serial — the backend auto-falls back to a mock generator if hardware is absent

### 1. Clone & install dependencies

```bash
git clone <repo-url>
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure

Copy the example env file and fill in secrets:

```bash
copy .env.example .env   # Windows
cp .env.example .env     # Linux / macOS
```

Edit `.env` with real values (JWT secret, Twilio credentials). Hardware and processing settings live in `config.yaml`.

**Key `config.yaml` settings:**

```yaml
serial:
  port: "COM6"              # Change to your actual serial port
  mock_when_unavailable: true  # Keep true for dev without hardware

security:
  jwt_secret: "change-this-in-production"
```

### 3. Run

```bash
python run.py
```

Server starts at `http://localhost:8000`.

- Interactive API docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Health check: `http://localhost:8000/health`

A default demo patient (`P-001 – Arjun Sharma`) is seeded automatically on first run.

---

## API Overview

| Router | Prefix | Description |
|---|---|---|
| auth | `/api/auth` | Login, refresh token |
| patients | `/api/patients` | Patient CRUD |
| ecg | `/api/ecg` | Session start/stop, history |
| heart_rate | `/api/heart-rate` | BPM history per patient |
| alerts | `/api/alerts` | Alert list & resolution |
| weekly_health | `/api/weekly-health` | BP / sugar / weight logs |
| reports | `/api/reports` | PDF report download |
| risk | `/api/risk` | Cardiac risk predictions |
| websocket | `/ws` | Live ECG + BPM stream |
| dashboard | `/api/dashboard` | Aggregated patient summary |

Full interactive documentation is available at `/docs` once the server is running.

---

## Environment Variables

| Variable | Description |
|---|---|
| `JWT_SECRET` | Secret key for signing JWTs (override `config.yaml`) |
| `TWILIO_ACCOUNT_SID` | Twilio account SID for WhatsApp alerts |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_FROM_NUMBER` | Twilio WhatsApp sender number |
| `DATABASE_PATH` | Override SQLite file path |
| `SERIAL_PORT` | Override serial port (e.g. `/dev/ttyUSB0`) |
| `DEBUG` | Set `true` to enable hot-reload and SQL logging |

---

## Running Tests

```bash
pytest
```

---

## License

MIT
