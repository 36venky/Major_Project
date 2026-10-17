/**
 * useWebSocket – Connects to FastAPI /ws/ecg with JWT auth.
 *
 * Simulation has been fully removed.  When the backend is unreachable or
 * no ESP32 hardware is connected, the hook dispatches a NO_DATA action so
 * the dashboard can show "Hardware not connected" instead of stale charts.
 *
 * Token expiry handling
 * ─────────────────────
 * When the backend rejects a connection with {"error": "..."} (expired/invalid
 * token), the hook:
 *   1. Stops reconnecting immediately.
 *   2. Tries to refresh the access token via POST /auth/refresh.
 *   3. On success — reconnects with the new token.
 *   4. On failure — clears tokens and redirects to /login.
 */
import { useEffect, useRef, useCallback } from 'react';
import { useApp } from '../context/AppContext';
import { getToken, getRefreshToken, clearToken } from '../services/auth';
import { BASE_URL } from '../services/apiClient';

/**
 * Derive the WebSocket base URL from the HTTP base URL.
 *   https://...  →  wss://...
 *   http://...   →  ws://...
 * This means only VITE_API_URL needs updating when the backend tunnel changes.
 */
function toWsBase(httpUrl) {
  return httpUrl.replace(/^https:\/\//, 'wss://').replace(/^http:\/\//, 'ws://');
}

const WS_BASE_URL     = `${toWsBase(BASE_URL)}/ws/ecg`;
const API_BASE_URL    = BASE_URL;
const RECONNECT_DELAY = 5000;

/* ── Token helpers ──────────────────────────────────────── */

function isAccessTokenValid() {
  const token = getToken();
  if (!token) return false;
  try {
    const { exp } = JSON.parse(atob(token.split('.')[1]));
    if (!exp) return true;
    return Date.now() / 1000 < exp - 10;
  } catch {
    return false;
  }
}

async function silentRefresh() {
  const rt = getRefreshToken();
  if (!rt) return null;
  try {
    const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method:  'POST',
      headers: {
        'Content-Type': 'application/json',
        'ngrok-skip-browser-warning': 'true',
      },
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

  const reconnectRef = useRef(null);
  const stoppedRef   = useRef(false);

  /* ── Helpers ────────────────────────────────────────── */
  const dispatchNoData = useCallback(() => {
    dispatch({
      type: 'SET_NO_DATA',
      payload: { message: 'Hardware not connected — awaiting ESP32' },
    });
  }, [dispatch]);

  /* ── WebSocket ──────────────────────────────────────── */
  const connect = useCallback(async () => {
    if (stoppedRef.current) return;

    let token = getToken();

    if (!token) {
      // Not logged in — show no data, no WS needed
      dispatchNoData();
      return;
    }

    if (!isAccessTokenValid()) {
      const newToken = await silentRefresh();
      if (!newToken) {
        redirectToLogin();
        return;
      }
      token = newToken;
    }

    try {
      const ws = new WebSocket(
        `${WS_BASE_URL}?token=${encodeURIComponent(token)}&ngrok-skip-browser-warning=true`
      );
      wsRef.current = ws;

      ws.onopen = async () => {
        if (stoppedRef.current) return;
        dispatch({ type: 'UPDATE_DEVICE', payload: { connected: true, status: 'Connected' } });
        addTimelineEvent({ event: 'Backend Connected', icon: 'wifi', color: 'green' });

        // Check whether real ESP32 hardware is connected
        try {
          const res = await fetch(`${API_BASE_URL}/health`, {
            headers: { 'ngrok-skip-browser-warning': 'true' },
          });
          if (res.ok) {
            const h = await res.json();
            const hw = h.hardware_connected === true;
            dispatch({ type: 'UPDATE_DEVICE', payload: { hardwareConnected: hw } });
            // Restore recording state in case the page was refreshed mid-session
            if (h.is_recording !== undefined) {
              dispatch({ type: 'SET_RECORDING', payload: h.is_recording });
            }
            if (!hw) {
              // Backend is up but no hardware yet — show no-data state
              dispatchNoData();
              addTimelineEvent({
                event: 'Awaiting ESP32 Hardware',
                icon:  'alert',
                color: 'amber',
              });
            }
          }
        } catch { /* non-fatal */ }
      };

      ws.onmessage = async (e) => {
        if (stoppedRef.current) return;
        try {
          const data = JSON.parse(e.data);

          // ── Auth error frame ─────────────────────────────
          if (data.error) {
            const isAuthError = /token|expired|auth/i.test(data.error);
            if (isAuthError) {
              ws.onclose = null;
              ws.close();
              dispatch({ type: 'UPDATE_DEVICE', payload: { connected: false, status: 'Reconnecting…' } });

              const newToken = await silentRefresh();
              if (!newToken) { redirectToLogin(); return; }
              if (!stoppedRef.current) {
                clearTimeout(reconnectRef.current);
                reconnectRef.current = setTimeout(connect, 500);
              }
            }
            return;
          }

          // ── No data frame (no ESP32 connected) ───────────
          if (data.type === 'no_data') {
            dispatch({ type: 'UPDATE_DEVICE', payload: { hardwareConnected: false } });
            dispatchNoData();
            return;
          }

          // ── WhatsApp status notification ─────────────────
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

          // ── ECG sample — value is raw ADC (0–4095) from ESP32
          //    Centre on rolling mean then normalise to [-1, 1] for chart display.
          //    This works regardless of the hardware DC bias / ADC_BASELINE.
          if (data.ecg !== undefined) {
            // Hardware is sending — clear any no-data state
            dispatch({ type: 'UPDATE_DEVICE', payload: { hardwareConnected: true } });
            // Sync recording state from every frame (backend is source of truth)
            if (data.is_recording !== undefined) {
              dispatch({ type: 'SET_RECORDING', payload: data.is_recording });
            }
            // Normalise: centre on 2048 (12-bit midpoint), scale by half-range 2048
            const normalised = (data.ecg - 2048) / 2048;
            dispatch({
              type: 'APPEND_ECG',
              payload: [{ time: Date.now(), value: normalised }],
            });
          }

          // ── Heart rate ───────────────────────────────────
          if (data.bpm !== undefined) {
            dispatch({ type: 'SET_HEART_RATE', payload: data.bpm });
          }

          // ── AI analysis ──────────────────────────────────
          if (data.analysis) {
            const a = data.analysis;

            // Build recentEvents from XGBoost beat class changes and risk flags
            const events = [];
            if (a.xgbBeatClass && a.xgbBeatClass !== 'N') {
              events.push({ type: 'beat', label: `${a.xgbBeatType ?? a.xgbBeatClass} detected`, time: data.timestamp });
            }
            if (a.xgbRiskLabel && (a.xgbRiskLabel === 'High' || a.xgbRiskLabel === 'Critical')) {
              events.push({ type: 'risk', label: `Risk ${a.xgbRiskLabel}: score ${a.xgbRiskScore}/100`, time: data.timestamp });
            }
            if (a.riskLevel && (a.riskLevel === 'High' || a.riskLevel === 'Critical')) {
              events.push({ type: 'arrhythmia', label: `${a.rhythm ?? 'Abnormal rhythm'} (${a.riskLevel})`, time: data.timestamp });
            }

            // Merge all fields (arrhythmia + XGBoost) into aiAnalysis state
            dispatch({
              type: 'SET_AI_ANALYSIS',
              payload: {
                // Arrhythmia / rule-based (existing)
                rhythm:         a.rhythm,
                confidence:     a.confidence,
                riskLevel:      a.riskLevel,
                signalQuality:  a.signalQuality,
                heartRateTrend: a.heartRateTrend,
                // Append new events (keep last 10)
                ...(events.length > 0 ? { recentEvents: events } : {}),
                // XGBoost M2 pipeline fields (new)
                xgbBpm:         a.xgbBpm,
                xgbConfidence:  a.xgbConfidence,
                xgbRiskScore:   a.xgbRiskScore,
                xgbRiskLabel:   a.xgbRiskLabel,
                xgbBeatClass:   a.xgbBeatClass,
                xgbBeatType:    a.xgbBeatType,
                sdnn:           a.sdnn,
                rmssd:          a.rmssd,
                abnormalPct:    a.abnormalPct,
              },
            });

            // Update RiskCard via SET_RISK_PREDICTION
            if (a.riskPrediction) {
              dispatch({
                type:    'SET_RISK_PREDICTION',
                payload: { ...a.riskPrediction, timestamp: data.timestamp },
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
        dispatch({
          type:    'UPDATE_DEVICE',
          payload: { connected: false, hardwareConnected: false, status: 'Disconnected' },
        });
        dispatchNoData();
        addTimelineEvent({ event: 'Backend Disconnected', icon: 'alert', color: 'red' });
        // Reconnect after delay
        reconnectRef.current = setTimeout(connect, RECONNECT_DELAY);
      };

      ws.onerror = () => { ws.close(); };

    } catch {
      dispatchNoData();
      reconnectRef.current = setTimeout(connect, RECONNECT_DELAY);
    }
  }, [dispatch, wsRef, dispatchNoData, addTimelineEvent]);

  /* ── Lifecycle ──────────────────────────────────────── */
  useEffect(() => {
    stoppedRef.current = false;
    connect();
    return () => {
      stoppedRef.current = true;
      clearTimeout(reconnectRef.current);
      if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}
