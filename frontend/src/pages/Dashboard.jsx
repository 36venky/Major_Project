/**
 * Dashboard – Main overview page.
 *
 * Page header (top bar):
 *   LEFT  – Patient avatar + name + ID + "Active Monitoring" badge
 *   RIGHT – "▶ Start / ■ Stop" button → POST /ecg/start or /ecg/stop
 *            Gates DB session opening behind an explicit user action.
 *            Hardware always streams to the live chart for signal preview.
 *            "📤 Send Status" button → POST /alerts/send-report
 *            Sends current BPM, rhythm, risk level, signal quality and
 *            location to all three contact numbers simultaneously.
 */
import { useState, useCallback } from 'react';
import {
  Send, Loader2, CheckCircle, XCircle,
  Activity, UserCircle2, BadgeCheck,
  Play, StopCircle,
} from 'lucide-react';
import PatientCard      from '../components/PatientCard';
import HeartRateCard    from '../components/HeartRateCard';
import LiveECGChart     from '../components/LiveECGChart';
import AIAnalysisCard   from '../components/AIAnalysisCard';
import RiskCard         from '../components/RiskCard';
import RiskChart        from '../components/RiskChart';
import Card             from '../components/Card';
import { useApp }       from '../context/AppContext';
import { apiPost }      from '../services/apiClient';

