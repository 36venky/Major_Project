/**
 * Alerts – Full-page alert management with all alerts and filter tabs.
 */
import { useState } from 'react';
import { X, AlertCircle, AlertTriangle, Info, BellRing } from 'lucide-react';
import Card from '../components/Card';
import { useApp } from '../context/AppContext';
import { formatDateTime, severityColor } from '../utils/helpers';

const TABS = ['all', 'active', 'dismissed'];

export default function Alerts() {
  const { state, dispatch } = useApp();
  const [tab, setTab] = useState('all');

  const filtered = state.alerts.filter(a => {
    if (tab === 'all')       return true;
    if (tab === 'active')    return a.status === 'active';
    if (tab === 'dismissed') return a.status === 'dismissed';
    return true;
  });

  const activeCount = state.alerts.filter(a => a.status === 'active').length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Alerts</h1>
          <p className="text-sm text-slate-400 mt-0.5">{activeCount} active alert{activeCount !== 1 ? 's' : ''}</p>
        </div>
        <button
          onClick={() => state.alerts.filter(a => a.status === 'active').forEach(a =>
            dispatch({ type: 'DISMISS_ALERT', payload: a.id })
          )}
          className="text-xs text-slate-600 border border-slate-200 bg-white px-3 py-1.5 rounded-lg hover:bg-slate-50 transition-colors"
        >
          Dismiss All
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 bg-white rounded-lg border border-slate-200 p-1 w-fit">
        {TABS.map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`text-xs font-medium px-3 py-1.5 rounded-md capitalize transition-colors
              ${tab === t ? 'bg-blue-600 text-white' : 'text-slate-500 hover:text-slate-700'}`}
          >
            {t}
          </button>
        ))}
      </div>

      <Card noPad>
        {filtered.length === 0 ? (
          <div className="text-center py-12">
            <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center mx-auto mb-3">
              <BellRing className="w-6 h-6 text-slate-400" />
            </div>
            <p className="text-sm text-slate-400">No alerts found</p>
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {filtered.map(alert => {
              const c = severityColor(alert.severity);
              const Icon = alert.severity === 'critical' ? AlertCircle :
                           alert.severity === 'warning'  ? AlertTriangle : Info;
              return (
                <li key={alert.id} className={`flex items-start gap-4 px-5 py-4 ${alert.status === 'dismissed' ? 'opacity-50' : ''}`}>
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${c.bg} mt-0.5`}>
                    <Icon className={`w-4 h-4 ${c.text}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="text-sm font-semibold text-slate-800">{alert.title}</p>
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${c.badge} uppercase`}>
                        {alert.severity}
                      </span>
                      {alert.status === 'dismissed' && (
                        <span className="text-[10px] text-slate-400 italic">dismissed</span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">{alert.description}</p>
                    <p className="text-[10px] text-slate-400 mt-1">{formatDateTime(alert.time)}</p>
                  </div>
                  {alert.status === 'active' && (
                    <button
                      onClick={() => dispatch({ type: 'DISMISS_ALERT', payload: alert.id })}
                      className="text-slate-400 hover:text-slate-600 mt-1"
                      title="Dismiss"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
