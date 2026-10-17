/**
 * History – Lists past ECG monitoring sessions with real backend data.
 *
 * Loads sessions from GET /ecg/history?patient_id=<id>&limit=50.
 * Falls back to MOCK_HISTORY if the backend is unreachable or returns no data.
 */
import { useState, useEffect } from 'react';
import {
  Calendar, Clock, TrendingUp, ChevronDown, ChevronUp, Play, Activity, Loader2
} from 'lucide-react';
import Card from '../components/Card';
import Badge from '../components/Badge';
import { MOCK_HISTORY, getEcgHistory } from '../services/api';
import { useApp } from '../context/AppContext';

/** Format "HH:MM:SS" duration string from a session object. */
function formatDuration(session) {
  if (session.duration) return session.duration;
  if (session.start_time && session.end_time) {
    const ms = new Date(session.end_time) - new Date(session.start_time);
    const totalSec = Math.floor(ms / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  }
  return '—';
}

/** Map a backend ECGSession row to the shape SessionRow expects. */
function sessionFromBackend(row) {
  const start = row.start_time ? new Date(row.start_time) : null;
  const end   = row.end_time   ? new Date(row.end_time)   : null;
  return {
    id:        row.session_id,
    date:      start ? start.toLocaleDateString() : '—',
    startTime: start ? start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—',
    endTime:   end   ? end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })   : 'Active',
    duration:  formatDuration(row),
    avgBPM:    row.average_bpm ?? '—',
    maxBPM:    row.maximum_bpm ?? '—',
    minBPM:    row.minimum_bpm ?? '—',
    events:    row.is_active ? ['Session Active'] : ['Session Completed'],
    status:    row.is_active ? 'Active' : 'Completed',
  };
}

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
          <span className="hidden sm:block">
            Avg: <strong>{session.avgBPM}{typeof session.avgBPM === 'number' ? ' BPM' : ''}</strong>
          </span>
          <Badge label={session.status} variant={session.status === 'Active' ? 'blue' : 'green'} />
          {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
        </div>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-slate-100 px-5 py-4 bg-slate-50">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
            {[
              { label: 'Duration', value: session.duration },
              { label: 'Avg BPM',  value: typeof session.avgBPM === 'number' ? `${session.avgBPM} BPM` : session.avgBPM },
              { label: 'Max BPM',  value: typeof session.maxBPM === 'number' ? `${session.maxBPM} BPM` : session.maxBPM },
              { label: 'Min BPM',  value: typeof session.minBPM === 'number' ? `${session.minBPM} BPM` : session.minBPM },
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
  const { state }         = useApp();
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [usingMock, setUsingMock] = useState(false);
  const [expanded, setExpanded]   = useState(null);

  useEffect(() => {
    if (!state.patient?.id) return;

    setLoading(true);
    getEcgHistory(state.patient.id, 50)
      .then(rows => {
        if (rows && rows.length > 0) {
          setSessions(rows.map(sessionFromBackend));
          setUsingMock(false);
        } else {
          // No sessions yet — fall back to mock so the UI isn't empty
          setSessions(MOCK_HISTORY);
          setUsingMock(true);
        }
      })
      .catch(() => {
        // Backend unreachable — show mock data
        setSessions(MOCK_HISTORY);
        setUsingMock(true);
      })
      .finally(() => setLoading(false));
  }, [state.patient?.id]);

  // Compute summary stats from loaded sessions
  const totalSessions = sessions.length;
  const avgBPMs       = sessions.map(s => s.avgBPM).filter(v => typeof v === 'number');
  const overallAvg    = avgBPMs.length
    ? Math.round(avgBPMs.reduce((a, b) => a + b, 0) / avgBPMs.length)
    : '—';
  const eventCount    = sessions.reduce((acc, s) => acc + (s.events?.length ?? 0), 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">History</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Past ECG monitoring sessions
            {usingMock && !loading && (
              <span className="ml-2 text-[10px] text-amber-500 font-medium bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded-full">
                sample data
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: 'Total Sessions',   value: loading ? '…' : totalSessions,          icon: Calendar },
          { label: 'Avg BPM',          value: loading ? '…' : `${overallAvg} BPM`,    icon: TrendingUp },
          { label: 'Events Detected',  value: loading ? '…' : eventCount,              icon: Activity },
          { label: 'Duration',         value: loading ? '…' : sessions[0]?.duration ?? '—', icon: Clock },
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
        {loading ? (
          <div className="flex items-center justify-center py-10 gap-2 text-slate-400">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-sm">Loading sessions…</span>
          </div>
        ) : (
          <div>
            {sessions.map(session => (
              <SessionRow
                key={session.id}
                session={session}
                expanded={expanded === session.id}
                onToggle={() => setExpanded(p => p === session.id ? null : session.id)}
              />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
