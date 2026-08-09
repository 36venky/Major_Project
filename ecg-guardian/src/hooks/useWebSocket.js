/**
 * useWebSocket – Connects to FastAPI /ws/ecg, handles ECG + risk prediction data.
 * Falls back to a client-side simulator when the backend is unreachable.
 */
import { useEffect, useRef, useCallback } from 'react';
import { useApp } from '../context/AppContext';
import { getToken } from '../services/auth';

const WS_BASE_URL     = 'ws://localhost:8000/ws/ecg';
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
  if (cycle > 0.52 && cycle < 0.72) { const tw= (cycle - 0.52) / 0.20; v += 0.22 * Math.sin(Math.PI * tw);}
  v += (Math.random() + Math.random() + Math.random() - 1.5) * 0.012;
  return parseFloat(v.toFixed(4));
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

    let token = null;
    try { token = await getToken(); } catch { /* fall through */ }

    if (!token) {
      startSimulator();
      return;
    }

    try {
      const ws = new WebSocket(`${WS_BASE_URL}?token=${encodeURIComponent(token)}`);
      wsRef.current = ws;

      ws.onopen = () => {
        stopSimulator();
        dispatch({ type: 'UPDATE_DEVICE', payload: { connected: true, status: 'Active' } });
        addTimelineEvent({ event: 'Backend Connected', icon: 'wifi', color: 'green' });
      };

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.error) return; // auth/protocol error frame

          // ── WhatsApp send-status notification ───────────
          // Backend pushes one of these after each Twilio attempt.
          if (data.type === 'whatsapp_status') {
            const ok  = data.status === 'sent';
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
            return; // nothing else to process in this frame
          }

          // ECG sample — normalise ADC 0–4095 → [-1, 1]
          if (data.ecg !== undefined) {
            const normalised = (data.ecg - 2048) / 2048;
            dispatch({
              type: 'APPEND_ECG',
              payload: [{ time: Date.now(), value: normalised }],
            });
          }

          // Heart rate
          if (data.bpm !== undefined && data.bpm > 0) {
            dispatch({ type: 'SET_HEART_RATE', payload: data.bpm });
          }

          // AI analysis (rhythm, confidence, riskLevel, etc.)
          // Only update if backend has actual analysis (arrhythmia != null)
          if (data.analysis) {
            dispatch({ type: 'SET_AI_ANALYSIS', payload: data.analysis });

            // Live risk prediction embedded in analysis (Feature 5)
            if (data.analysis.riskPrediction) {
              dispatch({
                type: 'SET_RISK_PREDICTION',
                payload: {
                  ...data.analysis.riskPrediction,
                  timestamp: data.timestamp,
                },
              });
            }
          }
          // If analysis is null, leave existing state intact (don't flash stale defaults)

          // Signal quality
          if (data.quality_pct !== undefined) {
            dispatch({ type: 'UPDATE_DEVICE', payload: { signalQuality: data.quality_pct } });
          }
        } catch { /* ignore malformed frames */ }
      };

      ws.onclose = () => {
        if (stoppedRef.current) return;
        dispatch({ type: 'UPDATE_DEVICE', payload: { connected: false, status: 'Disconnected' } });
        startSimulator();
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
  }, []);

  return { startSimulator, stopSimulator };
}
