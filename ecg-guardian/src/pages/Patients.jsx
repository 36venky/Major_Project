/**
 * Patients – Patient profile view with editable information.
 * Edits are persisted to the backend via PUT /patients/{id}.
 *
 * toBackendPayload  – complete camelCase → snake_case mapping
 * fromBackend       – maps confirmed backend response back to context
 */
import { useState } from 'react';
import { Save, User, Phone, Loader2, Stethoscope } from 'lucide-react';
import Card from '../components/Card';
import PatientLocation from '../components/PatientLocation';
import { useApp } from '../context/AppContext';
import { updatePatient } from '../services/api';

export default function Patients() {
  const { state, dispatch } = useApp();
  const [editing, setEditing] = useState(false);
  const [form,    setForm]    = useState({ ...state.patient });
  const [saved,   setSaved]   = useState(false);
  const [saving,  setSaving]  = useState(false);
  const [error,   setError]   = useState('');

  // ── camelCase → snake_case (complete, no missing fields) ──
  const toBackendPayload = (f) => ({
    name:              f.name              || undefined,
    age:               Number(f.age)       || undefined,
    gender:            f.gender            || undefined,
    blood_group:       f.bloodGroup        || undefined,
    height:            f.height            || undefined,
    weight:            f.weight            || undefined,
    guardian_name:     f.guardianName      || undefined,
    guardian_phone:    f.guardianPhone     || undefined,
    phone:             f.phone             || undefined,
    emergency_contact: f.emergencyContact  || undefined,
    diseases:          f.diseases          || undefined,
    medications:       f.medications       || undefined,
    allergies:         f.allergies         || undefined,
    address:           f.address           || undefined,
    doctor_phone:      f.doctorPhone       || undefined,
    ambulance_phone:   f.ambulancePhone    || undefined,
  });

  // ── snake_case backend response → camelCase frontend state ─
  const fromBackend = (b) => ({
    id:               b.patient_id,
    name:             b.name,
    age:              b.age,
    gender:           b.gender,
    bloodGroup:       b.blood_group,
    height:           b.height,
    weight:           b.weight,
    guardianName:     b.guardian_name,
    guardianPhone:    b.guardian_phone,
    phone:            b.phone,
    emergencyContact: b.emergency_contact,
    diseases:         b.diseases,
    medications:      b.medications,
    allergies:        b.allergies,
    address:          b.address,
    doctorPhone:      b.doctor_phone,
    ambulancePhone:   b.ambulance_phone,
  });

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      const patientId = state.patient.id;
      const updated   = await updatePatient(patientId, toBackendPayload(form));
      // Sync context with what the backend actually stored
      const mapped = fromBackend(updated);
      dispatch({ type: 'UPDATE_PATIENT', payload: mapped });
      setForm(mapped);
      setEditing(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setError(`Save failed: ${err.message}. Check backend connection.`);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setEditing(false);
    setError('');
    setForm({ ...state.patient });
  };

  // Generic field renderer
  const field = (label, key, type = 'text') => (
    <div key={key}>
      <label className="text-xs text-slate-500 font-medium block mb-1">{label}</label>
      {editing ? (
        <input
          type={type}
          value={form[key] ?? ''}
          onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
          className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 text-slate-800
                     focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400"
        />
      ) : (
        <p className="text-sm font-semibold text-slate-800 py-2">
          {state.patient[key] || '—'}
        </p>
      )}
    </div>
  );

  return (
    <div className="space-y-6">

      {/* ── Page header ──────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Patients</h1>
          <p className="text-sm text-slate-400 mt-0.5">Patient profile and information</p>
        </div>
        <div className="flex gap-2">
          {editing ? (
            <>
              <button
                onClick={handleCancel}
                disabled={saving}
                className="text-sm text-slate-600 border border-slate-200 bg-white px-4 py-2
                           rounded-lg hover:bg-slate-50 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1.5 text-sm font-medium text-white bg-blue-600
                           px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-60"
              >
                {saving
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</>
                  : <><Save className="w-4 h-4" /> Save</>}
              </button>
            </>
          ) : (
            <button
              onClick={() => { setEditing(true); setForm({ ...state.patient }); }}
              className="text-sm font-medium text-blue-600 border border-blue-200 bg-blue-50
                         px-4 py-2 rounded-lg hover:bg-blue-100 transition-colors"
            >
              Edit Patient
            </button>
          )}
        </div>
      </div>

      {/* ── Status banners ───────────────────────────── */}
      {saved && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 text-sm
                        font-medium px-4 py-2.5 rounded-lg">
          ✓ Patient information saved to database.
        </div>
      )}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm
                        font-medium px-4 py-2.5 rounded-lg">
          {error}
        </div>
      )}

      {/* ── Profile + forms ──────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

        {/* Avatar / summary card */}
        <Card>
          <div className="flex flex-col items-center py-4">
            <div className="w-20 h-20 rounded-full bg-blue-100 flex items-center justify-center
                            text-blue-700 text-3xl font-bold mb-3">
              {state.patient.name?.charAt(0) ?? '?'}
            </div>
            <p className="text-lg font-bold text-slate-800">{state.patient.name}</p>
            <p className="text-sm text-slate-400">{state.patient.id}</p>
            <div className="flex gap-2 mt-3">
              <span className="text-xs bg-blue-50 text-blue-700 border border-blue-200
                               px-2 py-0.5 rounded-full font-medium">
                {state.patient.bloodGroup}
              </span>
              <span className="text-xs bg-slate-100 text-slate-600 border border-slate-200
                               px-2 py-0.5 rounded-full font-medium">
                {state.patient.gender}
              </span>
            </div>
            <div className="w-full mt-4 space-y-2">
              <div className="flex items-center gap-2 text-sm text-slate-600 bg-slate-50 rounded-lg p-2.5">
                <User  className="w-4 h-4 text-slate-400" />
                <span>{state.patient.guardianName || '—'}</span>
              </div>
              <div className="flex items-center gap-2 text-sm text-slate-600 bg-slate-50 rounded-lg p-2.5">
                <Phone className="w-4 h-4 text-slate-400" />
                <span>{state.patient.guardianPhone || state.patient.emergencyContact || '—'}</span>
              </div>
              {state.patient.doctorPhone && (
                <div className="flex items-center gap-2 text-sm text-slate-600 bg-slate-50 rounded-lg p-2.5">
                  <Stethoscope className="w-4 h-4 text-slate-400" />
                  <span>{state.patient.doctorPhone}</span>
                </div>
              )}
            </div>
          </div>
        </Card>

        {/* Editable forms — 2/3 width */}
        <div className="md:col-span-2 space-y-4">

          <Card title="Patient Details">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {field('Full Name',            'name')}
              {field('Age (years)',          'age',         'number')}
              {field('Gender',               'gender')}
              {field('Blood Group',          'bloodGroup')}
              {field('Height',               'height')}
              {field('Weight',               'weight')}
              {field('Diseases / Conditions','diseases')}
              {field('Current Medications',  'medications')}
              {field('Allergies',            'allergies')}
            </div>
          </Card>

          <Card title="Emergency Contacts" subtitle="All numbers receive WhatsApp alerts">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {field('Guardian Name',     'guardianName')}
              {field('Guardian Phone',    'guardianPhone',    'tel')}
              {field('Emergency Contact', 'emergencyContact', 'tel')}
              {field('Doctor Phone',      'doctorPhone',      'tel')}
              {field('Ambulance Number',  'ambulancePhone',   'tel')}
            </div>
          </Card>

        </div>
      </div>

      {/* ── Patient Location ─────────────────────────── */}
      <Card title="Patient Location" subtitle="Included in emergency WhatsApp alerts">
        <PatientLocation />
      </Card>

    </div>
  );
}
