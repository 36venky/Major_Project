/**
 * Sidebar – Left navigation panel.
 * Highlights the active route and shows monitoring status badge.
 */
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, Users, Activity, History,
  FileText, BellRing, Settings, Heart,
} from 'lucide-react';
import { useApp } from '../context/AppContext';

const NAV_ITEMS = [
  { to: '/',         label: 'Dashboard',  icon: LayoutDashboard },
  { to: '/patients', label: 'Patients',   icon: Users },
  { to: '/live-ecg', label: 'Live ECG',   icon: Activity },
  { to: '/history',  label: 'History',    icon: History },
  { to: '/reports',  label: 'Reports',    icon: FileText },
  { to: '/alerts',   label: 'Alerts',     icon: BellRing },
  { to: '/settings', label: 'Settings',   icon: Settings },
];

export default function Sidebar() {
  const { state } = useApp();
  const activeAlerts = state.alerts.filter(a => a.status === 'active').length;

  return (
    <aside className="w-60 min-h-screen bg-white border-r border-slate-200 flex flex-col shrink-0">
      {/* Brand */}
      <div className="h-16 flex items-center gap-3 px-5 border-b border-slate-200">
        <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
          <Heart className="w-4 h-4 text-white" fill="currentColor" />
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-800 leading-none">ECG Guardian</p>
          <p className="text-[10px] text-slate-400 mt-0.5">AI Monitoring System</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors relative
              ${isActive
                ? 'bg-blue-50 text-blue-700'
                : 'text-slate-600 hover:bg-slate-50 hover:text-slate-800'
              }`
            }
          >
            <Icon className="w-4 h-4 shrink-0" />
            {label}
            {/* Alerts badge */}
            {label === 'Alerts' && activeAlerts > 0 && (
              <span className="ml-auto text-[10px] font-semibold bg-red-500 text-white rounded-full w-4 h-4 flex items-center justify-center">
                {activeAlerts > 9 ? '9+' : activeAlerts}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Monitoring status footer */}
      <div className="p-4 border-t border-slate-200">
        <div className={`flex items-center gap-2 text-xs font-medium rounded-lg px-3 py-2
          ${state.device.connected ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
          <span className={`relative flex w-2 h-2`}>
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75
              ${state.device.connected ? 'bg-emerald-400' : 'bg-slate-400'}`} />
            <span className={`relative inline-flex rounded-full h-2 w-2
              ${state.device.connected ? 'bg-emerald-500' : 'bg-slate-400'}`} />
          </span>
          {state.device.connected ? `Connected · ${state.device.port}` : 'Disconnected'}
        </div>
        <p className="text-[10px] text-slate-400 text-center mt-2">ECG Guardian v1.0.0</p>
      </div>
    </aside>
  );
}