// ── Send-status result toast ──────────────────────────────
function SendToast({ result, onClose }) {
  if (!result) return null;

  const success = result.success;
  return (
    <div className={`flex items-start gap-3 px-4 py-3 rounded-xl border text-sm
      ${success
        ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
        : 'bg-red-50 border-red-200 text-red-800'
      }`}
    >
      {success
        ? <CheckCircle className="w-4 h-4 shrink-0 mt-0.5 text-emerald-600" />
        : <XCircle     className="w-4 h-4 shrink-0 mt-0.5 text-red-500" />
      }
      <div className="flex-1 min-w-0">
        <p className="font-semibold">{result.message}</p>
        {result.recipients?.length > 0 && (
          <ul className="mt-1 space-y-0.5">
            {result.recipients.map((r, i) => (
              <li key={i} className="text-xs flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0
                  ${r.status === 'sent' ? 'bg-emerald-500' : 'bg-red-400'}`}
                />
                <span className="capitalize font-medium">{r.role}</span>
                <span className="text-slate-500">·</span>
                <span className="font-mono">{r.phone}</span>
                <span className={r.status === 'sent' ? 'text-emerald-600' : 'text-red-500'}>
                  {r.status === 'sent' ? '✓ Sent' : '✗ Failed'}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <button
        onClick={onClose}
        className="text-slate-400 hover:text-slate-600 shrink-0 text-xs leading-none mt-0.5"
        title="Dismiss"
      >✕</button>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────
export default function Dashboard() {
  const { state, dispatch } = useApp();
  const patient = state.patient;

  // Send-status state
  const [sending,     setSending]     = useState(false);
  const [sendResult,  setSendResult]  = useState(null);   // null | { success, message, recipients }

  // Start/Stop recording state
  const [toggling,    setToggling]    = useState(false);  // request in-flight
  const isRecording = state.isRecording;
  const hardwareReady = state.device.hardwareConnected;

  // ── Start / Stop handler ──────────────────────────────
  const handleToggleRecording = useCallback(async () => {
    if (!patient?.id || toggling) return;
    setToggling(true);
    try {
      if (isRecording) {
        await apiPost('/ecg/stop', {});
        dispatch({ type: 'SET_RECORDING', payload: false });
      } else {
        await apiPost('/ecg/start', {});
        dispatch({ type: 'SET_RECORDING', payload: true });
      }
    } catch (err) {
      // Backend is source of truth — if the call fails the WS frame will
      // correct the state within the next broadcast tick, so just log it.
      console.warn('Toggle recording failed:', err.message);
    } finally {
      setToggling(false);
    }
  }, [patient?.id, toggling, isRecording, dispatch]);

  // ── Send status report ────────────────────────────────
  const handleSendStatus = useCallback(async () => {
    if (!patient?.id || sending) return;
    setSending(true);
    setSendResult(null);
    try {
      const res = await apiPost('/alerts/send-report', { patient_id: patient.id });
      setSendResult({
        success:    res.success,
        message:    res.message,
        recipients: res.recipients ?? [],
      });
    } catch (err) {
      setSendResult({
        success:    false,
        message:    err.message || 'Failed to send. Check backend and Twilio credentials.',
        recipients: [],
      });
    } finally {
      setSending(false);
    }
  }, [patient?.id, sending]);

  // ── Patient header data ───────────────────────────────
  const initials = patient?.name
    ? patient.name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
    : '?';

  const statusColor = state.device.connected
    ? state.device.hardwareConnected
      ? 'bg-emerald-500'   // real ESP32 live
      : 'bg-amber-400'     // backend connected, no hardware
    : 'bg-slate-300';      // backend offline

  // ── Start/Stop button appearance ─────────────────────
  const startStopDisabled = toggling || !patient?.id || !hardwareReady;
  const startStopTitle = !patient?.id
    ? 'Select a patient first'
    : !hardwareReady
    ? 'Connect ESP32 hardware first'
    : isRecording
    ? 'Stop recording and close the current session'
    : 'Start recording — open a new ECG session in the database';

  return (
    <div className="space-y-5">

      {/* ── Page header ──────────────────────────────── */}
      <div className="flex items-center justify-between gap-4 flex-wrap">

        {/* LEFT — patient identity block */}
        <div className="flex items-center gap-3">

          {/* Avatar with online dot */}
          <div className="relative shrink-0">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-700
                            flex items-center justify-center shadow-md shadow-blue-200">
              <span className="text-white font-bold text-base tracking-wide">{initials}</span>
            </div>
            {/* Live monitoring dot */}
            <span className={`absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 rounded-full
                              border-2 border-white ${statusColor}`}
            />
          </div>

          {/* Name + ID + badge */}
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-bold text-slate-800 leading-tight">
                {patient?.name ?? 'No Patient Selected'}
              </h1>
              {/* Recording badge — shown when session is active */}
              {isRecording && (
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold
                                 px-2 py-0.5 rounded-full bg-red-100 text-red-700
                                 border border-red-200 uppercase tracking-wide">
                  <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                  Recording
                </span>
              )}
              {/* Active monitoring badge — only when real hardware is connected */}
              {state.device.connected && state.device.hardwareConnected && !isRecording && (
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold
                                 px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700
                                 border border-emerald-200 uppercase tracking-wide">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Live Hardware
                </span>
              )}
              {/* Simulator badge — backend connected but no real ESP32 */}
              {state.device.connected && !state.device.hardwareConnected && (
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold
                                 px-2 py-0.5 rounded-full bg-slate-100 text-slate-500
                                 border border-slate-200 uppercase tracking-wide">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
                  Awaiting ESP32
                </span>
              )}
              {/* Offline badge — backend WS not reachable */}
              {!state.device.connected && (
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold
                                 px-2 py-0.5 rounded-full bg-slate-100 text-slate-500
                                 border border-slate-200 uppercase tracking-wide">
                  Offline
                </span>
              )}
            </div>
            {patient?.id
              ? (
                <p className="text-xs text-slate-400 mt-0.5 font-mono">
                  ID&nbsp;{patient.id}
                  {patient.age ? <span className="ml-2 not-italic font-sans text-slate-400">· {patient.age} yrs · {patient.gender}</span> : null}
                </p>
              )
              : (
                <p className="text-xs text-slate-400 mt-0.5">Register a patient to begin monitoring</p>
              )
            }
          </div>
        </div>

        {/* RIGHT — action buttons */}
        <div className="flex items-center gap-2 flex-wrap">

          {/* ── Start / Stop button ─────────────────── */}
          <button
            onClick={handleToggleRecording}
            disabled={startStopDisabled}
            title={startStopTitle}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold
              shadow-sm transition-all active:scale-95 select-none
              ${startStopDisabled
                ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                : isRecording
                ? 'bg-red-600 hover:bg-red-700 text-white shadow-red-200 cursor-pointer'
                : 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-emerald-200 cursor-pointer'
              }`}
          >
            {toggling
              ? <><Loader2 className="w-4 h-4 animate-spin" />{isRecording ? 'Stopping…' : 'Starting…'}</>
              : isRecording
              ? <><StopCircle className="w-4 h-4" /> Stop</>
              : <><Play       className="w-4 h-4" /> Start</>
            }
          </button>

          {/* ── Send Status button ───────────────────── */}
          <button
            onClick={handleSendStatus}
            disabled={sending || !patient?.id}
            title={
              !patient?.id
                ? 'Select a patient first'
                : 'Send current BPM, risk level, and location to all contacts via WhatsApp'
            }
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold
              shadow-sm transition-all active:scale-95 select-none
              ${sending || !patient?.id
                ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-700 text-white shadow-blue-200 cursor-pointer'
              }`}
          >
            {sending
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Sending…</>
              : <><Send    className="w-4 h-4" /> Send Status</>
            }
          </button>
        </div>
      </div>

      {/* ── Send-result toast (appears below header, auto-dismissed) ─ */}
      {sendResult && (
        <SendToast
          result={sendResult}
          onClose={() => setSendResult(null)}
        />
      )}

      {/* ── Live ECG waveform ─────────────────────────── */}
      <Card title="Live ECG Waveform" subtitle="Continuous monitoring — Lead II" noPad>
        <div className="p-4">
          <LiveECGChart windowSeconds={10} />
        </div>
      </Card>

      {/* Info cards — ROW 1: Patient Information, Heart Rate, Risk Prediction */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <PatientCard />
        <HeartRateCard />
        <RiskCard />
      </div>

      {/* ROW 2: Risk vs Day chart and AI Analysis */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <Card title="Risk vs Day" subtitle="Last 30 days — cardiac risk trend" noPad>
            <div className="px-2 pb-2">
              <RiskChart />
            </div>
          </Card>
        </div>
        <AIAnalysisCard />
      </div>

    </div>
  );
}
