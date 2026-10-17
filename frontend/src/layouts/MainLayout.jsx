/**
 * MainLayout – Shell: collapsible Sidebar + TopBar + page content.
 *
 * Mobile (< md):
 *   - Sidebar slides in as an overlay from the left; backdrop closes it.
 *   - Bottom navigation bar for quick page switching.
 *   - Main content has smaller padding (p-3 instead of p-6).
 *
 * Desktop (≥ md):
 *   - Sidebar is always visible in the left rail (collapsible to icons).
 *   - Bottom nav is hidden.
 */
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar  from './TopBar';
import MobileBottomNav from './MobileBottomNav';
import { useWebSocket }       from '../hooks/useWebSocket';
import { useMonitoringTimer } from '../hooks/useMonitoringTimer';
import ToastContainer         from '../components/ToastContainer';
import { SidebarProvider }    from '../context/SidebarContext';
import { useSidebar }         from '../context/SidebarContext';

function LayoutInner() {
  const { open, toggle } = useSidebar();

  return (
    <div className="flex h-screen overflow-hidden bg-slate-100">

      {/* ── Desktop sidebar (always in flow) ─────────── */}
      <div className="hidden md:flex md:flex-col md:shrink-0">
        <Sidebar />
      </div>

      {/* ── Mobile sidebar overlay ────────────────────── */}
      {open && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/40"
            onClick={toggle}
            aria-label="Close sidebar"
          />
          {/* Drawer */}
          <div className="relative z-50 flex flex-col w-64 bg-white shadow-xl">
            <Sidebar forcedOpen />
          </div>
        </div>
      )}

      {/* ── Main area ─────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar />
        {/* Extra bottom padding on mobile so content isn't hidden behind the bottom nav */}
        <main className="flex-1 overflow-y-auto p-3 md:p-6 pb-20 md:pb-6">
          <Outlet />
        </main>
      </div>

      {/* ── Mobile bottom navigation ───────────────────── */}
      <MobileBottomNav />

      <ToastContainer />
    </div>
  );
}

export default function MainLayout() {
  useWebSocket();
  useMonitoringTimer();

  return (
    <SidebarProvider>
      <LayoutInner />
    </SidebarProvider>
  );
}
