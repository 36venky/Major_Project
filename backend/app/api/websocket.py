"""
api/websocket.py
─────────────────
WebSocket endpoint for real-time ECG streaming.

WS /ws/ecg
──────────
Clients connect once and receive continuous JSON frames:
{
  "timestamp":   "2026-07-17T12:10:31.123456+00:00",
  "ecg":         531.42,
  "bpm":         74,
  "quality":     "Good",
  "quality_pct": 88,
  "status":      "Normal Sinus Rhythm",
  "session_id":  "S-ABC123",
  "analysis": {
    "rhythm":        "Normal Sinus Rhythm",
    "confidence":    97,
    "riskLevel":     "Low",
    "signalQuality": "Good",
    "heartRateTrend":"Stable"
  }
}

Authentication:
  Pass JWT as query param ?token=<access_token>
  (WebSocket clients cannot set Authorization headers).
"""

from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.logger import get_logger
from app.core.security import decode_token
from app.services.ecg_service import ecg_service

router = APIRouter(tags=["WebSocket"])
logger = get_logger("api.websocket")


@router.websocket("/ws/ecg")
async def ecg_websocket(
    websocket: WebSocket,
    token: str = Query(default=None, description="JWT access token"),
):
    """
    Real-time ECG streaming WebSocket endpoint.

    Authenticates via ?token=<jwt> query parameter.
    Broadcasts ECG samples at ~25 fps (configurable via WS_BROADCAST_INTERVAL).

    Returns WS 1008 (Policy Violation) if the token is missing or invalid.
    """
    # ── Token guard ───────────────────────────────────────
    if not token:
        await websocket.accept()
        await websocket.send_json({
            "error": "Authentication required. Connect with ?token=<access_token>",
            "hint": "POST /auth/login to obtain a token."
        })
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket rejected — no token provided")
        return

    # ── Validate token ────────────────────────────────────
    try:
        user = decode_token(token)
    except Exception:
        await websocket.accept()
        await websocket.send_json({"error": "Invalid or expired token."})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket rejected — invalid token")
        return

    await ecg_service.connect_ws(websocket)
    logger.info("WebSocket authenticated as '%s'", user.sub)

    try:
        # Keep connection alive; actual data is pushed by ECGService broadcast loop
        while True:
            # Accept any client messages (ping-pong / control frames)
            data = await websocket.receive_text()
            # Could handle client commands here (e.g. {"cmd": "pause"})
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected normally")
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
    finally:
        await ecg_service.disconnect_ws(websocket)
