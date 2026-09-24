/**
 * AIAnalysisCard – Shows ML model output: rhythm, confidence, risk, signal quality.
 */
import { Brain, ShieldCheck } from 'lucide-react';
import Card from './Card';
import Badge from './Badge';
import { useApp } from '../context/AppContext';
import { riskColor } from '../utils/helpers';

export default function AIAnalysisCard() {
  const { state } = useApp();
  const ai = state.aiAnalysis;

  // "Moderate" is the string the backend sends — map it to amber.
  // "Medium" kept for backwards compat. Anything else → red.
  const riskVariant =
    ai.riskLevel === 'Low'                          ? 'green' :
    ai.riskLevel === 'Medium' || ai.riskLevel === 'Moderate' ? 'amber' : 'red';

  // Show loading state until the first real analysis arrives from the backend
  const isLoading = ai.rhythm === null || ai.confidence === null;

  return (
    <Card title="AI Analysis" subtitle="Model inference">
      {/* Rhythm + confidence */}
      <div className="flex items-start gap-3 mb-4">
        <div className="w-10 h-10 rounded-xl bg-blue-100 flex items-center justify-center shrink-0">
          <Brain className="w-5 h-5 text-blue-600" />
        </div>
        <div className="flex-1">
          {isLoading ? (
            <p className="text-sm font-semibold text-slate-400 animate-pulse">Awaiting analysis…</p>
          ) : (
            <p className="text-sm font-bold text-slate-800">{ai.rhythm}</p>
          )}
          <div className="flex items-center gap-2 mt-1">
            <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-700"
                style={{ width: isLoading ? '0%' : `${ai.confidence}%` }}
              />
            </div>
            <span className="text-xs font-semibold text-blue-600">
              {isLoading ? '—' : `${ai.confidence}%`}
            </span>
          </div>
          <p className="text-[10px] text-slate-400 mt-0.5">Confidence Score</p>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-2">
        <div className="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
          <p className="text-[10px] text-slate-400 uppercase tracking-wide">Risk Level</p>
          {isLoading
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
          <p className="text-xs font-semibold text-slate-700 mt-0.5">{ai.recentEvents.length} recent</p>
        </div>
      </div>
    </Card>
  );
}
