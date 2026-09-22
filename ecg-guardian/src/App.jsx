/**
 * App.jsx – Root component with React Router routes.
 *
 * Public  : /login, /register, /verify-email
 * Protected: everything else → RequireAuth → MainLayout
 *
 * Auth guard checks both token existence AND expiry so that an expired
 * token stored in localStorage correctly redirects to /login instead of
 * showing the dashboard and hitting 401s everywhere.
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppProvider } from './context/AppContext';
import MainLayout  from './layouts/MainLayout';
import Login       from './pages/Login';
import Register    from './pages/Register';
import VerifyEmail from './pages/VerifyEmail';
import Dashboard   from './pages/Dashboard';
import Patients    from './pages/Patients';
import History     from './pages/History';
import Reports     from './pages/Reports';
import Alerts      from './pages/Alerts';
import Settings    from './pages/Settings';
import { getToken, clearToken } from './services/auth';

// One-time cleanup: remove legacy patient persistence key if it exists.
// Patient is now always fetched fresh from the backend after login.
localStorage.removeItem('ecg_active_patient');

/**
 * Return true if a JWT string is present AND not yet expired.
 * Decodes the payload manually (no library needed — we only read the exp claim).
 * A token without an exp claim is treated as valid (never expires).
 */
function isTokenValid() {
  const token = getToken();
  if (!token) return false;
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    if (!payload.exp) return true;
    // exp is seconds since epoch; add a 10-second buffer for clock skew
    const expired = Date.now() / 1000 > payload.exp - 10;
    if (expired) {
      clearToken(); // wipe the stale token so the user sees login cleanly
    }
    return !expired;
  } catch {
    return false; // malformed token — treat as invalid
  }
}

function RequireAuth({ children }) {
  return isTokenValid() ? children : <Navigate to="/login" replace />;
}

function RedirectIfAuth({ children }) {
  return isTokenValid() ? <Navigate to="/" replace /> : children;
}

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Routes>

          {/* ── Public routes ──────────────────────────────── */}
          <Route path="/login"        element={<RedirectIfAuth><Login /></RedirectIfAuth>} />
          <Route path="/register"     element={<RedirectIfAuth><Register /></RedirectIfAuth>} />
          <Route path="/verify-email" element={<VerifyEmail />} />

          {/* ── Protected routes ───────────────────────────── */}
          <Route element={<RequireAuth><MainLayout /></RequireAuth>}>
            <Route path="/"          element={<Dashboard />} />
            <Route path="/patients"  element={<Patients />} />
            <Route path="/history"   element={<History />} />
            <Route path="/reports"   element={<Reports />} />
            <Route path="/alerts"    element={<Alerts />} />
            <Route path="/settings"  element={<Settings />} />
          </Route>

          {/* ── Fallback ────────────────────────────────────── */}
          <Route path="*" element={<Navigate to="/" replace />} />

        </Routes>
      </BrowserRouter>
    </AppProvider>
  );
}
