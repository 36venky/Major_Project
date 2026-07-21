/**
 * App.jsx – Root component with React Router routes.
 */
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AppProvider } from './context/AppContext';
import MainLayout from './layouts/MainLayout';
import Dashboard from './pages/Dashboard';
import Patients from './pages/Patients';
import LiveECG from './pages/LiveECG';
import History from './pages/History';
import Reports from './pages/Reports';
import Alerts from './pages/Alerts';
import Settings from './pages/Settings';

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/"         element={<Dashboard />} />
            <Route path="/patients" element={<Patients />} />
            <Route path="/live-ecg" element={<LiveECG />} />
            <Route path="/history"  element={<History />} />
            <Route path="/reports"  element={<Reports />} />
            <Route path="/alerts"   element={<Alerts />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppProvider>
  );
}
