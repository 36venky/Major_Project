/**
 * History – Lists past ECG monitoring sessions with replay capability.
 */
import { useState } from 'react';
import {
  Calendar, Clock, TrendingUp, ChevronDown, ChevronUp, Play, Activity
} from 'lucide-react';
import Card from '../components/Card';
import Badge from '../components/Badge';
import { MOCK_HISTORY } from '../services/api';

function SessionRow({ session, expanded, onToggle }) {
  return (
    <div className="border border-slate-200 rounded-xl overflow-hidden mb-3 last:mb-0">
      {/* Header row */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-4 px-5 py-4 bg-white hover:bg-slate-50 transition-colors text-left"
      >
        <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
          <Activity className="w-4 h-4 text-blue-600" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-slate-800">Session {session.id}</p>
          <p className="text-xs text-slate-400">{session.date} · {session.startTime} – {session.endTime}</p>
        </div>
        <div className="flex items-center gap-4 text-xs text-slate-600 shrink-0">
          <span className="hidden sm:block">Avg: <strong>{session.avgBPM}</strong> BPM</span>
          <Badge label={session.status} variant="green" />
          {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
        </div>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-slate-100 px-5 py-4 bg-slate-50">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
            {[
              { label: 'Duration',   value: session.duration },
              { label: 'Avg BPM',   value: `${session.avgBPM} BPM` },
              { label: 'Max BPM',   value: `${session.maxBPM} BPM` },
              { label: 'Min BPM',   value: `${session.minBPM} BPM` },
            ].map(s => (
              <div key={s.label} className="text-center p-2 bg-white rounded-lg border border-slate-100">
                <p className="text-[10px] text-slate-400 uppercase tracking-wide">{s.label}</p>
                <p className="text-sm font-bold text-slate-700 mt-0.5">{s.value}</p>
              </div>
            ))}
          </div>

          {/* Events */}
          <div className="mb-3">
            <p className="text-xs font-semibold text-slate-600 mb-2">Detected Events</p>
            <div className="flex flex-wrap gap-2">
              {session.events.map((ev, i) => (
                <span key={i} className="text-[11px] px-2 py-0.5 bg-white border border-slate-200 rounded-full text-slate-600">
                  {ev}
                </span>
              ))}
            </div>
          </div>

          <button className="flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:text-blue-700 border border-blue-200 bg-blue-50 px-3 py-1.5 rounded-lg transition-colors">
            <Play className="w-3 h-3" />
            Replay Session (simulated)
          </button>
        </div>
      )}
    </div>
  );
}

export default function History() {
  const [expanded, setExpanded] = useState(null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-800">History</h1>
        <p className="text-sm text-slate-400 mt-0.5">Past ECG monitoring sessions</p>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: 'Total Sessions',  value: MOCK_HISTORY.length,   icon: Calendar },
          { label: 'Total Duration',  value: '2h 20m',              icon: Clock },
          { label: 'Avg BPM',        value: '73 BPM',              icon: TrendingUp },
          { label: 'Events Detected', value: '5',                   icon: Activity },
        ].map(s => (
          <div key={s.label} className="bg-white rounded-xl border border-slate-200 p-4 shadow-sm flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center">
              <s.icon className="w-4 h-4 text-blue-600" />
            </div>
            <div>
              <p className="text-[10px] text-slate-400 uppercase tracking-wide">{s.label}</p>
              <p className="text-base font-bold text-slate-800">{s.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Sessions list */}
      <Card title="ECG Sessions" subtitle="Click to expand details">
        <div>
          {MOCK_HISTORY.map(session => (
            <SessionRow
              key={session.id}
              session={session}
              expanded={expanded === session.id}
              onToggle={() => setExpanded(p => p === session.id ? null : session.id)}
            />
          ))}
        </div>
      </Card>
    </div>
  );
}
