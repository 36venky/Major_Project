/**
 * TopBar – Top navigation bar.
 * Hamburger button opens/closes the sidebar.
 * Shows patient info, connection status, live clock, notifications, profile + logout.
 */
import { useState, useEffect } from 'react';
import { Bell, User, Wifi, WifiOff, LogOut, Menu } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useApp }      from '../context/AppContext';
import { useSidebar }  from '../context/SidebarContext';
import { clearToken, getRefreshToken } from '../services/auth';
import { BASE_URL } from '../services/apiClient';
import { formatTime }  from '../utils/helpers';

export default function TopBar() {
  const { state, dispatch } = useApp();
  const { toggle }          = useSidebar();
  const navigate            = useNavigate();

  const [now,         setNow]         = useState(new Date());
  const [notifOpen,   setNotifOpen]   = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);

  // Live clock
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const unread = state.notifications.length;
  const user   = state.authUser;

  const handleLogout = async () => {
    try {
      const refreshToken = getRefreshToken();
      // Fire-and-forget server-side token blacklist
      fetch(`${BASE_URL}/auth/logout`, {
        method:  'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('ecg_access_token') || ''}`,
        },
        body: JSON.stringify(refreshToken ? { refresh_token: refreshToken } : {}),
      }).catch(() => {});
    } catch { /* non-fatal */ }
    clearToken();
    dispatch({ type: 'LOGOUT' });
    navigate('/login', { replace: true });
  };

  return (
    <header className="h-16 bg-white border-b border-slate-200 flex items-center px-4 gap-3 shrink-0">

      {/* ── Sidebar toggle (hamburger) ─────────────────── */}
      <button
        onClick={toggle}
        title="Toggle sidebar"
        className="w-9 h-9 rounded-lg flex items-center justify-center
                   text-slate-500 hover:bg-slate-100 transition-colors shrink-0"
      >
        <Menu className="w-4 h-4" />
      </button>

      {/* ── Patient info ──────────────────────────────── */}
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center
                        text-blue-700 text-xs font-bold shrink-0">
          {state.patient?.name?.charAt(0) ?? '?'}
        </div>
        <div className="hidden sm:block">
          <p className="text-sm font-semibold text-slate-800 leading-none">
            {state.patient?.name ?? 'No patient'}
          </p>
          <p className="text-[10px] text-slate-400">
            {state.patient?.id ? `ID: ${state.patient.id}` : 'Register a patient to begin'}
          </p>
        </div>
      </div>

      <div className="flex-1" />

      {/* ── Connection status ─────────────────────────── */}
      <div className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full
        ${state.device.connected
          ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
          : 'bg-red-50 text-red-600 border border-red-200'
        }`}
      >
        {state.device.connected
          ? <Wifi    className="w-3 h-3" />
          : <WifiOff className="w-3 h-3" />
        }
        <span className="hidden sm:inline">
          {state.device.connected ? 'Connected' : 'Disconnected'}
        </span>
      </div>

      {/* ── Clock ────────────────────────────────────── */}
      <div className="text-right hidden md:block">
        <p className="text-sm font-semibold text-slate-700">
          {now.toLocaleTimeString('en-IN', {
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true,
          })}
        </p>
        <p className="text-[10px] text-slate-400">
          {now.toLocaleDateString('en-IN', {
            weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
          })}
        </p>
      </div>

      {/* ── Notifications ────────────────────────────── */}
      <div className="relative">
        <button
          onClick={() => { setNotifOpen(p => !p); setProfileOpen(false); }}
          className="relative w-9 h-9 rounded-lg flex items-center justify-center
                     text-slate-500 hover:bg-slate-100 transition-colors"
        >
          <Bell className="w-4 h-4" />
          {unread > 0 && (
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full" />
          )}
        </button>

        {notifOpen && (
          <div className="absolute right-0 top-11 w-80 bg-white rounded-xl shadow-xl
                          border border-slate-200 z-50">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
              <p className="text-sm font-semibold text-slate-700">Notifications</p>
              <button
                onClick={() => dispatch({ type: 'CLEAR_NOTIFICATION' })}
                className="text-xs text-blue-600 hover:underline"
              >
                Clear all
              </button>
            </div>
            {state.notifications.length === 0
              ? <p className="text-sm text-slate-400 text-center py-6">No new notifications</p>
              : (
                <ul className="divide-y divide-slate-100 max-h-72 overflow-y-auto">
                  {state.notifications.map(n => (
                    <li key={n.id} className="px-4 py-3">
                      <p className="text-xs font-semibold text-slate-700">{n.title}</p>
                      <p className="text-xs text-slate-500 mt-0.5">{n.description}</p>
                      <p className="text-[10px] text-slate-400 mt-1">{formatTime(n.time)}</p>
                    </li>
                  ))}
                </ul>
              )
            }
          </div>
        )}
      </div>

      {/* ── User profile + logout ─────────────────────── */}
      <div className="relative">
        <button
          onClick={() => { setProfileOpen(p => !p); setNotifOpen(false); }}
          className="w-9 h-9 rounded-lg bg-slate-100 flex items-center justify-center
                     text-slate-600 hover:bg-slate-200 transition-colors"
        >
          <User className="w-4 h-4" />
        </button>

        {profileOpen && (
          <div className="absolute right-0 top-11 w-52 bg-white rounded-xl shadow-xl
                          border border-slate-200 z-50 py-2">
            {user && (
              <div className="px-4 py-2 border-b border-slate-100">
                <p className="text-sm font-semibold text-slate-700 truncate">{user.full_name}</p>
                <p className="text-xs text-slate-400 truncate">{user.email || user.username}</p>
                <p className="text-xs text-blue-500 capitalize mt-0.5">{user.role}</p>
              </div>
            )}
            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-red-600
                         hover:bg-red-50 transition-colors"
            >
              <LogOut className="w-4 h-4" />
              Sign Out
            </button>
          </div>
        )}
      </div>

    </header>
  );
}
