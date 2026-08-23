/**
 * App.jsx – Root component with React Router routes.
 *
 * Public routes  : /login, /register
 * Protected routes: everything else, wrapped in RequireAuth → MainLayout
 *
 * Route guard:
 *   - Unauthenticated → /login
 *   - Already authenticated visiting /login or /register → /
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppProvider } from './context/AppContext';
import MainLayout from './layouts/MainLayout';
import Login    from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import Patients  from './pages/Patients';
import LiveECG   from './pages/LiveECG';
import History   from './pages/History';
import Reports   from './pages/Reports';
import Alerts    from './pages/Alerts';
import Settings  from './pages/Settings';
import { getToken } from './services/auth';

/** Redirect to /login when no valid token is present. */
function RequireAuth({ children }) {
  return getToken() ? children : <Navigate to="/login" replace />;
}

/** Redirect already-authenticated users away from public auth pages. */
function RedirectIfAuth({ children }) {
  return getToken() ? <Navigate to="/" replace /> : children;
}

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Routes>

          {/* ── Public routes ──────────────────────────────── */}
          <Route
            path="/login"
            element={<RedirectIfAuth><Login /></RedirectIfAuth>}
          />
          <Route
            path="/register"
            element={<RedirectIfAuth><Register /></RedirectIfAuth>}
          />

          {/* ── Protected routes ───────────────────────────── */}
          <Route
            element={
              <RequireAuth>
                <MainLayout />
              </RequireAuth>
            }
          >
            <Route path="/"         element={<Dashboard />} />
            <Route path="/patients" element={<Patients />} />
            <Route path="/live-ecg" element={<LiveECG />} />
            <Route path="/history"  element={<History />} />
            <Route path="/reports"  element={<Reports />} />
            <Route path="/alerts"   element={<Alerts />} />
            <Route path="/settings" element={<Settings />} />
          </Route>

          {/* ── Fallback ────────────────────────────────────── */}
          <Route path="*" element={<Navigate to="/" replace />} />

        </Routes>
      </BrowserRouter>
    </AppProvider>
  );
}
