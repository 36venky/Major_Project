/**
 * Sidebar – Left navigation panel with collapse/expand toggle.
 *
 * Expanded  (w-60) : icons + labels
 * Collapsed (w-16) : icons only with hover tooltips
 *
 * The toggle button lives both here (chevron inside) and in TopBar (hamburger).
 * Live ECG page removed — waveform is on Dashboard.
 */
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, Users, History,
  FileText, BellRing, Settings, Heart,
  ChevronLeft, ChevronRight,
} from 'lucide-react';
import { useApp }     from '../context/AppContext';
import { useSidebar } from '../context/SidebarContext';

const NAV_ITEMS = [
  { to: '/',         label: 'Dashboard', icon: LayoutDashboard },
  { to: '/patients', label: 'Patients',  icon: Users },
  { to: '/history',  label: 'History',   icon: History },
  { to: '/reports',  label: 'Reports',   icon: FileText },
  { to: '/alerts',   label: 'Alerts',    icon: BellRing },
  { to: '/settings', label: 'Settings',  icon: Settings },
];

export default function Sidebar() {
  const { state }        = useApp();
  const { open, toggle } = useSidebar();
  const activeAlerts = state.alerts.filter(a => a.status === 'active').length;

  return (
    <aside
      className={`
        ${open ? 'w-60' : 'w-16'}
        min-h-screen bg-white border-r border-slate-200
        flex flex-col shrink-0
        transition-all duration-200 ease-in-out overflow-hidden
      `}
    >
      {/* Brand + toggle */}
      <div className="h-16 flex items-center gap-3 px-3 border-b border-slate-200">
        <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center shrink-0">
          <Heart className="w-4 h-4 text-white" fill="currentColor" />
        </div>

        {open && (
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-slate-800 leading-none truncate">ECG Guardian</p>
            <p className="text-[10px] text-slate-400 mt-0.5 truncate">AI Monitoring</p>
          </div>
        )}

        {/* Collapse / expand button */}
        <button
          onClick={toggle}
          title={open ? 'Collapse sidebar' : 'Expand sidebar'}
          className="ml-auto w-7 h-7 rounded-lg flex items-center justify-center
                     text-slate-400 hover:bg-slate-100 hover:text-slate-600
                     transition-colors shrink-0"
        >
          {open
            ? <ChevronLeft  className="w-4 h-4" />
            : <ChevronRight className="w-4 h-4" />
          }
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-0.5">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            title={!open ? label : undefined}
            className={({ isActive }) =>
              `relative flex items-center gap-3 px-2.5 py-2.5 rounded-lg text-sm
               font-medium transition-colors group
              ${isActive
                ? 'bg-blue-50 text-blue-700'
                : 'text-slate-600 hover:bg-slate-50 hover:text-slate-800'
              }`
            }
          >
            <Icon className="w-4 h-4 shrink-0" />
            {open && <span className="truncate">{label}</span>}

            {/* Tooltip shown only when collapsed */}
            {!open && (
              <span
                className="absolute left-full ml-2 px-2 py-1 text-xs font-medium
                           bg-slate-800 text-white rounded-lg shadow-lg
                           opacity-0 group-hover:opacity-100 pointer-events-none
                           transition-opacity whitespace-nowrap z-50"
              >
                {label}
              </span>
            )}

            {/* Alerts badge */}
            {label === 'Alerts' && activeAlerts > 0 && (
              <span
                className={`
                  text-[10px] font-semibold bg-red-500 text-white rounded-full
                  w-4 h-4 flex items-center justify-center shrink-0
                  ${open ? 'ml-auto' : 'absolute top-1 right-1'}
                `}
              >
                {activeAlerts > 9 ? '9+' : activeAlerts}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Connection status footer */}
      <div className="p-3 border-t border-slate-200">
        {open ? (
          <>
            <div className={`flex items-center gap-2 text-xs font-medium rounded-lg px-3 py-2
              ${state.device.connected
                ? 'bg-emerald-50 text-emerald-700'
                : 'bg-slate-100 text-slate-500'
              }`}
            >
              <span className="relative flex w-2 h-2 shrink-0">
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75
                  ${state.device.connected ? 'bg-emerald-400' : 'bg-slate-400'}`} />
                <span className={`relative inline-flex rounded-full h-2 w-2
                  ${state.device.connected ? 'bg-emerald-500' : 'bg-slate-400'}`} />
              </span>
              <span className="truncate">
                {state.device.connected ? `Connected · ${state.device.port}` : 'Disconnected'}
              </span>
            </div>
            <p className="text-[10px] text-slate-400 text-center mt-2">v1.0.0</p>
          </>
        ) : (
          <div className="flex justify-center">
            <span className={`w-2.5 h-2.5 rounded-full
              ${state.device.connected ? 'bg-emerald-500' : 'bg-slate-400'}`}
            />
          </div>
        )}
      </div>
    </aside>
  );
}
