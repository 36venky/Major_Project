/**
 * PatientSelector – Dropdown to switch the active monitored patient.
 * Fetches patient list from GET /patients and calls POST /patients/{id}/select.
 */
import { useEffect, useState, useCallback } from 'react';
import { ChevronDown, Loader2, RefreshCw } from 'lucide-react';
import { useApp } from '../context/AppContext';
import { getAuthHeaders } from '../services/auth';

const API_BASE = 'http://localhost:8000';

export default function PatientSelector() {
  const { state, dispatch } = useApp();
  const activeId = state.patient.id;

  const [patients,   setPatients]   = useState([]);
  const [switching,  setSwitching]  = useState(false);
  const [loading,    setLoading]    = useState(true);
  const [switchErr,  setSwitchErr]  = useState('');

  // ── Load patient list ─────────────────────────────────
  const loadPatients = useCallback(() => {
    setLoading(true);
    getAuthHeaders().then(headers => {
      fetch(`${API_BASE}/patients`, { headers })
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(data => {
          const list = Array.isArray(data) ? data : [];
          setPatients(list);
          // Sync patientList into global context so other components can use it
          dispatch({ type: 'SET_PATIENT_LIST', payload: list });
        })
        .catch(() => {})
        .finally(() => setLoading(false));
    });
  }, [dispatch]);

  // Load on mount
  useEffect(() => { loadPatients(); }, [loadPatients]);

  // Also reload when a new patient is added (patientList grows)
  useEffect(() => {
    if (state.patientList.length > patients.length) {
      setPatients(state.patientList);
    }
  }, [state.patientList]);

  // ── Switch patient ────────────────────────────────────
  async function handleChange(e) {
    const newId = e.target.value;
    if (!newId || newId === activeId) return;

    setSwitching(true);
    setSwitchErr('');

    try {
      const headers = await getAuthHeaders();

      const res = await fetch(`${API_BASE}/patients/${encodeURIComponent(newId)}/select`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...headers },
        body:    '{}',   // empty JSON body — FastAPI needs this for POST
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setSwitchErr(body.detail || body.message || `Server error ${res.status}`);
        setSwitching(false);
        return;
      }

      // Update global patient state immediately
      const selected = patients.find(p => p.patient_id === newId);
      if (selected) {
        dispatch({
          type: 'UPDATE_PATIENT',
          payload: {
            id:               selected.patient_id,
            name:             selected.name,
            age:              selected.age,
            gender:           selected.gender,
            bloodGroup:       selected.blood_group,
            height:           selected.height   || '—',
            weight:           selected.weight   || '—',
            guardianName:     selected.guardian_name  || '—',
            emergencyContact: selected.guardian_phone || selected.emergency_contact || '—',
          },
        });
        dispatch({
          type: 'ADD_NOTIFICATION',
          payload: {
            id:          `sw-${Date.now()}`,
            title:       'Patient Switched',
            description: `Now monitoring: ${selected.name}`,
            severity:    'info',
            time:        new Date().toISOString(),
          },
        });
      }
    } catch (err) {
      console.error('Patient switch error:', err);
      setSwitchErr('Could not reach server. Is the backend running?');
    }

    setSwitching(false);
  }

  // ── Render ────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-400 border border-slate-200 rounded-lg px-3 py-2 bg-slate-50">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        <span>Loading patients…</span>
      </div>
    );
  }

  if (patients.length === 0) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-400 border border-slate-200 rounded-lg px-3 py-2 bg-slate-50">
        <span>No patients registered</span>
        <button onClick={loadPatients} title="Retry" className="ml-1 text-slate-400 hover:text-slate-600">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="relative flex items-center">
        {switching && (
          <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin absolute left-2.5 z-10" />
        )}
        <select
          value={activeId}
          onChange={handleChange}
          disabled={switching}
          className={`appearance-none text-sm border rounded-lg py-2 pr-8 bg-white text-slate-700
            focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400
            disabled:opacity-60 cursor-pointer transition-colors
            ${switching ? 'pl-8' : 'pl-3'}
            ${switchErr ? 'border-red-300' : 'border-slate-200'}`}
        >
          {patients.map(p => (
            <option key={p.patient_id} value={p.patient_id}>
              {p.name}  —  {p.patient_id}
            </option>
          ))}
        </select>
        <ChevronDown className="w-4 h-4 text-slate-400 absolute right-2.5 pointer-events-none" />
      </div>

      {switchErr && (
        <p className="text-xs text-red-500 px-1">{switchErr}</p>
      )}
    </div>
  );
}
