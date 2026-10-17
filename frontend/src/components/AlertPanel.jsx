/**
 * AlertPanel – Active alerts list with severity color-coding and dismiss button.
 */
import { X, AlertTriangle, Info, AlertCircle } from 'lucide-react';
import Card from './Card';
import { useApp } from '../context/AppContext';
import { formatTime, severityColor } from '../utils/helpers';

const SeverityIcon = ({ severity }) => {
  if (severity === 'critical') return <AlertCircle className="w-3.5 h-3.5 text-red-600" />;
  if (severity === 'warning')  return <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />;
  return <Info className="w-3.5 h-3.5 text-blue-600" />;
};

export default function AlertPanel({ maxItems = 4 }) {
  const { state, dispatch } = useApp();
  const active = state.alerts.filter(a => a.status === 'active').slice(0, maxItems);

  return (
    <Card title="Active Alerts" subtitle={`${active.length} active`}>
      {active.length === 0 ? (
        <div className="text-center py-4">
          <div className="w-10 h-10 rounded-full bg-emerald-50 flex items-center justify-center mx-auto mb-2">
            <Info className="w-5 h-5 text-emerald-500" />
          </div>
          <p className="text-xs text-slate-400">No active alerts</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {active.map(alert => {
            const c = severityColor(alert.severity);
            return (
              <li
                key={alert.id}
                className={`flex items-start gap-2.5 p-2.5 rounded-lg border ${c.bg} ${c.border} animate-slide-in`}
              >
                <SeverityIcon severity={alert.severity} />
                <div className="flex-1 min-w-0">
                  <p className={`text-xs font-semibold ${c.text}`}>{alert.title}</p>
                  <p className="text-[10px] text-slate-500 mt-0.5 truncate">{alert.description}</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">{formatTime(alert.time)}</p>
                </div>
                <button
                  onClick={() => dispatch({ type: 'DISMISS_ALERT', payload: alert.id })}
                  className="text-slate-400 hover:text-slate-600 mt-0.5"
                  title="Dismiss"
                >
                  <X className="w-3 h-3" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
