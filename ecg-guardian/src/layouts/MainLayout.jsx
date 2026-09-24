/**
 * MainLayout – Shell: collapsible Sidebar + TopBar + page content.
 * SidebarProvider gives the sidebar its open/close state.
 */
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import TopBar  from './TopBar';
import { useWebSocket }       from '../hooks/useWebSocket';
import { useMonitoringTimer } from '../hooks/useMonitoringTimer';
import ToastContainer         from '../components/ToastContainer';
import { SidebarProvider }    from '../context/SidebarContext';

export default function MainLayout() {
  useWebSocket();
  useMonitoringTimer();

  return (
    <SidebarProvider>
      <div className="flex h-screen overflow-hidden bg-slate-100">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <TopBar />
          <main className="flex-1 overflow-y-auto p-6">
            <Outlet />
          </main>
        </div>
        <ToastContainer />
      </div>
    </SidebarProvider>
  );
}
