/**
 * LiveECG – Dedicated full-screen ECG monitoring page.
 * Larger canvas + detailed sidebar controls.
 * Includes a "Send Report" button that dispatches a WhatsApp status
 * message with live ECG values to the patient's guardian.
 */
import { useState } from 'react';
import { Send, Loader2, CheckCircle, XCircle } from 'lucide-react';
import ECGCanvas from '../components/ECGCanvas';
import AIAnalysisCard from '../components/AIAnalysisCard';
import AlertPanel from '../components/AlertPanel';
import Card from '../components/Card';
import StatRow from '../components/StatRow';
import { useApp } from '../context/AppContext';
import { sendWhatsAppReport } from '../services/api';

export default function LiveECG() {
  const { state } = useApp();
  const hr = state.heartRate;
  const d  = state.device;

  const [sending, setSending]   = useState(false);
  const [sendStatus, setSendStatus] = useState(null); // 'ok' | 'error' | null
  const [sendMsg, setSendMsg]   = useState('');

  const handleSendReport = async () => {
    setSending(true);
    setSendStatus(null);
    try {
      const patientId = state.patient.id;
      const res = await sendWhatsAppReport(patientId);
      setSendStatus('ok');
      setSendMsg(res.message ?? 'Report sent.');
    } catch (err) {
      setSendStatus('error');
      setSendMsg(err.message ?? 'Failed to send report.');
    } finally {
      setSending(false);
      setTimeout(() => setSendStatus(null), 4000);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Live ECG</h1>
          <p className="text-sm text-slate-400 mt-0.5">Full-screen real-time ECG waveform</p>
        </div>

        {/* Send Report button */}
        <div className="flex items-center gap-3">
          {sendStatus === 'ok' && (
            <span className="flex items-center gap-1.5 text-xs font-medium text-emerald-700
              bg-emerald-50 border border-emerald-200 px-3 py-1.5 rounded-lg">
              <CheckCircle className="w-3.5 h-3.5" /> {sendMsg}
            </span>
          )}
          {sendStatus === 'error' && (
            <span className="flex items-center gap-1.5 text-xs font-medium text-red-700
              bg-red-50 border border-red-200 px-3 py-1.5 rounded-lg">
              <XCircle className="w-3.5 h-3.5" /> {sendMsg}
            </span>
          )}
          <button
            onClick={handleSendReport}
            disabled={sending}
            className="flex items-center gap-2 px-4 py-2 text-sm font-semibold
              bg-emerald-600 text-white rounded-lg hover:bg-emerald-700
              active:scale-95 transition-all shadow-sm disabled:opacity-60"
          >
            {sending
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Sending…</>
              : <><Send className="w-4 h-4" /> Send WhatsApp Report</>
            }
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* ECG canvas — 3 cols */}
        <div className="lg:col-span-3 space-y-4">
          <Card title="ECG Waveform — Lead II" subtitle={`Sampling: ${d.samplingRate}`} noPad>
            <div className="p-4">
              <ECGCanvas />
            </div>
          </Card>

          {/* Heart rate chart (BPM history) */}
          <Card title="BPM History (last 60 readings)">
            <div className="flex items-end gap-0.5 h-16">
              {hr.history.slice(-60).map((v, i) => {
                const pct = ((v - 40) / 80) * 100;
                const color = v < 60 ? 'bg-amber-400' : v > 100 ? 'bg-red-400' : 'bg-emerald-400';
                return (
                  <div key={i} className="flex-1 flex items-end">
                    <div
                      className={`w-full rounded-sm ${color} transition-all duration-150`}
                      style={{ height: `${Math.max(4, pct)}%` }}
                    />
                  </div>
                );
              })}
            </div>
            <div className="flex justify-between text-[10px] text-slate-400 mt-1">
              <span>60 readings ago</span>
              <span>Now — {hr.current} BPM</span>
            </div>
          </Card>
        </div>

        {/* Right panel — 1 col */}
        <div className="space-y-4">
          {/* Vital signs */}
          <Card title="Vital Signs">
            <div className="flex flex-col items-center py-2">
              <div className="text-5xl font-bold text-slate-800 tabular-nums leading-none">
                {hr.current}
              </div>
              <p className="text-xs text-slate-400 mt-1">BPM</p>
              <span className={`mt-2 text-xs font-semibold px-3 py-1 rounded-full
                ${hr.status === 'Normal'      ? 'bg-emerald-50 text-emerald-700' :
                  hr.status === 'Tachycardia' ? 'bg-red-50 text-red-700'
                                              : 'bg-amber-50 text-amber-700'}`}>
                {hr.status}
              </span>
            </div>
            <div className="mt-3">
              <StatRow label="Min (session)"  value={hr.history.length ? `${Math.min(...hr.history)} BPM` : '—'} />
              <StatRow label="Max (session)"  value={hr.history.length ? `${Math.max(...hr.history)} BPM` : '—'} />
              <StatRow label="Avg (session)"
                value={hr.history.length
                  ? `${Math.round(hr.history.reduce((a, b) => a + b, 0) / hr.history.length)} BPM`
                  : '—'}
              />
              <StatRow label="Duration"       value={d.monitoringDuration} />
              <StatRow label="Signal Quality" value={`${d.signalQuality}%`} />
            </div>
          </Card>

          <AIAnalysisCard />
          <AlertPanel maxItems={3} />
        </div>
      </div>
    </div>
  );
}
