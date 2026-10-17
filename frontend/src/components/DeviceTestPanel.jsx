/**
 * DeviceTestPanel – shown when the ESP32 hardware is disconnected.
 *
 * Buttons:
 *   Show Sample Waveform  – clears ECG buffer so simulator replays a clean normal waveform
 *   Test Alert System     – injects PVC anomaly + fires backend alert pipeline
 */
import { useState } from 'react';
import { Activity, BellRing, Loader2, CheckCircle, XCircle, WifiOff } from 'lucide-react';
import { useApp } from '../context/AppContext';
import { apiPost } from '../services/apiClient';

/** Generate one PVC (premature ventricular contraction) sample at time t */
function pvcSample(t) {
  const cycle = (t % 1.12) / 1.12;   // longer cycle = compensatory pause
  let v = 0.015 * Math.sin(2 * Math.PI * 0.15 * t);
  if (cycle > 0.10 && cycle < 0.30) v += 1.6  * Math.sin(Math.PI * (cycle - 0.10) / 0.20);
  if (cycle > 0.30 && cycle < 0.40) v -= 0.55 * Math.sin(Math.PI * (cycle - 0.30) / 0.10);
  if (cycle > 0.60 && cycle < 0.80) v -= 0.35 * Math.sin(Math.PI * (cycle - 0.60) / 0.20);
  v += (Math.random() * 2 - 1) * 0.018;
  return parseFloat(v.toFixed(4));
}

export default function DeviceTestPanel({ onSampleWaveform }) {
  const { state, dispatch } = useApp();
  const [testing,     setTesting]     = useState(false);
  const [alertStatus, setAlertStatus] = useState(null); // 'ok'|'error'|null
  const [alertMsg,    setAlertMsg]    = useState('');

  const patientId = state.patient?.id;   // null when no patient selected — button disabled below

  const handleSampleWaveform = () => {
    dispatch({ type: 'SET_ECG_DATA',   payload: [] });
    dispatch({ type: 'SET_HEART_RATE', payload: 72 });
    if (onSampleWaveform) onSampleWaveform();
  };

  const handleTestAlert = async () => {
    if (!patientId) {
      setAlertStatus('error');
      setAlertMsg('No patient selected. Select or register a patient first.');
      return;
    }
    setTesting(true);
    setAlertStatus(null);

    // Inject PVC waveform locally for visual effect
    const batch = [];
    let t = 0;
    for (let i = 0; i < 500; i++) {
      t += 0.004;
      batch.push({ time: Date.now() + i * 4, value: pvcSample(t) });
    }
    dispatch({ type: 'APPEND_ECG',     payload: batch });
    dispatch({ type: 'SET_HEART_RATE', payload: 165 });
    setTimeout(() => dispatch({ type: 'SET_HEART_RATE', payload: 74 }), 5000);

    // Fire real backend alert pipeline
    try {
      const res = await apiPost('/ecg/test-alert', { patient_id: patientId });
      setAlertStatus('ok');
      setAlertMsg(res.message || 'Alert triggered successfully.');
    } catch (err) {
      setAlertStatus('error');
      setAlertMsg(err.message || 'Backend unreachable — waveform injected locally only.');
    } finally {
      setTesting(false);
      setTimeout(() => setAlertStatus(null), 5000);
    }
  };

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-amber-100 flex items-center justify-center">
          <WifiOff className="w-4 h-4 text-amber-600" />
        </div>
        <div>
          <p className="text-sm font-semibold text-amber-800">Hardware Disconnected</p>
          <p className="text-xs text-amber-600">ESP32 not connected — simulator active</p>
        </div>
        <span className="ml-auto flex items-center gap-1 text-xs font-medium
                         bg-amber-100 text-amber-700 border border-amber-200 px-2 py-1 rounded-full">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
          Simulated
        </span>
      </div>

      {/* Buttons */}
      <div className="flex flex-col sm:flex-row gap-2">
        <button onClick={handleSampleWaveform}
          className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5
                     text-sm font-semibold bg-blue-600 text-white rounded-xl
                     hover:bg-blue-700 active:scale-95 transition-all shadow-sm">
          <Activity className="w-4 h-4" />
          Show Sample Waveform
        </button>
        <button onClick={handleTestAlert} disabled={testing || !patientId}
          className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5
                     text-sm font-semibold bg-red-600 text-white rounded-xl
                     hover:bg-red-700 active:scale-95 transition-all shadow-sm disabled:opacity-60">
          {testing
            ? <><Loader2 className="w-4 h-4 animate-spin" />Triggering…</>
            : !patientId
              ? <><BellRing className="w-4 h-4" />No Patient</>
              : <><BellRing className="w-4 h-4" />Test Alert System</>
          }
        </button>
      </div>

      {/* Status feedback */}
      {alertStatus === 'ok' && (
        <div className="flex items-start gap-2 p-3 bg-emerald-50 border border-emerald-200
                        rounded-xl text-xs text-emerald-700">
          <CheckCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">Alert system triggered</p>
            <p className="mt-0.5">{alertMsg}</p>
            <p className="mt-0.5 text-emerald-500">Check the Alerts tab and WhatsApp.</p>
          </div>
        </div>
      )}
      {alertStatus === 'error' && (
        <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200
                        rounded-xl text-xs text-red-700">
          <XCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">Backend unreachable</p>
            <p className="mt-0.5">{alertMsg}</p>
          </div>
        </div>
      )}

      <p className="text-xs text-amber-700">
        <span className="font-semibold">Sample Waveform</span> — resets to a clean 75 BPM ECG.&nbsp;
        <span className="font-semibold">Test Alert</span> — injects a PVC anomaly and fires the
        WhatsApp alert pipeline (requires doctor/admin role on backend).
      </p>
    </div>
  );
}
