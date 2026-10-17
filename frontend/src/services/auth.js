/**
 * auth.js – Authentication service for ECG Guardian.
 *
 * Tokens stored in localStorage (persist across browser restarts).
 * Keys:
 *   ecg_access_token   – short-lived JWT
 *   ecg_refresh_token  – long-lived JWT
 *   ecg_user_info      – serialised user profile
 *
 * BASE_URL is imported from apiClient.js — the single source of truth.
 * Update VITE_API_URL in .env when the backend ngrok tunnel changes.
 */

import { BASE_URL } from './apiClient';
const ACCESS_KEY  = 'ecg_access_token';
const REFRESH_KEY = 'ecg_refresh_token';
const USER_KEY    = 'ecg_user_info';

// ── Registration ──────────────────────────────────────────

export async function registerUser(data) {
  const url = `${BASE_URL}/auth/register`;
  console.log('Calling registration API:', url);
  console.log('Request payload:', JSON.stringify(data, null, 2));
  
  try {
    const res = await fetch(url, {
      method:  'POST',
      headers: {
        'Content-Type': 'application/json',
        'ngrok-skip-browser-warning': 'true',
      },
      body:    JSON.stringify(data),
    });
    
    console.log('Registration response status:', res.status, res.statusText);
    
    const body = await res.json().catch(() => ({}));
    console.log('Registration response body:', body);
    
    if (!res.ok) {
      const detail = body.detail;
      if (Array.isArray(detail)) {
        // Pydantic validation errors
        const errors = detail.map(e => {
          if (e.loc && e.msg) {
            const field = e.loc.join('.');
            return `${field}: ${e.msg}`;
          }
          return e.msg || JSON.stringify(e);
        }).join(' • ');
        throw new Error(errors);
      }
      throw new Error(detail || `Registration failed (HTTP ${res.status}).`);
    }
    return { user: body };
  } catch (err) {
    console.error('Registration API error:', err);
    // If it's a network error (fetch failed), provide more helpful message
    if (err.message === 'Failed to fetch' || err.name === 'TypeError') {
      throw new Error(`Cannot connect to server. Please ensure the backend is running and VITE_API_URL (${BASE_URL}) is correct.`);
    }
    throw err;
  }
}

// ── Login ─────────────────────────────────────────────────

export async function loginWithCredentials(email, password) {
  const res = await fetch(`${BASE_URL}/auth/login`, {
    method:  'POST',
    headers: {
      'Content-Type': 'application/json',
      'ngrok-skip-browser-warning': 'true',
    },
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
      headers: {
        'Authorization': `Bearer ${data.access_token}`,
        'ngrok-skip-browser-warning': 'true',
      },
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
