/**
 * Settings – App configuration: health update form, alert thresholds, notifications, device.
 */
import { useState } from 'react';
import { Save, Bell, Sliders, Cpu, User, Droplets, Activity } from 'lucide-react';
import Card from '../components/Card';
import { useApp } from '../context/AppContext';

/* ── Reusable input ─────────────────────────────────────── */
function Field({ label, value, onChange, type = 'text', unit, help }) {
  return (
    <div>
      <label className="text-xs text-slate-500 font-medium block mb-1">{label}</label>
      <div className="flex items-center gap-2">
        <input
          type={type}
          value={value}
          onChange={e => onChange(e.target.value)}
          className="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400"
        />
        {unit && <span className="text-xs text-slate-400 shrink-0">{unit}</span>}
      </div>
      {help && <p className="text-[10px] text-slate-400 mt-1">{help}</p>}
    </div>
  );
}

/* ── Toggle ─────────────────────────────────────────────── */
function Toggle({ checked, onChange }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={`relative w-10 h-5.5 rounded-full transition-colors ${checked ? 'bg-blue-600' : 'bg-slate-300'}`}
      style={{ height: 22 }}
    >
      <span
        className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${checked ? 'translate-x-5' : 'translate-x-0.5'}`}
      />
    </button>
  );
}

export default function Settings() {
  const { state, dispatch, addTimelineEvent } = useApp();
  const [healthForm, setHealthForm] = useState({
    bloodPressure: state.weeklyHealth.bloodPressure,
    bloodSugar:    state.weeklyHealth.bloodSugar,
    weight:        state.patient.weight,
    updatedBy:     'Guardian',
    notes:         '',
  });
  const [thresholds, setThresholds] = useState({ hrHigh: 100, hrLow: 60 });
  const [notifPrefs, setNotifPrefs] = useState({
    highHR: true, lowHR: true, irregularRhythm: true, poorSignal: true, deviceDisconnect: true,
  });
  const [savedHealth, setSavedHealth] = useState(false);
  const [savedThresholds, setSavedThresholds] = useState(false);

  const handleHealthSave = () => {
    dispatch({
      type: 'UPDATE_WEEKLY_HEALTH',
      payload: { bloodPressure: healthForm.bloodPressure, bloodSugar: healthForm.bloodSugar },
    });
    dispatch({ type: 'UPDATE_PATIENT', payload: { weight: healthForm.weight } });
    addTimelineEvent({
      event: `${healthForm.updatedBy} updated health values`,
      icon: 'edit',
      color: 'purple',
    });
    setSavedHealth(true);
    setTimeout(() => setSavedHealth(false), 2500);
  };

  const handleThresholdSave = () => {
    setSavedThresholds(true);
    setTimeout(() => setSavedThresholds(false), 2500);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-800">Settings</h1>
        <p className="text-sm text-slate-400 mt-0.5">Configure monitoring preferences and health data</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Manual Health Update */}
        <Card
          title="Manual Health Update"
          subtitle="Update blood pressure, sugar, and weight"
          action={<Droplets className="w-4 h-4 text-slate-400" />}
        >
          {savedHealth && (
            <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium px-3 py-2 rounded-lg mb-4 animate-slide-in">
              ✓ Health values updated successfully.
            </div>
          )}
          <div className="space-y-3">
            <Field
              label="Blood Pressure"
              value={healthForm.bloodPressure}
              onChange={v => setHealthForm(f => ({ ...f, bloodPressure: v }))}
              unit="mmHg"
              help="Format: 120/80 mmHg"
            />
            <Field
              label="Blood Sugar"
              value={healthForm.bloodSugar}
              onChange={v => setHealthForm(f => ({ ...f, bloodSugar: v }))}
              unit="mg/dL"
            />
            <Field
              label="Weight"
              value={healthForm.weight}
              onChange={v => setHealthForm(f => ({ ...f, weight: v }))}
            />
            <div>
              <label className="text-xs text-slate-500 font-medium block mb-1">Updated By</label>
              <select
                value={healthForm.updatedBy}
                onChange={e => setHealthForm(f => ({ ...f, updatedBy: e.target.value }))}
                className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              >
                <option>Guardian</option>
                <option>Patient</option>
                <option>Doctor</option>
                <option>Nurse</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-500 font-medium block mb-1">Notes</label>
              <textarea
                value={healthForm.notes}
                onChange={e => setHealthForm(f => ({ ...f, notes: e.target.value }))}
                placeholder="Optional notes..."
                rows={2}
                className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/30 resize-none"
              />
            </div>
            <button
              onClick={handleHealthSave}
              className="flex items-center gap-1.5 w-full justify-center text-sm font-medium text-white bg-blue-600 px-4 py-2.5 rounded-lg hover:bg-blue-700 transition-colors"
            >
              <Save className="w-4 h-4" />
              Save Health Data
            </button>
          </div>
        </Card>

        {/* Alert Thresholds */}
        <Card
          title="Alert Thresholds"
          subtitle="Trigger alerts when values exceed limits"
          action={<Sliders className="w-4 h-4 text-slate-400" />}
        >
          {savedThresholds && (
            <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-medium px-3 py-2 rounded-lg mb-4 animate-slide-in">
              ✓ Thresholds saved.
            </div>
          )}
          <div className="space-y-3">
            <Field
              label="High Heart Rate Threshold"
              value={thresholds.hrHigh}
              onChange={v => setThresholds(t => ({ ...t, hrHigh: Number(v) }))}
              type="number"
              unit="BPM"
              help="Alert triggers when BPM exceeds this value"
            />
            <Field
              label="Low Heart Rate Threshold"
              value={thresholds.hrLow}
              onChange={v => setThresholds(t => ({ ...t, hrLow: Number(v) }))}
              type="number"
              unit="BPM"
              help="Alert triggers when BPM drops below this value"
            />
            <button
              onClick={handleThresholdSave}
              className="flex items-center gap-1.5 w-full justify-center text-sm font-medium text-white bg-blue-600 px-4 py-2.5 rounded-lg hover:bg-blue-700 transition-colors"
            >
              <Save className="w-4 h-4" />
              Save Thresholds
            </button>
          </div>
        </Card>

        {/* Notification Preferences */}
        <Card
          title="Notification Preferences"
          subtitle="Choose which events trigger notifications"
          action={<Bell className="w-4 h-4 text-slate-400" />}
        >
          <div className="space-y-3">
            {Object.entries(notifPrefs).map(([key, val]) => {
              const labels = {
                highHR: 'High Heart Rate',
                lowHR: 'Low Heart Rate',
                irregularRhythm: 'Irregular Rhythm',
                poorSignal: 'Poor Signal Quality',
                deviceDisconnect: 'Device Disconnected',
              };
              return (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-sm text-slate-700">{labels[key]}</span>
                  <Toggle checked={val} onChange={v => setNotifPrefs(p => ({ ...p, [key]: v }))} />
                </div>
              );
            })}
          </div>
        </Card>

        {/* Device Configuration */}
        <Card
          title="Device Configuration"
          subtitle="COM port and sampling settings"
          action={<Cpu className="w-4 h-4 text-slate-400" />}
        >
          <div className="space-y-3">
            <div>
              <label className="text-xs text-slate-500 font-medium block mb-1">COM Port</label>
              <select className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/30">
                <option>COM6</option>
                <option>COM3</option>
                <option>COM4</option>
                <option>COM5</option>
              </select>
              <p className="text-[10px] text-slate-400 mt-1">Port is managed by the Python backend</p>
            </div>
            <div>
              <label className="text-xs text-slate-500 font-medium block mb-1">Sampling Rate</label>
              <select className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/30">
                <option>250 Hz</option>
                <option>500 Hz</option>
                <option>1000 Hz</option>
              </select>
            </div>
            <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg">
              <p className="text-xs text-amber-700 font-medium">⚠ Device settings are controlled by the FastAPI backend. Changes here are UI preferences only.</p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
