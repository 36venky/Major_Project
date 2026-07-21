/**
 * ToastContainer – Renders the global notification toasts.
 * Reads from AppContext.notifications, auto-dismisses after 5s.
 */
import { useEffect } from 'react';
import { CheckCircle, AlertTriangle, XCircle, Info, X } from 'lucide-react';
import { useApp } from '../context/AppContext';

const ICONS = {
  info:     <Info        className="w-4 h-4 text-blue-500" />,
  success:  <CheckCircle className="w-4 h-4 text-emerald-500" />,
  warning:  <AlertTriangle className="w-4 h-4 text-amber-500" />,
  critical: <XCircle    className="w-4 h-4 text-red-500" />,
  error:    <XCircle    className="w-4 h-4 text-red-500" />,
};

const BG = {
  info:     'bg-white border-blue-200',
  success:  'bg-white border-emerald-200',
  warning:  'bg-white border-amber-200',
  critical: 'bg-white border-red-200',
  error:    'bg-white border-red-200',
};

export default function ToastContainer() {
  const { state, dispatch } = useApp();

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
      {state.notifications.map(n => (
        <Toast
          key={n.id}
          notification={n}
          onDismiss={() => dispatch({ type: 'CLEAR_NOTIFICATION', payload: n.id })}
        />
      ))}
    </div>
  );
}

function Toast({ notification: n, onDismiss }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 5000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  const sev = n.severity || 'info';

  return (
    <div
      className={`pointer-events-auto flex items-start gap-3 min-w-64 max-w-sm
        border rounded-xl shadow-lg px-4 py-3 animate-fade-in ${BG[sev] || BG.info}`}
    >
      <div className="mt-0.5 flex-shrink-0">{ICONS[sev] || ICONS.info}</div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-slate-800 truncate">{n.title}</p>
        {n.description && (
          <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">{n.description}</p>
        )}
      </div>
      <button onClick={onDismiss} className="flex-shrink-0 text-slate-300 hover:text-slate-500 transition-colors">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
