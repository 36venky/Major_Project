/**
 * Reports – Generates a downloadable patient monitoring report.
 * PDF export uses the browser print dialog.
 */
import { FileText, Download, Printer } from 'lucide-react';
import Card from '../components/Card';
import StatRow from '../components/StatRow';
import { useApp } from '../context/AppContext';
import { formatDateTime } from '../utils/helpers';
import { MOCK_HISTORY } from '../services/api';

export default function Reports() {
  const { state } = useApp();
  const p  = state.patient;
  const wh = state.weeklyHealth;
  const hr = state.heartRate;

  const handlePrint = () => window.print();

  const allEvents = MOCK_HISTORY.flatMap(s => s.events);
  const uniqueEvents = [...new Set(allEvents)];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Reports</h1>
          <p className="text-sm text-slate-400 mt-0.5">Generate and export monitoring summaries</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handlePrint}
            className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 transition-colors"
          >
            <Printer className="w-4 h-4" />
            Print / PDF
          </button>
          <button
            onClick={handlePrint}
            className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
          >
            <Download className="w-4 h-4" />
            Export PDF
          </button>
        </div>
      </div>

      {/* Report body */}
      <div id="report-content" className="space-y-4">
        {/* Header */}
        <div className="bg-blue-700 text-white rounded-xl p-6">
          <div className="flex items-center gap-3 mb-1">
            <FileText className="w-6 h-6" />
            <h2 className="text-lg font-bold">ECG Guardian — Patient Report</h2>
          </div>
          <p className="text-blue-200 text-sm">Generated: {formatDateTime(new Date().toISOString())}</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Patient info */}
          <Card title="Patient Information">
            <StatRow label="Name"             value={p.name} />
            <StatRow label="Patient ID"       value={p.id} />
            <StatRow label="Age"              value={`${p.age} years`} />
            <StatRow label="Gender"           value={p.gender} />
            <StatRow label="Blood Group"      value={p.bloodGroup} />
            <StatRow label="Height"           value={p.height} />
            <StatRow label="Weight"           value={p.weight} />
            <StatRow label="Guardian"         value={p.guardianName} />
            <StatRow label="Emergency Contact" value={p.emergencyContact} />
          </Card>

          {/* Monitoring summary */}
          <Card title="Monitoring Summary">
            <StatRow label="Current BPM"      value={`${hr.current} BPM`} />
            <StatRow label="Status"           value={hr.status} />
            <StatRow label="Avg BPM (history)"
              value={hr.history.length
                ? `${Math.round(hr.history.reduce((a, b) => a + b, 0) / hr.history.length)} BPM`
                : '—'
              }
            />
            <StatRow label="Max BPM"
              value={hr.history.length ? `${Math.max(...hr.history)} BPM` : '—'}
            />
            <StatRow label="Min BPM"
              value={hr.history.length ? `${Math.min(...hr.history)} BPM` : '—'}
            />
            <StatRow label="Blood Pressure"   value={wh.bloodPressure} />
            <StatRow label="Blood Sugar"      value={wh.bloodSugar} />
            <StatRow label="Last Health Update" value={formatDateTime(wh.lastUpdated)} />
          </Card>
        </div>

        {/* Detected events */}
        <Card title="Detected Events">
          {uniqueEvents.length === 0 ? (
            <p className="text-sm text-slate-400">No events detected.</p>
          ) : (
            <ul className="space-y-2">
              {uniqueEvents.map((ev, i) => (
                <li key={i} className="flex items-center gap-2 text-sm text-slate-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-500 shrink-0" />
                  {ev}
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Doctor notes */}
        <Card title="Doctor Notes">
          <textarea
            className="w-full text-sm text-slate-700 bg-transparent border-none outline-none resize-none min-h-[80px] placeholder:text-slate-300"
            placeholder="Add doctor notes here before exporting..."
          />
        </Card>

        {/* AI Analysis summary */}
        <Card title="AI Analysis Summary">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'Rhythm',        value: state.aiAnalysis.rhythm },
              { label: 'Confidence',    value: `${state.aiAnalysis.confidence}%` },
              { label: 'Risk Level',    value: state.aiAnalysis.riskLevel },
              { label: 'Signal Quality',value: state.aiAnalysis.signalQuality },
            ].map(s => (
              <div key={s.label} className="p-3 bg-slate-50 rounded-lg text-center border border-slate-100">
                <p className="text-[10px] text-slate-400 uppercase tracking-wide">{s.label}</p>
                <p className="text-sm font-bold text-slate-700 mt-0.5">{s.value}</p>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
