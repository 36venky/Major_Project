/**
 * auth.js – Authentication service for the ECG Guardian frontend.
 *
 * Handles JWT token storage, auto-login with default credentials,
 * and token retrieval for API/WebSocket calls.
 *
 * Default credentials (development): guardian / guardian123
 */

const BASE_URL  = 'http://localhost:8000';
const TOKEN_KEY = 'ecg_access_token';

// In-flight login promise – prevents multiple simultaneous login calls
let _loginPromise = null;

/**
 * Login and store the access token.
 * Returns the token string on success, null on failure.
 */
export async function login(username = 'guardian', password = 'guardian123') {
  try {
    const res = await fetch(`${BASE_URL}/auth/login`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ username, password }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    if (data.access_token) {
      sessionStorage.setItem(TOKEN_KEY, data.access_token);
      _loginPromise = null;
      return data.access_token;
    }
    return null;
  } catch {
    _loginPromise = null;
    return null;
  }
}

/**
 * Return the stored token, or auto-login to obtain one.
 * Deduplicates concurrent calls — only one login request at a time.
 * Returns null if the backend is unreachable.
 */
export async function getToken() {
  const stored = sessionStorage.getItem(TOKEN_KEY);
  if (stored) return stored;

  // Deduplicate: return the same promise if login is already in-flight
  if (!_loginPromise) {
    _loginPromise = login();
  }
  return _loginPromise;
}

/**
 * Clear the stored token (logout).
 */
export function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
  _loginPromise = null;
}

/**
 * Synchronous: return headers if token already cached, else empty object.
 * Use getAuthHeaders() (async) for reliable requests.
 */
export function authHeaders() {
  const token = sessionStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Async: always returns valid auth headers, waiting for login if needed.
 * Use this in fetch calls inside components.
 */
export async function getAuthHeaders() {
  const token = await getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
