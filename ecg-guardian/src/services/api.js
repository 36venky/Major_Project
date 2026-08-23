/**
 * api.js – REST API service layer.
 * All communication with FastAPI backend goes through this file.
 */

import { getAuthHeaders } from './auth';

const BASE_URL = 'http://localhost:8000';

async function request(method, path, body) {
  const authHdrs = await getAuthHeaders();
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json', ...authHdrs },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE_URL}${path}`, opts);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/* ── Patient ────────────────────────────────────────────── */
export const getPatient    = (id)       => request('GET', `/patients/${id}`);
export const updatePatient = (id, data) => request('PUT', `/patients/${id}`, data);

/* ── Patient Location ───────────────────────────────────── */
export const getLocation   = (id)       => request('GET',    `/patients/${id}/location`);
export const saveLocation  = (id, data) => request('PUT',    `/patients/${id}/location`, data);
export const clearLocation = (id)       => request('DELETE', `/patients/${id}/location`);

/* ── Alerts ─────────────────────────────────────────────── */
export const getAlerts          = (patientId) => request('GET',  `/alerts?patient_id=${patientId}`);
export const sendWhatsAppReport = (patientId) => request('POST', '/alerts/send-report', { patient_id: patientId });

/* ── Weekly Health ──────────────────────────────────────── */
export const getWeeklyHealth  = ()     => request('GET',  '/weekly-health');
export const postWeeklyHealth = (data) => request('POST', '/weekly-health', data);

/* ── Reports ────────────────────────────────────────────── */
export const getReports = () => request('GET', '/reports');

/* ── History ────────────────────────────────────────────── */
export const getHistory = () => request('GET', '/history');

/* ── Device ─────────────────────────────────────────────── */
export const getDevice = () => request('GET', '/device');

/* ── Mock History Sessions (used when backend is down) ─── */
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
