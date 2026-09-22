/**
 * api.js – REST API service layer.
 * All communication with FastAPI backend goes through this file.
 *
 * Uses getAuthHeaders() from auth.js (no automatic 401 refresh here —
 * use apiClient.js for endpoints that need silent token refresh).
 */

import { getAuthHeaders } from './auth';

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

async function request(method, path, body) {
  const authHdrs = await getAuthHeaders();
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json', ...authHdrs },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);

  const res = await fetch(`${BASE_URL}${path}`, opts);

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const errBody = await res.json();
      if (typeof errBody.detail === 'string') {
        detail = errBody.detail;
      } else if (Array.isArray(errBody.detail)) {
        detail = errBody.detail
          .map(e => `${e.loc?.slice(1).join(' → ') ?? 'field'}: ${e.msg}`)
          .join('; ');
      } else if (errBody.message) {
        detail = errBody.message;
      }
    } catch { /* keep generic HTTP status string */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }

  if (res.status === 204) return null;
  return res.json();
}

/* ── Patient ────────────────────────────────────────────── */
export const listPatients  = ()         => request('GET', '/patients');
export const getPatient    = (id)       => request('GET', `/patients/${id}`);
export const updatePatient = (id, data) => request('PUT', `/patients/${id}`, data);

/* ── Patient Location ───────────────────────────────────── */
export const getLocation   = (id)       => request('GET',    `/patients/${id}/location`);
export const saveLocation  = (id, data) => request('PUT',    `/patients/${id}/location`, data);
export const clearLocation = (id)       => request('DELETE', `/patients/${id}/location`);

/* ── Alerts ─────────────────────────────────────────────── */
export const getAlerts          = (patientId) => request('GET',  `/alerts?patient_id=${encodeURIComponent(patientId)}`);
export const sendWhatsAppReport = (patientId) => request('POST', '/alerts/send-report', { patient_id: patientId });

/* ── Weekly Health ──────────────────────────────────────── */
// patient_id is required — the backend endpoint now requires it as a query param
export const getWeeklyHealth  = (patientId) => request('GET',  `/weekly-health?patient_id=${encodeURIComponent(patientId)}`);
export const postWeeklyHealth = (data)      => request('POST', '/weekly-health', data);

/* ── ECG History (correct path: /ecg/history, requires patient_id) ── */
export const getEcgHistory = (patientId, limit = 20) =>
  request('GET', `/ecg/history?patient_id=${encodeURIComponent(patientId)}&limit=${limit}`);

/* ── Reports ────────────────────────────────────────────── */
export const getReportSessions = (patientId, limit = 20) => getEcgHistory(patientId, limit);

/* ── Device status (correct path: /device) ─────────────── */
export const getDevice = () => request('GET', '/device');

/* ── Mock History Sessions (fallback when backend is down) ─ */
export const MOCK_HISTORY = [
  {
    id: 'S001',
    date: '2026-07-16',
    startTime: '09:00 AM',
    endTime: '09:45 AM',
    duration: '45 min',
    avgBPM: 74,
    maxBPM: 102,
    minBPM: 62,
    events: ['Normal Sinus Rhythm', 'Brief Tachycardia Episode'],
    status: 'Completed',
  },
  {
    id: 'S002',
    date: '2026-07-15',
    startTime: '08:30 AM',
    endTime: '09:15 AM',
    duration: '45 min',
    avgBPM: 71,
    maxBPM: 89,
    minBPM: 65,
    events: ['Normal Sinus Rhythm'],
    status: 'Completed',
  },
  {
    id: 'S003',
    date: '2026-07-14',
    startTime: '07:00 PM',
    endTime: '07:30 PM',
    duration: '30 min',
    avgBPM: 79,
    maxBPM: 115,
    minBPM: 68,
    events: ['Possible Arrhythmia Detected', 'Signal Lost (2 min)', 'Signal Restored'],
    status: 'Completed',
  },
  {
    id: 'S004',
    date: '2026-07-13',
    startTime: '10:00 AM',
    endTime: '10:20 AM',
    duration: '20 min',
    avgBPM: 68,
    maxBPM: 78,
    minBPM: 60,
    events: ['Normal Sinus Rhythm'],
    status: 'Completed',
  },
];
