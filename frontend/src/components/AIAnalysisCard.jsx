/**
 * AIAnalysisCard – ML model output panel.
 *
 * Shows two layers of analysis:
 *
 *  1. Arrhythmia classifier (rule-based, always present)
 *     – Rhythm label, arrhythmia confidence bar, risk level, signal quality
 *
 *  2. XGBoost M2 pipeline (present after first 10-s window)
 *     – Beat classification (AAMI code + full name)
 *     – XGBoost confidence %  (predict_proba)
 *     – BPM from 192-Hz RR intervals
 *     – Risk Score 0-100  (prototype)
 *     – HRV: SDNN / RMSSD
 *     – Abnormal beat %
 */
import { Brain, Activity, Heart } from 'lucide-react';
import Card from './Card';
import Badge from './Badge';
import { useApp } from '../context/AppContext';

const BEAT_COLORS = {
  N: { chip: 'bg-emerald-100 text-emerald-700', bar: 'bg-emerald-500' },
  S: { chip: 'bg-amber-100  text-amber-700',   bar: 'bg-amber-400'   },
  V: { chip: 'bg-red-100    text-red-700',      bar: 'bg-red-500'     },
  F: { chip: 'bg-purple-100 text-purple-700',   bar: 'bg-purple-500'  },
  Q: { chip: 'bg-slate-100  text-slate-600',    bar: 'bg-slate-400'   },
};

const RISK_BADGE = {
  Low:      'green',
  Moderate: 'amber',
  Medium:   'amber',
  High:     'red',
  Critical: 'red',
};

function MiniStat({ label, value, highlight }) {
  return (
    <div className="p-2 rounded-lg bg-slate-50 border border-slate-100">
      <p className="text-[10px] text-slate-400 uppercase tracking-wide leading-tight">{label}</p>
      <p className={`text-xs font-bold mt-0.5 tabular-nums ${highlight ?? 'text-slate-700'}`}>
        {value ?? '—'}
      </p>
    </div>
  );
}

