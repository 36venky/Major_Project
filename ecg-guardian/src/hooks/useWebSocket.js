/**
 * useWebSocket – Connects to FastAPI /ws/ecg with JWT auth.
 * Falls back to a client-side simulator when the backend is unreachable.
 *
 * Token expiry handling
 * ─────────────────────
 * When the backend rejects a connection with {"error": "..."} (expired or
 * invalid token), the hook:
 *   1. Stops reconnecting immediately (no infinite retry loop).
 *   2. Tries to refresh the access token via POST /auth/refresh.
 *   3. On success — reconnects with the new token.
 *   4. On failure — clears all tokens and redirects to /login.
 */
import { useEffect, useRef, useCallback } from 'react';
import { useApp } from '../context/AppContext';
import { getToken, getRefreshToken, clearToken } from '../services/auth';

const WS_BASE_URL     = `${import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000'}/ws/ecg`;
const API_BASE_URL    = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
const RECONNECT_DELAY = 5000;

/* ── Client-side ECG simulator (fallback) ───────────────── */
function generateECGPoint(t) {
  const period = 0.8;
  const cycle  = (t % period) / period;
  let v = 0;
  v += 0.015 * Math.sin(2 * Math.PI * 0.15 * t);
  if (cycle > 0.08 && cycle < 0.22) { const p = (cycle - 0.08) / 0.14; v += 0.08 * Math.sin(Math.PI * p); }
  if (cycle > 0.28 && cycle < 0.33) { const q = (cycle - 0.28) / 0.05; v -= 0.12 * Math.sin(Math.PI * q); }
  if (cycle > 0.33 && cycle < 0.42) { const r = (cycle - 0.33) / 0.09; v += 1.0  * Math.sin(Math.PI * r); }
  if (cycle > 0.42 && cycle < 0.47) { const s = (cycle - 0.42) / 0.05; v -= 0.18 * Math.sin(Math.PI * s); }
  if (cycle > 0.52 && cycle < 0.72) { const tw= (cycle - 0.52) / 0.20; v += 0.22 * Math.sin(Math.PI * tw); }
  v += (Math.random() + Math.random() + Math.random() - 1.5) * 0.012;
  return parseFloat(v.toFixed(4));
}

/* ── Token helpers ──────────────────────────────────────── */

/** True if the stored access token exists and has not expired yet. */
function isAccessTokenValid() {
  const token = getToken();
  if (!token) return false;
  try {
    const { exp } = JSON.parse(atob(token.split('.')[1]));
    if (!exp) return true;
    return Date.now() / 1000 < exp - 10; // 10-second buffer
  } catch {
    return false;
  }
}

/**
 * Attempt a silent token refresh.
 * Returns the new access token on success, null on failure.
 */
async function silentRefresh() {
  const rt = getRefreshToken();
  if (!rt) return null;
  try {
    const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ refresh_token: rt }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data.access_token) return null;
    localStorage.setItem('ecg_access_token',  data.access_token);
    localStorage.setItem('ecg_refresh_token', data.refresh_token);
    return data.access_token;
  } catch {
    return null;
  }
}

function redirectToLogin() {
  clearToken();
  if (!window.location.pathname.startsWith('/login')) {
    window.location.replace('/login');
  }
}

