/**
 * auth.js – Authentication service for ECG Guardian.
 *
 * Stores JWT token and user info in sessionStorage.
 * Exposes:
 *   registerUser(data)                           – POST /auth/register, returns { user } or throws
 *   loginWithCredentials(username, password)     – POST /auth/login, returns { token, user } or throws
 *   getToken()                                   – cached token or null
 *   getUserInfo()                                – cached user object or null
 *   clearToken()                                 – logout (clears sessionStorage)
 *   getAuthHeaders()                             – { Authorization: 'Bearer ...' } or {}
 */

const BASE_URL  = 'http://localhost:8000';
const TOKEN_KEY = 'ecg_access_token';
const USER_KEY  = 'ecg_user_info';

// ── Registration ──────────────────────────────────────────

/**
 * Register a new user account.
 * On success: returns { user } (does NOT auto-login — user must sign in after).
 * On failure: throws an Error with a human-readable message.
 *
 * @param {Object} data – matches RegisterRequest schema
 */
export async function registerUser(data) {
  const res = await fetch(`${BASE_URL}/auth/register`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(data),
  });

  const body = await res.json().catch(() => ({}));

  if (!res.ok) {
    // FastAPI validation errors come as { detail: [...] } or { detail: "string" }
    const detail = body.detail;
    if (Array.isArray(detail)) {
      const msgs = detail.map(e => e.msg || JSON.stringify(e)).join(' • ');
      throw new Error(msgs);
    }
    throw new Error(detail || `Registration failed (HTTP ${res.status}).`);
  }

  return { user: body };
}

// ── Login ─────────────────────────────────────────────────

/**
 * Login with credentials (username or email + password).
 * On success: stores token + user info in sessionStorage and returns them.
 * On failure: throws an Error with a human-readable message.
 */
export async function loginWithCredentials(username, password) {
  const res = await fetch(`${BASE_URL}/auth/login`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ username, password }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    if (res.status === 401) throw new Error('Incorrect username/email or password.');
    if (res.status === 403) throw new Error(detail || 'Account deactivated.');
    throw new Error(detail || `Login failed (HTTP ${res.status}). Check if the backend is running.`);
  }

  const data = await res.json();
  if (!data.access_token) throw new Error('Server returned an invalid response.');

  sessionStorage.setItem(TOKEN_KEY, data.access_token);

  // Fetch full profile to populate user info
  let userInfo = { username, role: 'guardian', full_name: username };
  try {
    const profileRes = await fetch(`${BASE_URL}/auth/profile`, {
      headers: { Authorization: `Bearer ${data.access_token}` },
    });
    if (profileRes.ok) {
      const profile = await profileRes.json();
      userInfo = {
        username:       profile.username,
        role:           profile.role,
        full_name:      profile.full_name,
        email:          profile.email       ?? null,
        phone:          profile.phone       ?? null,
        specialization: profile.specialization ?? null,
        hospital:       profile.hospital    ?? null,
        city:           profile.city        ?? null,
        country:        profile.country     ?? null,
      };
    }
  } catch { /* profile fetch failure is non-fatal */ }

  sessionStorage.setItem(USER_KEY, JSON.stringify(userInfo));
  return { token: data.access_token, user: userInfo };
}

// ── Token helpers ─────────────────────────────────────────

/** Return the cached JWT token, or null if not logged in. */
export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) ?? null;
}

/** Return cached user info object, or null. */
export function getUserInfo() {
  const raw = sessionStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

/** Clear token and user info (logout). */
export function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}

/** Synchronous: return auth headers if token is cached, else {}. */
export function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Async: return auth headers.
 * Does NOT auto-login — returns {} if the user is not logged in.
 */
export async function getAuthHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
