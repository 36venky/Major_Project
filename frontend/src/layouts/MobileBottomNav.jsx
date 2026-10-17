/**
 * MobileBottomNav – Bottom tab bar shown only on mobile (< md).
 * Mirrors the sidebar nav items so pages are reachable with one thumb tap.
 */
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, Users, History,
  FileText, BellRing, Settings,
} from 'lucide-react';
import { useApp } from '../context/AppContext';

const NAV_ITEMS = [
  { to: '/',         label: 'Dashboard', icon: LayoutDashboard },
  { to: '/patients', label: 'Patients',  icon: Users },
  { to: '/history',  label: 'History',   icon: History },
  { to: '/reports',  label: 'Reports',   icon: FileText },
  { to: '/alerts',   label: 'Alerts',    icon: BellRing },
  { to: '/settings', label: 'Settings',  icon: Settings },
];

export default function MobileBottomNav() {
  const { state } = useApp();
  const activeAlerts = state.alerts.filter(a => a.status === 'active').length;

  return (
    <nav
      className="
        md:hidden
        fixed bottom-0 left-0 right-0 z-30
        bg-white border-t border-slate-200
        flex items-center justify-around
        h-16 px-1 safe-area-pb
      "
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          className={({ isActive }) =>
            `relative flex flex-col items-center justify-center gap-0.5
             flex-1 h-full text-[10px] font-medium transition-colors
             ${isActive ? 'text-blue-600' : 'text-slate-400 hover:text-slate-600'}`
          }
        >
          {({ isActive }) => (
            <>
              <div className={`w-8 h-8 rounded-xl flex items-center justify-center transition-colors
                ${isActive ? 'bg-blue-50' : ''}`}>
                <Icon className="w-4 h-4" />
              </div>
              <span>{label}</span>

              {/* Alert badge */}
              {label === 'Alerts' && activeAlerts > 0 && (
                <span className="absolute top-1 right-1/4 w-4 h-4 bg-red-500 text-white
                                 text-[9px] font-bold rounded-full flex items-center justify-center">
                  {activeAlerts > 9 ? '9+' : activeAlerts}
                </span>
              )}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