/* ── Hook ───────────────────────────────────────────────── */
export function useWebSocket() {
  const { dispatch, wsRef, addTimelineEvent } = useApp();

  const simRef       = useRef(null);
  const tRef         = useRef(0);
  const bpmTimerRef  = useRef(0);
  const reconnectRef = useRef(null);
  const stoppedRef   = useRef(false);

  /* ── Simulator ──────────────────────────────────────── */
  const startSimulator = useCallback(() => {
    if (simRef.current) return;
    const INTERVAL = 40;
    const STEP     = INTERVAL / 1000;
    simRef.current = setInterval(() => {
      const batch = [];
      for (let i = 0; i < 5; i++) {
        tRef.current += STEP / 5;
        batch.push({ time: Date.now() + i, value: generateECGPoint(tRef.current) });
      }
      dispatch({ type: 'APPEND_ECG', payload: batch });
      bpmTimerRef.current++;
      if (bpmTimerRef.current % 25 === 0) {
        const bpm = Math.round(75 + 6 * Math.sin(tRef.current * 0.04));
        dispatch({ type: 'SET_HEART_RATE', payload: bpm });
      }
    }, INTERVAL);
  }, [dispatch]);

  const stopSimulator = useCallback(() => {
    if (simRef.current) { clearInterval(simRef.current); simRef.current = null; }
  }, []);

  /* ── WebSocket ──────────────────────────────────────── */
  const connect = useCallback(async () => {
    if (stoppedRef.current) return;

    // ── Token check before connecting ────────────────────
    // If the stored access token is already expired, try to refresh it silently
    // before opening the WebSocket.  This avoids the infinite reject loop.
    let token = getToken();

    if (!token) {
      // Not logged in — run simulator, no WS needed
      startSimulator();
      return;
    }

    if (!isAccessTokenValid()) {
      // Token expired — try silent refresh first
      const newToken = await silentRefresh();
      if (!newToken) {
        // Refresh token also expired or absent → must log in again
        redirectToLogin();
        return;
      }
      token = newToken;
    }

    try {
      const ws = new WebSocket(`${WS_BASE_URL}?token=${encodeURIComponent(token)}`);
      wsRef.current = ws;

      ws.onopen = async () => {
        if (stoppedRef.current) return;
        stopSimulator();
        dispatch({ type: 'UPDATE_DEVICE', payload: { connected: true, status: 'Active' } });
        addTimelineEvent({ event: 'Backend Connected', icon: 'wifi', color: 'green' });

        // Query /health once to learn whether a real ESP32 is connected
        // (is_connected is true in both mock and hardware modes; hardware_connected is not)
        try {
          const res = await fetch(`${API_BASE_URL}/health`);
          if (res.ok) {
            const h = await res.json();
            dispatch({
              type: 'UPDATE_DEVICE',
              payload: { hardwareConnected: h.hardware_connected === true },
            });
          }
        } catch { /* non-fatal — assume no hardware */ }
      };

      ws.onmessage = async (e) => {
        if (stoppedRef.current) return;
        try {
          const data = JSON.parse(e.data);

          // ── Auth error frame from backend ────────────────
          // Backend sends {"error": "Invalid or expired token."} then closes.
          // We should NOT reconnect with the same token — try refresh first.
          if (data.error) {
            const isAuthError = /token|expired|auth/i.test(data.error);
            if (isAuthError) {
              ws.onclose = null; // prevent double-handling in onclose
              ws.close();
              stopSimulator();
              dispatch({ type: 'UPDATE_DEVICE', payload: { connected: false, status: 'Reconnecting…' } });

              const newToken = await silentRefresh();
              if (!newToken) {
                redirectToLogin();
                return;
              }
              // Successfully refreshed — reconnect immediately
              if (!stoppedRef.current) {
                clearTimeout(reconnectRef.current);
                reconnectRef.current = setTimeout(connect, 500);
              }
            }
            return;
          }

          // ── WhatsApp send-status notification ────────────
          if (data.type === 'whatsapp_status') {
            const ok = data.status === 'sent';
            dispatch({
              type: 'ADD_NOTIFICATION',
              payload: {
                id:          `ws-${Date.now()}-${Math.random()}`,
                title:       data.title,
                description: data.description,
                severity:    ok ? 'success' : 'error',
                time:        data.timestamp || new Date().toISOString(),
                phone:       data.phone,
                alert_type:  data.alert_type,
              },
            });
            return;
          }

          // ── ECG sample — normalise ADC 0–4095 → [-1, 1] ─
          if (data.ecg !== undefined) {
            dispatch({
              type: 'APPEND_ECG',
              payload: [{ time: Date.now(), value: (data.ecg - 2048) / 2048 }],
            });
          }

          // ── Heart rate ───────────────────────────────────
          if (data.bpm !== undefined && data.bpm > 0) {
            dispatch({ type: 'SET_HEART_RATE', payload: data.bpm });
          }

          // ── AI analysis ──────────────────────────────────
          if (data.analysis) {
            dispatch({ type: 'SET_AI_ANALYSIS', payload: data.analysis });
            if (data.analysis.riskPrediction) {
              dispatch({
                type: 'SET_RISK_PREDICTION',
                payload: { ...data.analysis.riskPrediction, timestamp: data.timestamp },
              });
            }
          }

          // ── Signal quality ───────────────────────────────
          if (data.quality_pct !== undefined) {
            dispatch({ type: 'UPDATE_DEVICE', payload: { signalQuality: data.quality_pct } });
          }

        } catch { /* ignore malformed frames */ }
      };

      ws.onclose = () => {
        if (stoppedRef.current) return;
        dispatch({ type: 'UPDATE_DEVICE', payload: { connected: false, hardwareConnected: false, status: 'Disconnected' } });
        startSimulator();
        // Normal network close — schedule a reconnect (token will be re-validated then)
        reconnectRef.current = setTimeout(connect, RECONNECT_DELAY);
      };

      ws.onerror = () => { ws.close(); };

    } catch {
      startSimulator();
      reconnectRef.current = setTimeout(connect, RECONNECT_DELAY);
    }
  }, [dispatch, wsRef, stopSimulator, startSimulator, addTimelineEvent]);

  /* ── Lifecycle ──────────────────────────────────────── */
  useEffect(() => {
    stoppedRef.current = false;
    connect();
    return () => {
      stoppedRef.current = true;
      stopSimulator();
      clearTimeout(reconnectRef.current);
      if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return { startSimulator, stopSimulator };
}