export default function AIAnalysisCard() {
  const { state } = useApp();
  const ai   = state.aiAnalysis;
  const isRecording = state.isRecording;
  const hwConnected = state.device.hardwareConnected;

  // ── Arrhythmia layer ─────────────────────────────────
  const hasArrhythmia = ai.rhythm !== null && ai.confidence !== null
    && ai.rhythm !== 'Insufficient Data';
  const riskVariant   = RISK_BADGE[ai.riskLevel] ?? 'red';

  // ── XGBoost M2 layer ─────────────────────────────────
  const hasXgb    = ai.xgbBeatClass !== null;
  const beatCode  = ai.xgbBeatClass ?? null;
  const beatColor = BEAT_COLORS[beatCode] ?? BEAT_COLORS.N;
  const xgbConf   = ai.xgbConfidence ?? null;
  const xgbScore  = ai.xgbRiskScore  ?? null;
  const xgbLabel  = ai.xgbRiskLabel  ?? null;
  const xgbBpm    = ai.xgbBpm        ?? null;
  const sdnn      = ai.sdnn          ?? null;
  const rmssd     = ai.rmssd         ?? null;
  const abnPct    = ai.abnormalPct   ?? null;

  const scoreColor =
    xgbScore === null    ? 'text-slate-400' :
    xgbScore >= 70       ? 'text-rose-600'  :
    xgbScore >= 45       ? 'text-red-500'   :
    xgbScore >= 20       ? 'text-amber-600' : 'text-emerald-600';

  // Pre-Start placeholder message
  const notStartedMsg = !hwConnected
    ? 'Connect ESP32 hardware first'
    : !isRecording
    ? 'Click Start to begin analysis'
    : null;

  return (
    <Card title="AI Analysis" subtitle="Arrhythmia + XGBoost M2">

      {/* ══ SECTION 1 — Arrhythmia (rule-based) ════════ */}
      <div className="flex items-start gap-3 mb-4">
        <div className="w-9 h-9 rounded-xl bg-blue-100 flex items-center justify-center shrink-0">
          <Brain className="w-4.5 h-4.5 text-blue-600" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[10px] text-slate-400 uppercase tracking-wide mb-0.5">
            Rhythm Analysis
          </p>
          {notStartedMsg ? (
            <p className="text-sm font-semibold text-slate-400">{notStartedMsg}</p>
          ) : !hasArrhythmia ? (
            <p className="text-sm font-semibold text-slate-400 animate-pulse">
              Accumulating beats…
            </p>
          ) : (
            <p className="text-sm font-bold text-slate-800 truncate">{ai.rhythm}</p>
          )}
          {/* Arrhythmia confidence bar */}
          <div className="flex items-center gap-2 mt-1.5">
            <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-700"
                style={{ width: hasArrhythmia ? `${ai.confidence}%` : '0%' }}
              />
            </div>
            <span className="text-xs font-semibold text-blue-600 tabular-nums w-10 text-right">
              {hasArrhythmia ? `${ai.confidence}%` : '—'}
            </span>
          </div>
          <p className="text-[10px] text-slate-400 mt-0.5">Arrhythmia Confidence</p>
        </div>
      </div>

      {/* Stats row: Risk Level / HR Trend / Signal / Events */}
      <div className="grid grid-cols-2 gap-2 mb-4">
        <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
          <p className="text-[10px] text-slate-400 uppercase tracking-wide">Risk Level</p>
          {!hasArrhythmia
            ? <p className="text-xs text-slate-400 mt-0.5">—</p>
            : <Badge label={ai.riskLevel} variant={riskVariant} dot />
          }
        </div>
        <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
          <p className="text-[10px] text-slate-400 uppercase tracking-wide">HR Trend</p>
          <p className="text-xs font-semibold text-slate-700 mt-0.5">{ai.heartRateTrend}</p>
        </div>
        <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
          <p className="text-[10px] text-slate-400 uppercase tracking-wide">Signal</p>
          <p className="text-xs font-semibold text-slate-700 mt-0.5">{ai.signalQuality}</p>
        </div>
        <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
          <p className="text-[10px] text-slate-400 uppercase tracking-wide">Events</p>
          <p className="text-xs font-semibold text-slate-700 mt-0.5">
            {ai.recentEvents.length > 0
              ? <span className="text-amber-600">{ai.recentEvents.length} flagged</span>
              : <span className="text-emerald-600">None</span>
            }
          </p>
        </div>
      </div>

      {/* ══ SECTION 2 — XGBoost M2 pipeline ═══════════ */}
      <div className="border-t border-slate-100 pt-3">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-7 h-7 rounded-lg bg-indigo-100 flex items-center justify-center">
            <Activity className="w-3.5 h-3.5 text-indigo-600" />
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-700 leading-tight">
              XGBoost M2 Pipeline
            </p>
            <p className="text-[10px] text-slate-400 leading-tight">
              192 Hz · AAMI 5-class · 190-sample beat
            </p>
          </div>
        </div>

        {!hasXgb ? (
          <p className="text-xs text-slate-400 text-center py-3">
            {notStartedMsg
              ? notStartedMsg
              : isRecording
              ? 'Accumulating 10 s of ECG data…'
              : 'Awaiting 10 s of ECG data…'
            }
          </p>
        ) : (
          <div className="space-y-3">

            {/* Beat class chip + XGBoost confidence bar */}
            <div className="flex items-start gap-3">
              <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs
                font-bold shrink-0 ${beatColor.chip}`}>
                <Heart className="w-3 h-3" />
                {beatCode}
              </span>
              <div className="flex-1">
                <p className="text-xs font-semibold text-slate-700 leading-tight">
                  {ai.xgbBeatType ?? '—'}
                </p>
                {/* XGBoost confidence bar */}
                <div className="flex items-center gap-2 mt-1.5">
                  <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-700 ${beatColor.bar}`}
                      style={{ width: xgbConf !== null ? `${xgbConf}%` : '0%' }}
                    />
                  </div>
                  <span className={`text-xs font-bold tabular-nums w-12 text-right
                    ${beatColor.chip.split(' ')[1]}`}>
                    {xgbConf !== null ? `${xgbConf.toFixed(1)}%` : '—'}
                  </span>
                </div>
                <p className="text-[10px] text-slate-400 mt-0.5">XGBoost Confidence</p>
              </div>
            </div>

            {/* Risk Score 0-100 */}
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-slate-400 uppercase tracking-wide w-24 shrink-0">
                Risk Score
              </span>
              <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${beatColor.bar}`}
                  style={{ width: xgbScore !== null ? `${xgbScore}%` : '0%' }}
                />
              </div>
              <span className={`text-xs font-bold tabular-nums w-16 text-right ${scoreColor}`}>
                {xgbScore !== null ? `${xgbScore}/100` : '—'}
              </span>
              {xgbLabel && (
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full shrink-0
                  ${RISK_BADGE[xgbLabel] === 'green' ? 'bg-emerald-100 text-emerald-700' :
                    RISK_BADGE[xgbLabel] === 'amber' ? 'bg-amber-100 text-amber-700' :
                    'bg-red-100 text-red-700'}`}>
                  {xgbLabel}
                </span>
              )}
            </div>

            {/* Metrics grid: BPM / SDNN / RMSSD / Abnormal% */}
            <div className="grid grid-cols-2 gap-1.5">
              <MiniStat
                label="XGBoost BPM"
                value={xgbBpm !== null ? `${xgbBpm.toFixed(1)}` : null}
                highlight="text-blue-700"
              />
              <MiniStat
                label="Abnormal Beats"
                value={abnPct !== null ? `${abnPct.toFixed(1)}%` : null}
                highlight={
                  abnPct === null    ? 'text-slate-700' :
                  abnPct > 30        ? 'text-red-600'   :
                  abnPct > 10        ? 'text-amber-600' : 'text-emerald-600'
                }
              />
              <MiniStat
                label="HRV SDNN"
                value={sdnn !== null ? `${sdnn.toFixed(1)} ms` : null}
              />
              <MiniStat
                label="HRV RMSSD"
                value={rmssd !== null ? `${rmssd.toFixed(1)} ms` : null}
              />
            </div>

            <p className="text-[9px] text-slate-400 text-right leading-tight">
              ⚠ Risk score is a prototype metric — not a clinical diagnosis
            </p>

          </div>
        )}
      </div>

    </Card>
  );
}
