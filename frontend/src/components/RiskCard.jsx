/**
 * RiskCard – Displays the latest M2 XGBoost prediction.
 *
 * riskPrediction payload (from WebSocket analysis.riskPrediction):
 *   risk_percentage : number   – XGBoost confidence (0-100)
 *   risk_level      : string   – "Low" | "Moderate" | "High"
 *   majority_label  : string   – AAMI short code e.g. "V"
 *   beat_type       : string   – e.g. "Ventricular Ectopic"
 *   xgb_bpm         : number   – BPM from 192-Hz RR intervals
 *   sdnn_ms         : number   – HRV SDNN (ms)
 *   rmssd_ms        : number   – HRV RMSSD (ms)
 *   abnormal_pct    : number   – % of abnormal beats this session
 *   risk_score      : number   – composite 0-100 prototype score
 *   risk_label      : string   – "Low"|"Moderate"|"High"|"Critical"
 *   timestamp       : string   – ISO-8601
 *
 * NOTE: risk_score/100 is a prototype/project metric —
 *       NOT a clinically validated diagnostic score.
 */
import { useApp } from '../context/AppContext';
import Card from './Card';

const LEVEL_STYLES = {
  Low:      { badge: 'bg-emerald-100 text-emerald-700', bar: 'bg-emerald-500', dot: 'bg-emerald-500', ring: 'ring-emerald-200' },
  Moderate: { badge: 'bg-amber-100  text-amber-700',   bar: 'bg-amber-400',   dot: 'bg-amber-400',   ring: 'ring-amber-200'   },
  High:     { badge: 'bg-red-100    text-red-700',      bar: 'bg-red-500',     dot: 'bg-red-500',     ring: 'ring-red-200'     },
  Critical: { badge: 'bg-rose-100   text-rose-800',     bar: 'bg-rose-600',    dot: 'bg-rose-600',    ring: 'ring-rose-200'    },
};

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
  const hardwareConnected = state.device?.hardwareConnected ?? false;

  const confLevel  = risk?.risk_level  || 'Low';
  const riskLabel  = risk?.risk_label  || confLevel;    // composite label
  const pct        = risk?.risk_percentage ?? null;     // XGBoost confidence
  const riskScore  = risk?.risk_score      ?? null;     // 0-100 composite
  const beatType   = risk?.beat_type || (risk?.majority_label ? LABEL_TITLE[risk.majority_label] : null);
  const shortCode  = risk?.majority_label ?? null;
  const xgbBpm     = risk?.xgb_bpm        ?? null;
  const sdnn       = risk?.sdnn_ms         ?? null;
  const rmssd      = risk?.rmssd_ms        ?? null;
  const abnPct     = risk?.abnormal_pct    ?? null;
  const ts         = risk?.timestamp
    ? new Date(risk.timestamp).toLocaleTimeString()
    : '—';

  // Use composite label for badge colour if available
  const badgeKey   = LEVEL_STYLES[riskLabel] ? riskLabel : confLevel;
  const styles     = LEVEL_STYLES[badgeKey] || LEVEL_STYLES.Low;

  // Loading state: hardware connected but XGBoost window not yet full (10 seconds)
  // Mutually exclusive with no-data state (hardware disconnected)
  const isCollectingBaseline = hardwareConnected && !risk;

  return (
    <Card title="Risk Prediction" subtitle="M2 XGBoost · AAMI 5-class">
      <div className="flex flex-col gap-3">

        {/* ── Confidence % + risk-level badge ────────── */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-3xl font-bold text-slateate-800">
              {pct !== null ? `${pct.toFixed(1)}%` : '—'}
            </p>
            <p className="text-xs text-slate-400 mt-0.5">Confidence Score</p>
          </div>
          <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
            text-sm font-semibold ring-1 ${styles.badge} ${styles.ring}`}>
            <span className={`w-2 h-2 rounded-full ${styles.dot}`} />
            {confLevel}
          </span>
        </div>

        {/* ── Confidence progress bar ─────────────────── */}
        {pct !== null && (
          <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ${styles.bar}`}
              style={{ width: `${Math.min(100, pct)}%` }}
            />
          </div>
        )}

        {/* ── Beat classification ─────────────────────── */}
        {beatType && (
          <div className="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-slate-50 border border-slate-100">
            <div className={`w-2 h-2 rounded-full shrink-0 ${styles.dot}`} />
            <div>
              <p className="text-[10px] text-slate-400 uppercase tracking-wide">Beat Classification</p>
              <p className="text-xs font-semibold text-slate-700">
                {beatType}
                {shortCode && (
                  <span className="ml-1.5 text-[10px] font-mono text-slate-400
                    bg-slate-100 px-1 py-0.5 rounded">
                    {shortCode}
                  </span>
                )}
              </p>
            </div>
          </div>
        )}

        {/* ── Risk Score 0-100 ────────────────────────── */}
        {riskScore !== null && (
          <div className="flex items-center gap-2 px-2.5 py-2 rounded-lg
            bg-slate-50 border border-slate-100">
            <div>
              <p className="text-[10px] text-slate-400 uppercase tracking-wide">
                Risk Score
                <span className="ml-1 text-slate-300 normal-case">(prototype)</span>
              </p>
              <div className="flex items-center gap-2 mt-0.5">
                <div className="flex-1 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${styles.bar}`}
                    style={{ width: `${Math.min(100, riskScore)}%` }}
                  />
                </div>
                <span className={`text-xs font-bold tabular-nums ${
                  riskScore >= 70 ? 'text-rose-600' :
                  riskScore >= 45 ? 'text-red-500'  :
                  riskScore >= 20 ? 'text-amber-600' : 'text-emerald-600'
                }`}>
                  {riskScore}
                  <span className="text-[10px] font-normal text-slate-400">/100</span>
                </span>
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full
                  ${styles.badge}`}>
                  {riskLabel}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* ── Stats grid: BPM / SDNN / RMSSD / Abnormal ─ */}
        <div className="grid grid-cols-2 gap-2">
          <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
            <p className="text-[10px] text-slate-400 uppercase tracking-wide">XGBoost BPM</p>
            <p className="text-sm font-bold tabular-nums text-blue-700 mt-0.5">
              {xgbBpm !== null ? `${xgbBpm.toFixed(1)}` : '—'}
            </p>
          </div>
          <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
            <p className="text-[10px] text-slate-400 uppercase tracking-wide">Abnormal Beats</p>
            <p className={`text-sm font-bold tabular-nums mt-0.5 ${
              abnPct !== null && abnPct > 30 ? 'text-red-600' :
              abnPct !== null && abnPct > 10 ? 'text-amber-600' : 'text-slate-700'
            }`}>
              {abnPct !== null ? `${abnPct.toFixed(1)}%` : '—'}
            </p>
          </div>
          <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
            <p className="text-[10px] text-slate-400 uppercase tracking-wide">HRV SDNN</p>
            <p className="text-sm font-bold tabular-nums text-slate-700 mt-0.5">
              {sdnn !== null ? `${sdnn.toFixed(1)} ms` : '—'}
            </p>
          </div>
          <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
            <p className="text-[10px] text-slate-400 uppercase tracking-wide">HRV RMSSD</p>
            <p className="text-sm font-bold tabular-nums text-slate-700 mt-0.5">
              {rmssd !== null ? `${rmssd.toFixed(1)} ms` : '—'}
            </p>
          </div>
        </div>

        <div className="flex justify-end">
          <p className="text-[10px] text-slate-400">Updated {ts}</p>
        </div>

        {/* Loading indicator: hardware connected, waiting for 10-second XGBoost window */}
        {isCollectingBaseline && (
          <div className="flex items-center justify-center gap-2 py-3 px-4 rounded-lg
            bg-blue-50 border border-blue-100">
            <svg className="animate-spin h-4 w-4 text-blue-500" xmlns="http://www.w3.org/2000/svg"
              fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <div className="text-left">
              <p className="text-xs font-semibold text-blue-700">Collecting baseline data</p>
              <p className="text-[10px] text-blue-500">XGBoost requires 10 seconds of signal</p>
            </div>
          </div>
        )}

        {/* No-data fallback: hardware NOT connected (mutually exclusive with loading state) */}
        {!hardwareConnected && !risk && (
          <p className="text-xs text-slate-400 text-center py-2">
            Awaiting hardware connection…
          </p>
        )}
      </div>
    </Card>
  );
}
