/**
 * Reports – Patient monitoring report page.
 *
 * Features:
 * - On-screen summary with live BPM sparkline, Blood Sugar trend,
 *   and Blood Pressure (systolic) trend using Recharts.
 * - Real PDF download: fetches /reports/pdf/{session_id} from the
 *   backend (ReportLab-generated, includes line charts).
 * - Session selector: lists past ECG sessions and downloads the
 *   PDF for whichever one is chosen.
 */
import { useState, useEffect, useCallback } from 'react';
import { FileText, Download, Loader2, ChevronDown } from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, ReferenceLine,
} from 'recharts';
import Card from '../components/Card';
import StatRow from '../components/StatRow';
import { useApp } from '../context/AppContext';
import { formatDateTime } from '../utils/helpers';
import { getAuthHeaders } from '../services/auth';

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

// ── Helpers ───────────────────────────────────────────────

function parseNumeric(str) {
  if (!str) return null;
  const m = str.match(/[\d.]+/);
  return m ? parseFloat(m[0]) : null;
}

function parseSystolic(str) {
  if (!str) return null;
  const m = str.match(/^([\d.]+)\s*\//);
  return m ? parseFloat(m[1]) : parseNumeric(str);
}

// ── Mini sparkline ────────────────────────────────────────

function Sparkline({ data, color, unit, label }) {
  if (!data || data.length < 2) {
    return (
      <div className="flex items-center justify-center h-20 text-xs text-slate-400">
        Not enough data
      </div>
    );
  }
  return (
    <div>
      <p className="text-[10px] text-slate-400 uppercase tracking-wide mb-1">{label}</p>
      <ResponsiveContainer width="100%" height={72}>
        <LineChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="label" tick={{ fontSize: 8 }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 8 }} width={32} />
          <Tooltip
            contentStyle={{ fontSize: 10 }}
            formatter={v => [`${v} ${unit}`, label]}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.8}
            dot={false}
            activeDot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── BPM sparkline from heartRate.history ─────────────────

function BPMSparkline({ history }) {
  const data = history.slice(-30).map((v, i) => ({ label: i + 1, value: v }));
  return (
    <div>
      <p className="text-[10px] text-slate-400 uppercase tracking-wide mb-1">
        BPM — last {data.length} readings
      </p>
      <ResponsiveContainer width="100%" height={72}>
        <LineChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="label" tick={{ fontSize: 8 }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 8 }} width={32} domain={['auto', 'auto']} />
          <Tooltip
            contentStyle={{ fontSize: 10 }}
            formatter={v => [`${v} BPM`, 'Heart Rate']}
          />
          <ReferenceLine y={100} stroke="#ef4444" strokeDasharray="3 3" />
          <ReferenceLine y={60}  stroke="#f59e0b" strokeDasharray="3 3" />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#10b981"
            strokeWidth={1.8}
            dot={false}
            activeDot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────

export default function Reports() {
  const { state } = useApp();
  const p  = state.patient;    // may be null — guard below before using p.id
  const wh = state.weeklyHealth;
  const hr = state.heartRate;

  const [sessions,        setSessions]        = useState([]);
  const [selectedSession, setSelectedSession] = useState('');
  const [downloading,     setDownloading]     = useState(false);
  const [downloadError,   setDownloadError]   = useState('');
  const [loadingSessions, setLoadingSessions] = useState(false);

  // ── Fetch session list on mount ───────────────────────
  useEffect(() => {
    const load = async () => {
      if (!p?.id) { setLoadingSessions(false); return; }
      setLoadingSessions(true);
      try {
        const headers = await getAuthHeaders();
        const res = await fetch(
          `${BASE_URL}/ecg/history?patient_id=${p?.id ?? ''}&limit=20`,
          { headers },
        );
        if (!res.ok) throw new Error('Failed to load sessions');
        const data = await res.json();
        setSessions(data);
        if (data.length > 0) setSelectedSession(data[0].session_id);
      } catch {
        // silently fall back — user can still see on-screen report
      } finally {
        setLoadingSessions(false);
      }
    };
    load();
  }, [p?.id]);

  // ── Real PDF download ─────────────────────────────────
  const handleDownloadPDF = useCallback(async () => {
    if (!selectedSession) {
      setDownloadError('No session selected. Start a monitoring session first.');
      return;
    }
    setDownloading(true);
    setDownloadError('');
    try {
      const headers = await getAuthHeaders();
      const res = await fetch(
        `${BASE_URL}/reports/pdf/${selectedSession}`,
        { headers },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.message || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = `ecg_report_${selectedSession}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setDownloadError(err.message ?? 'Download failed. Ensure the backend is running.');
    } finally {
      setDownloading(false);
    }
  }, [selectedSession]);

  // ── Build health trend data from weeklyHealth state ───
  // The state only holds the latest entry; we use heartRate.history for BPM.
  // For Sugar/BP we use the single value to show a reference point.
  const sugarVal     = parseNumeric(wh.bloodSugar);
  const bpVal        = parseSystolic(wh.bloodPressure);
  // Single-point trend — shows as a flat reference line until more data is fetched
  const sugarData    = sugarVal != null ? [{ label: 'Latest', value: sugarVal }] : [];
  const bpData       = bpVal    != null ? [{ label: 'Latest', value: bpVal }]    : [];

  return (
    <div className="space-y-6">
      {/* ── Page header ─────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Reports</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Download session PDF or review live health metrics
          </p>
        </div>

        {/* Session selector + Download button */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Session dropdown */}
          <div className="relative">
            <select
              value={selectedSession}
              onChange={e => setSelectedSession(e.target.value)}
              className="appearance-none text-sm border border-slate-200 rounded-lg
                         pl-3 pr-8 py-2 text-slate-700 bg-white focus:outline-none
                         focus:ring-2 focus:ring-blue-500/30 min-w-[220px]"
            >
              {loadingSessions && (
                <option value="">Loading sessions…</option>
              )}
              {!loadingSessions && sessions.length === 0 && (
                <option value="">No sessions available</option>
              )}
              {sessions.map(s => (
                <option key={s.session_id} value={s.session_id}>
                  {s.session_id} — {s.start_time
                    ? new Date(s.start_time).toLocaleDateString()
                    : 'Active'}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-2.5 w-4 h-4 text-slate-400 pointer-events-none" />
          </div>

          {/* Download PDF */}
          <button
            onClick={handleDownloadPDF}
            disabled={downloading || !selectedSession}
            className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg
                       bg-blue-600 text-white hover:bg-blue-700 transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {downloading
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Generating…</>
              : <><Download className="w-4 h-4" /> Download PDF</>
            }
          </button>
        </div>
      </div>

      {/* Download error */}
      {downloadError && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
          {downloadError}
        </div>
      )}

      {/* ── Report body ──────────────────────────────── */}
      <div className="space-y-4">

        {/* Header card */}
        <div className="bg-blue-700 text-white rounded-xl p-6">
          <div className="flex items-center gap-3 mb-1">
            <FileText className="w-6 h-6" />
            <h2 className="text-lg font-bold">ECG Guardian — Patient Report</h2>
          </div>
          <p className="text-blue-200 text-sm">
            Generated: {formatDateTime(new Date().toISOString())}
          </p>
          {selectedSession && (
            <p className="text-blue-300 text-xs mt-0.5">Session: {selectedSession}</p>
          )}
        </div>

        {/* Patient + Monitoring summary */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card title="Patient Information">
            <StatRow label="Name"              value={p?.name             || '—'} />
            <StatRow label="Patient ID"        value={p?.id               || '—'} />
            <StatRow label="Age"               value={p?.age ? `${p.age} years` : '—'} />
            <StatRow label="Gender"            value={p?.gender           || '—'} />
            <StatRow label="Blood Group"       value={p?.bloodGroup       || '—'} />
            <StatRow label="Height"            value={p?.height           || '—'} />
            <StatRow label="Weight"            value={p?.weight           || '—'} />
            <StatRow label="Guardian"          value={p?.guardianName     || '—'} />
            <StatRow label="Emergency Contact" value={p?.emergencyContact || '—'} />
          </Card>

          <Card title="Monitoring Summary">
            <StatRow label="Current BPM"   value={`${hr.current} BPM`} />
            <StatRow label="Status"        value={hr.status} />
            <StatRow
              label="Avg BPM"
              value={hr.history.length
                ? `${Math.round(hr.history.reduce((a, b) => a + b, 0) / hr.history.length)} BPM`
                : '—'}
            />
            <StatRow
              label="Max BPM"
              value={hr.history.length ? `${Math.max(...hr.history)} BPM` : '—'}
            />
            <StatRow
              label="Min BPM"
              value={hr.history.length ? `${Math.min(...hr.history)} BPM` : '—'}
            />
            <StatRow label="Blood Pressure" value={wh.bloodPressure} />
            <StatRow label="Blood Sugar"    value={wh.bloodSugar} />
            <StatRow label="Last Updated"   value={formatDateTime(wh.lastUpdated)} />
          </Card>
        </div>

        {/* ── Live trend charts ─────────────────────── */}
        <Card title="Health Trends">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 pt-1">
            {/* BPM history */}
            <BPMSparkline history={hr.history} />

            {/* Blood Sugar */}
            <Sparkline
              data={sugarData}
              color="#f59e0b"
              unit="mg/dL"
              label="Blood Sugar"
            />

            {/* Blood Pressure (systolic) */}
            <Sparkline
              data={bpData}
              color="#7c3aed"
              unit="mmHg"
              label="BP Systolic"
            />
          </div>

          <p className="text-[10px] text-slate-400 mt-3">
            BPM trend uses live session readings. Sugar &amp; BP reflect the latest
            manually recorded entry. The downloaded PDF includes full historical charts.
          </p>
        </Card>

        {/* AI Analysis */}
        <Card title="AI Analysis Summary">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'Rhythm',         value: state.aiAnalysis.rhythm },
              { label: 'Confidence',     value: `${state.aiAnalysis.confidence}%` },
              { label: 'Risk Level',     value: state.aiAnalysis.riskLevel },
              { label: 'Signal Quality', value: state.aiAnalysis.signalQuality },
            ].map(s => (
              <div
                key={s.label}
                className="p-3 bg-slate-50 rounded-lg text-center border border-slate-100"
              >
                <p className="text-[10px] text-slate-400 uppercase tracking-wide">{s.label}</p>
                <p className="text-sm font-bold text-slate-700 mt-0.5">{s.value}</p>
              </div>
            ))}
          </div>
        </Card>

        {/* Doctor notes */}
        <Card title="Doctor Notes">
          <textarea
            className="w-full text-sm text-slate-700 bg-transparent border-none
                       outline-none resize-none min-h-[80px] placeholder:text-slate-300"
            placeholder="Add doctor notes here before exporting…"
          />
        </Card>

        {/* PDF info banner */}
        <div className="flex items-start gap-3 bg-blue-50 border border-blue-200
                        rounded-xl px-4 py-3 text-sm text-blue-700">
          <FileText className="w-4 h-4 mt-0.5 shrink-0" />
          <span>
            The downloaded PDF includes <strong>BPM trend charts</strong>, 
            <strong> Blood Sugar</strong> and <strong>Blood Pressure</strong> line graphs
            drawn from stored session history, plus the full alert log and doctor notes.
            Select a session above and click <em>Download PDF</em>.
          </span>
        </div>
      </div>
    </div>
  );
}
