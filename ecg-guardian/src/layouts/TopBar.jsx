/**
 * TopBar – Top navigation bar.
 * Shows patient name, connection status, live clock, notifications, and user profile.
 */
import { useState, useEffect } from 'react';
import { Bell, User, Wifi, WifiOff } from 'lucide-react';
import { useApp } from '../context/AppContext';
import { formatTime } from '../utils/helpers';

export default function TopBar() {
  const { state, dispatch } = useApp();
  const [now, setNow] = useState(new Date());
  const [notifOpen, setNotifOpen] = useState(false);

  // Live clock
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const unread = state.notifications.length;

  return (
    <header className="h-16 bg-white border-b border-slate-200 flex items-center px-6 gap-4 shrink-0">
      {/* Patient name */}
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center text-blue-700 text-xs font-bold">
          {state.patient.name.charAt(0)}
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-800 leading-none">{state.patient.name}</p>
          <p className="text-[10px] text-slate-400">ID: {state.patient.id}</p>
        </div>
      </div>

      <div className="flex-1" />

      {/* Connection status */}
      <div className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full
        ${state.device.connected
          ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
          : 'bg-red-50 text-red-600 border border-red-200'
        }`}>
        {state.device.connected
          ? <Wifi className="w-3 h-3" />
          : <WifiOff className="w-3 h-3" />
        }
        {state.device.connected ? 'Connected' : 'Disconnected'}
      </div>

      {/* Clock */}
      <div className="text-right hidden sm:block">
        <p className="text-sm font-semibold text-slate-700">
          {now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true })}
        </p>
        <p className="text-[10px] text-slate-400">
          {now.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}
        </p>
      </div>

      {/* Notifications */}
      <div className="relative">
        <button
          onClick={() => setNotifOpen(p => !p)}
          className="relative w-9 h-9 rounded-lg flex items-center justify-center text-slate-500 hover:bg-slate-100 transition-colors"
        >
          <Bell className="w-4 h-4" />
          {unread > 0 && (
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full" />
          )}
        </button>

        {notifOpen && (
          <div className="absolute right-0 top-11 w-80 bg-white rounded-xl shadow-xl border border-slate-200 z-50 animate-slide-in">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
              <p className="text-sm font-semibold text-slate-700">Notifications</p>
              <button
                onClick={() => dispatch({ type: 'CLEAR_NOTIFICATION' })}
                className="text-xs text-blue-600 hover:underline"
              >
                Clear all
              </button>
            </div>
            {state.notifications.length === 0 ? (
              <p className="text-sm text-slate-400 text-center py-6">No new notifications</p>
            ) : (
              <ul className="divide-y divide-slate-100 max-h-72 overflow-y-auto">
                {state.notifications.map(n => (
                  <li key={n.id} className="px-4 py-3">
                    <p className="text-xs font-semibold text-slate-700">{n.title}</p>
                    <p className="text-xs text-slate-500 mt-0.5">{n.description}</p>
                    <p className="text-[10px] text-slate-400 mt-1">{formatTime(n.time)}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* User profile */}
      <button className="w-9 h-9 rounded-lg bg-slate-100 flex items-center justify-center text-slate-600 hover:bg-slate-200 transition-colors">
        <User className="w-4 h-4" />
      </button>
    </header>
  );
}
