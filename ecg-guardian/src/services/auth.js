/**
 * auth.js – Authentication service for ECG Guardian.
 *
 * Tokens stored in localStorage (persist across browser restarts).
 * Keys:
 *   ecg_access_token   – short-lived JWT
 *   ecg_refresh_token  – long-lived JWT
 *   ecg_user_info      – serialised user profile
 */

const BASE_URL    = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
const ACCESS_KEY  = 'ecg_access_token';
const REFRESH_KEY = 'ecg_refresh_token';
const USER_KEY    = 'ecg_user_info';

// ── Registration ──────────────────────────────────────────

export async function registerUser(data) {
  const res  = await fetch(`${BASE_URL}/auth/register`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(data),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body.detail;
    if (Array.isArray(detail)) throw new Error(detail.map(e => e.msg || JSON.stringify(e)).join(' • '));
    throw new Error(detail || `Registration failed (HTTP ${res.status}).`);
  }
  return { user: body };
}

// ── Login ─────────────────────────────────────────────────

export async function loginWithCredentials(email, password) {
  const res = await fetch(`${BASE_URL}/auth/login`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ username: email, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) throw new Error('Invalid email or password.');
    if (res.status === 403) throw new Error(body.detail || 'Account deactivated.');
    throw new Error(body.detail || `Login failed (HTTP ${res.status}).`);
  }
  const data = await res.json();
  if (!data.access_token) throw new Error('Server returned an invalid response.');

  localStorage.setItem(ACCESS_KEY,  data.access_token);
  localStorage.setItem(REFRESH_KEY, data.refresh_token);

  // Fetch full user profile
  let userInfo = { username: email, role: 'guardian', full_name: email };
  try {
    const pr = await fetch(`${BASE_URL}/auth/profile`, {
      headers: { Authorization: `Bearer ${data.access_token}` },
    });
    if (pr.ok) {
      const p = await pr.json();
      userInfo = {
        username:       p.username,
        role:           p.role,
        full_name:      p.full_name,
        email:          p.email          ?? null,
        phone:          p.phone          ?? null,
        specialization: p.specialization ?? null,
        hospital:       p.hospital       ?? null,
        city:           p.city           ?? null,
        country:        p.country        ?? null,
      };
    }
  } catch { /* non-fatal */ }

  localStorage.setItem(USER_KEY, JSON.stringify(userInfo));
  return { token: data.access_token, user: userInfo };
}

// ── Token helpers ─────────────────────────────────────────

export function getToken()        { return localStorage.getItem(ACCESS_KEY)  ?? null; }
export function getRefreshToken() { return localStorage.getItem(REFRESH_KEY) ?? null; }

export function getUserInfo() {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

export function clearToken() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem('ecg_active_patient');  // remove any legacy patient persistence
}

export function authHeaders() {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function getAuthHeaders() {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}
