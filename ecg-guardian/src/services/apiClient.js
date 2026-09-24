/**
 * apiClient.js – Authenticated fetch wrapper with automatic JWT refresh.
 *
 * On a 401 response the client silently:
 *   1. Calls POST /auth/refresh with the stored refresh token
 *   2. Retries the original request with the new access token
 *   3. If refresh fails → clears storage and redirects to /login
 */

import { getToken, getRefreshToken, clearToken } from './auth';

export const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

async function _refresh() {
  const rt = getRefreshToken();
  if (!rt) return null;
  try {
    const res  = await fetch(`${BASE_URL}/auth/refresh`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ refresh_token: rt }),
    });
    if (!res.ok) { clearToken(); return null; }
    const data = await res.json();
    localStorage.setItem('ecg_access_token',  data.access_token);
    localStorage.setItem('ecg_refresh_token', data.refresh_token);
    return data.access_token;
  } catch { return null; }
}

function _redirectToLogin() {
  clearToken();
  if (!window.location.pathname.startsWith('/login') &&
      !window.location.pathname.startsWith('/register')) {
    window.location.replace('/login');
  }
}

export async function apiRequest(method, path, body, options = {}) {
  const makeOpts = (token) => {
    const opts = {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...options,
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    return opts;
  };

  let token = getToken();
  let res   = await fetch(`${BASE_URL}${path}`, makeOpts(token));

  if (res.status === 401) {
    const newToken = await _refresh();
    if (!newToken) { _redirectToLogin(); throw new Error('Session expired. Please log in again.'); }
    res = await fetch(`${BASE_URL}${path}`, makeOpts(newToken));
    if (res.status === 401) { _redirectToLogin(); throw new Error('Session expired. Please log in again.'); }
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const err = await res.json();
      detail = err.detail || err.message || detail;
      if (Array.isArray(detail)) detail = detail.map(e => e.msg || JSON.stringify(e)).join(' • ');
    } catch { /* ignore */ }
    throw new Error(detail);
  }

  const ct = res.headers.get('Content-Type') || '';
  if (ct.includes('application/json'))                                      return res.json();
  if (ct.includes('application/pdf') || ct.includes('application/octet-stream')) return res.blob();
  return res.text();
}

export const apiGet    = (path, opts)       => apiRequest('GET',    path, undefined, opts);
export const apiPost   = (path, body, opts) => apiRequest('POST',   path, body,      opts);
export const apiPut    = (path, body, opts) => apiRequest('PUT',    path, body,      opts);
export const apiPatch  = (path, body, opts) => apiRequest('PATCH',  path, body,      opts);
export const apiDelete = (path, opts)       => apiRequest('DELETE', path, undefined, opts);
