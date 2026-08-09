/**
 * RiskCard – Displays the latest ML risk prediction from the M2 XGBoost model.
 *
 * Payload shape (from WebSocket analysis.riskPrediction):
 *   {
 *     risk_percentage : number,   e.g. 87.3
 *     risk_level      : string,   "Low" | "Moderate" | "High"
 *     majority_label  : string,   short AAMI code, e.g. "V"
 *     beat_type       : string,   human-readable, e.g. "Ventricular Ectopic"
 *     timestamp       : string,   ISO-8601
 *   }
 */
import { useApp } from '../context/AppContext';
import Card from './Card';
import StatRow from './StatRow';

const LEVEL_STYLES = {
  Low:      { badge: 'bg-emerald-100 text-emerald-700', bar: 'bg-emerald-500', dot: 'bg-emerald-500' },
  Moderate: { badge: 'bg-amber-100  text-amber-700',   bar: 'bg-amber-400',   dot: 'bg-amber-400'   },
  High:     { badge: 'bg-red-100    text-red-700',      bar: 'bg-red-500',     dot: 'bg-red-500'     },
};

// Short AAMI code → accessible label for screen readers / tooltips
const LABEL_TITLE = {
  N: 'Normal Sinus Beat',
  S: 'Supraventricular Ectopic',
  V: 'Ventricular Ectopic',
  F: 'Fusion Beat',
  Q: 'Unclassifiable Beat',
};

export default function RiskCard() {
  const { state } = useApp();
  const risk = state.riskPrediction;

  const level     = risk?.risk_level      || 'Low';
  const pct       = risk?.risk_percentage ?? null;
  const beatType  = risk?.beat_type       || (risk?.majority_label ? LABEL_TITLE[risk.majority_label] : null);
  const shortCode = risk?.majority_label  || null;
  const ts        = risk?.timestamp
    ? new Date(risk.timestamp).toLocaleString()
    : '—';

  const styles = LEVEL_STYLES[level] || LEVEL_STYLES.Low;

  return (
    <Card title="Risk Prediction" subtitle="M2 XGBoost · AAMI 5-class">
      <div className="flex flex-col gap-3">

        {/* Risk percentage + risk-level badge */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-3xl font-bold text-slate-800">
              {pct !== null ? `${pct}%` : '—'}
            </p>
            <p className="text-xs text-slate-400 mt-0.5">Confidence Score</p>
          </div>
          <span
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-semibold ${styles.badge}`}
          >
            <span className={`w-2 h-2 rounded-full ${styles.dot}`} />
            {level}
          </span>
        </div>

        {/* Progress bar */}
        {pct !== null && (
          <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ${styles.bar}`}
              style={{ width: `${Math.min(100, pct)}%` }}
            />
          </div>
        )}

        {/* Beat type — human-readable label from M2 model */}
        {beatType && (
          <div className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-slate-50 border border-slate-100">
            <div className={`w-2 h-2 rounded-full shrink-0 ${styles.dot}`} />
            <div>
              <p className="text-[10px] text-slate-400 uppercase tracking-wide">Beat Classification</p>
              <p className="text-xs font-semibold text-slate-700">
                {beatType}
                {shortCode && (
                  <span className="ml-1.5 text-[10px] font-mono text-slate-400 bg-slate-100 px-1 py-0.5 rounded">
                    {shortCode}
                  </span>
                )}
              </p>
            </div>
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
