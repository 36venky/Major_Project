/**
 * RiskCard – Displays the latest ML risk prediction.
 * Data comes from AppContext.riskPrediction (populated via WebSocket analysis payload).
 */
import { useApp } from '../context/AppContext';
import Card from './Card';
import StatRow from './StatRow';

const LEVEL_STYLES = {
  Low:      { badge: 'bg-emerald-100 text-emerald-700', dot: 'bg-emerald-500' },
  Moderate: { badge: 'bg-amber-100  text-amber-700',   dot: 'bg-amber-400'   },
  High:     { badge: 'bg-red-100    text-red-700',      dot: 'bg-red-500'     },
};

export default function RiskCard() {
  const { state } = useApp();
  const risk = state.riskPrediction;

  const level  = risk?.risk_level  || 'Low';
  const pct    = risk?.risk_percentage ?? null;
  const ts     = risk?.timestamp
    ? new Date(risk.timestamp).toLocaleString()
    : '—';

  const styles = LEVEL_STYLES[level] || LEVEL_STYLES.Low;

  return (
    <Card title="Risk Prediction" subtitle="ML ensemble model">
      <div className="flex flex-col gap-3">
        {/* Risk percentage + gauge */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-3xl font-bold text-slate-800">
              {pct !== null ? `${pct}%` : '—'}
            </p>
            <p className="text-xs text-slate-400 mt-0.5">Risk Score</p>
          </div>
          <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-semibold ${styles.badge}`}>
            <span className={`w-2 h-2 rounded-full ${styles.dot}`} />
            {level}
          </span>
        </div>

        {/* Progress bar */}
        {pct !== null && (
          <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ${
                level === 'High' ? 'bg-red-500' :
                level === 'Moderate' ? 'bg-amber-400' : 'bg-emerald-500'
              }`}
              style={{ width: `${Math.min(100, pct)}%` }}
            />
          </div>
        )}

        <StatRow label="Last updated" value={ts} />
        {!risk && (
          <p className="text-xs text-slate-400 text-center py-2">
            Awaiting first prediction…
          </p>
        )}
      </div>
    </Card>
  );
}
