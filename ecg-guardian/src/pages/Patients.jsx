/**
 * Patients – Patient profile view with inline edit.
 *
 * Save flow:
 *  1. Client-side validation (required fields, age range, phone format)
 *  2. Build payload with ONLY the fields that changed (diff against original)
 *  3. PUT /patients/{id}  — backend receives only changed fields
 *  4. Backend response mapped through patientFromBackend() → SET_PATIENT dispatch
 *
 * Key fixes vs previous version:
 *  - toBackendPayload used `|| undefined` which silently dropped intentional
 *    empty-string clears.  Now we diff against the saved record and only send
 *    fields the user actually changed.
 *  - Error messages now surface real FastAPI detail (api.js was fixed separately).
 *  - Uses SET_PATIENT (full replace) not UPDATE_PATIENT (partial merge) after save
 *    so the displayed record always matches exactly what the DB stored.
 *  - Null-guards throughout so the page renders safely while patient loads.
 */

import { useState, useMemo } from 'react';
import { Save, Edit2, X, User, Phone, Stethoscope, AlertCircle, Loader2 } from 'lucide-react';
import Card from '../components/Card';
import PatientLocation from '../components/PatientLocation';
import { useApp, patientFromBackend } from '../context/AppContext';
import { updatePatient } from '../services/api';

// ── Validation ────────────────────────────────────────────

const E164_RE = /^\+?[1-9]\d{6,14}$/;

function validate(form) {
  const errors = {};

  if (!form.name?.trim())
    errors.name = 'Full name is required.';
  else if (form.name.trim().length < 2)
    errors.name = 'Name must be at least 2 characters.';

  const age = Number(form.age);
  if (form.age === '' || form.age === null || form.age === undefined)
    errors.age = 'Age is required.';
  else if (!Number.isInteger(age) || age < 0 || age > 150)
    errors.age = 'Age must be a whole number between 0 and 150.';

  if (!form.gender?.trim())
    errors.gender = 'Gender is required.';

  if (!form.bloodGroup?.trim())
    errors.bloodGroup = 'Blood group is required.';

  // Phone fields — only validate if non-empty
  const phones = {
    guardianPhone:   'Guardian phone',
    phone:           'Patient phone',
    emergencyContact:'Emergency contact',
    doctorPhone:     'Doctor phone',
    ambulancePhone:  'Ambulance number',
  };
  for (const [key, label] of Object.entries(phones)) {
    const val = form[key];
    if (val && val.trim() && !E164_RE.test(val.trim()))
      errors[key] = `${label}: enter a valid phone number (e.g. +91XXXXXXXXXX).`;
  }

  return errors;   // empty object = valid
}

// ── camelCase → snake_case (complete mapping) ─────────────
// Returns ONLY fields whose value changed vs the saved record,
// so the backend only writes what actually needs updating.
function buildPayload(form, saved) {
  const map = {
    name:              'name',
    age:               'age',
    gender:            'gender',
    bloodGroup:        'blood_group',
    height:            'height',
    weight:            'weight',
    guardianName:      'guardian_name',
    guardianPhone:     'guardian_phone',
    phone:             'phone',
    emergencyContact:  'emergency_contact',
    diseases:          'diseases',
    medications:       'medications',
    allergies:         'allergies',
    address:           'address',
    doctorPhone:       'doctor_phone',
    ambulancePhone:    'ambulance_phone',
  };

  const payload = {};
  for (const [camel, snake] of Object.entries(map)) {
    const newVal  = camel === 'age' ? Number(form[camel]) : (form[camel] ?? '');
    const savedVal = camel === 'age' ? Number(saved[camel]) : (saved[camel] ?? '');
    // Include field if the value changed — including clearing it to ''
    if (newVal !== savedVal) {
      // Send null for empty strings on nullable fields so DB stores NULL
      payload[snake] = (typeof newVal === 'string' && newVal.trim() === '')
        ? null
        : newVal;
    }
  }
  return payload;   // may be empty if nothing changed
}

// ── Component ─────────────────────────────────────────────

export default function Patients() {
  const { state, dispatch, refreshPatients } = useApp();
  const patient = state.patient;

  const [editing,  setEditing]  = useState(false);
  const [form,     setForm]     = useState({});
  const [errors,   setErrors]   = useState({});
  const [saving,   setSaving]   = useState(false);
  const [saveMsg,  setSaveMsg]  = useState('');   // '' | 'success' | error string

  // ── Handlers ────────────────────────────────────────────

  function startEdit() {
    setForm({ ...patient });   // copy current live values into draft
    setErrors({});
    setSaveMsg('');
    setEditing(true);
  }

  function cancelEdit() {
    setEditing(false);
    setErrors({});
    setSaveMsg('');
    setForm({});
  }

  async function handleSave() {
    // 1. Validate
    const errs = validate(form);
    if (Object.keys(errs).length > 0) {
      setErrors(errs);
      return;
    }

    // 2. Diff — only send fields that actually changed
    const payload = buildPayload(form, patient);
    if (Object.keys(payload).length === 0) {
      // Nothing changed — exit edit mode silently
      setEditing(false);
      return;
    }

    // 3. Send to backend
    setSaving(true);
    setSaveMsg('');
    try {
      const updated = await updatePatient(patient.id, payload);
      // 4. Map backend response → camelCase and replace context patient entirely
      const mapped = patientFromBackend(updated);
      dispatch({ type: 'SET_PATIENT', payload: mapped });

      // Also update the patient list entry so the selector/other views stay fresh
      dispatch({ type: 'ADD_PATIENT_TO_LIST', payload: updated });

      setEditing(false);
      setSaveMsg('success');
      setTimeout(() => setSaveMsg(''), 3000);
    } catch (err) {
      setSaveMsg(err.message || 'Save failed. Check your connection and try again.');
    } finally {
      setSaving(false);
    }
  }

  function setField(key, value) {
    setForm(f => ({ ...f, [key]: value }));
    // Clear the error for this field as soon as the user starts correcting it
    if (errors[key]) setErrors(e => { const c = { ...e }; delete c[key]; return c; });
  }

  // ── Field renderer ────────────────────────────────────

  function field(label, key, type = 'text', options = null) {
    const hasError = !!errors[key];
    const displayVal = editing ? (form[key] ?? '') : (patient?.[key] ?? '—');

    return (
      <div key={key} className="flex flex-col gap-1">
        <label className="text-xs font-medium text-slate-500">{label}</label>

        {editing ? (
          options ? (
            <select
              value={form[key] ?? ''}
              onChange={e => setField(key, e.target.value)}
              className={`w-full text-sm rounded-lg px-3 py-2 border bg-white text-slate-800
                focus:outline-none focus:ring-2 transition-colors
                ${hasError
                  ? 'border-red-400 focus:ring-red-300'
                  : 'border-slate-200 focus:ring-blue-400/40 focus:border-blue-400'}`}
            >
              <option value="">Select…</option>
              {options.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            <input
              type={type}
              value={form[key] ?? ''}
              onChange={e => setField(key, e.target.value)}
              className={`w-full text-sm rounded-lg px-3 py-2 border bg-white text-slate-800
                focus:outline-none focus:ring-2 transition-colors
                ${hasError
                  ? 'border-red-400 focus:ring-red-300'
                  : 'border-slate-200 focus:ring-blue-400/40 focus:border-blue-400'}`}
            />
          )
        ) : (
          <p className="text-sm font-semibold text-slate-800 py-1.5 min-h-[2rem]">
            {displayVal}
          </p>
        )}

        {hasError && (
          <p className="flex items-center gap-1 text-xs text-red-600 mt-0.5">
            <AlertCircle className="w-3 h-3 shrink-0" />
            {errors[key]}
          </p>
        )}
      </div>
    );
  }

  // ── Loading / empty state ────────────────────────────────

  if (state.patientLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-sm">Loading patient data…</span>
      </div>
    );
  }

  if (!patient) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-slate-400">
        <User className="w-10 h-10" />
        <p className="text-sm font-medium">No patient registered yet.</p>
        {state.patientError && (
          <p className="text-xs text-red-500">{state.patientError}</p>
        )}
        <button
          onClick={refreshPatients}
          className="text-xs text-blue-600 underline hover:text-blue-700"
        >
          Retry
        </button>
      </div>
    );
  }

  // ── Render ───────────────────────────────────────────────

  return (
    <div className="space-y-6">

      {/* ── Page header ──────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Patient</h1>
          <p className="text-sm text-slate-400 mt-0.5">Profile and medical information</p>
        </div>

        <div className="flex gap-2">
          {editing ? (
            <>
              <button
                onClick={cancelEdit}
                disabled={saving}
                className="flex items-center gap-1.5 text-sm text-slate-600 border border-slate-200
                           bg-white px-4 py-2 rounded-lg hover:bg-slate-50 transition-colors
                           disabled:opacity-50"
              >
                <X className="w-4 h-4" /> Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1.5 text-sm font-medium text-white bg-blue-600
                           px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-60"
              >
                {saving
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</>
                  : <><Save className="w-4 h-4" /> Save changes</>}
              </button>
            </>
          ) : (
            <button
              onClick={startEdit}
              className="flex items-center gap-1.5 text-sm font-medium text-blue-600
                         border border-blue-200 bg-blue-50 px-4 py-2 rounded-lg
                         hover:bg-blue-100 transition-colors"
            >
              <Edit2 className="w-4 h-4" /> Edit Patient
            </button>
          )}
        </div>
      </div>

      {/* ── Status banners ──────────────────────────────────── */}
      {saveMsg === 'success' && (
        <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200
                        text-emerald-700 text-sm font-medium px-4 py-2.5 rounded-lg">
          ✓ Patient information saved to database.
        </div>
      )}
      {saveMsg && saveMsg !== 'success' && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200
                        text-red-700 text-sm px-4 py-2.5 rounded-lg">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
          <span>{saveMsg}</span>
        </div>
      )}
      {Object.keys(errors).length > 0 && editing && (
        <div className="flex items-center gap-2 bg-amber-50 border border-amber-200
                        text-amber-700 text-sm px-4 py-2.5 rounded-lg">
          <AlertCircle className="w-4 h-4 shrink-0" />
          Please fix the highlighted fields before saving.
        </div>
      )}

      {/* ── Profile + forms ─────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">

        {/* ── Avatar / summary card ──────────────────────── */}
        <Card>
          <div className="flex flex-col items-center py-4 text-center">
            <div className="w-20 h-20 rounded-full bg-blue-100 flex items-center justify-center
                            text-blue-700 text-3xl font-bold mb-3 select-none">
              {patient.name?.charAt(0)?.toUpperCase() ?? '?'}
            </div>
            <p className="text-lg font-bold text-slate-800 leading-snug">{patient.name}</p>
            <p className="text-xs text-slate-400 mt-0.5">{patient.id}</p>

            <div className="flex gap-2 mt-3 flex-wrap justify-center">
              {patient.bloodGroup && (
                <span className="text-xs bg-blue-50 text-blue-700 border border-blue-200
                                 px-2 py-0.5 rounded-full font-medium">
                  {patient.bloodGroup}
                </span>
              )}
              {patient.gender && (
                <span className="text-xs bg-slate-100 text-slate-600 border border-slate-200
                                 px-2 py-0.5 rounded-full font-medium">
                  {patient.gender}
                </span>
              )}
              {patient.age && (
                <span className="text-xs bg-slate-100 text-slate-600 border border-slate-200
                                 px-2 py-0.5 rounded-full font-medium">
                  {patient.age} yrs
                </span>
              )}
            </div>

            <div className="w-full mt-4 space-y-2 text-left">
              {patient.guardianName && (
                <div className="flex items-center gap-2 text-sm text-slate-600
                                bg-slate-50 rounded-lg p-2.5">
                  <User className="w-4 h-4 text-slate-400 shrink-0" />
                  <span className="truncate">{patient.guardianName}</span>
                </div>
              )}
              {(patient.guardianPhone || patient.emergencyContact) && (
                <div className="flex items-center gap-2 text-sm text-slate-600
                                bg-slate-50 rounded-lg p-2.5">
                  <Phone className="w-4 h-4 text-slate-400 shrink-0" />
                  <span className="truncate">
                    {patient.guardianPhone || patient.emergencyContact}
                  </span>
                </div>
              )}
              {patient.doctorPhone && (
                <div className="flex items-center gap-2 text-sm text-slate-600
                                bg-slate-50 rounded-lg p-2.5">
                  <Stethoscope className="w-4 h-4 text-slate-400 shrink-0" />
                  <span className="truncate">{patient.doctorPhone}</span>
                </div>
              )}
            </div>
          </div>
        </Card>

        {/* ── Editable form sections ─────────────────────── */}
        <div className="md:col-span-2 space-y-4">

          <Card title="Patient Details">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {field('Full Name',             'name')}
              {field('Age (years)',           'age',         'number')}
              {field('Gender',               'gender',      'text',
                ['Male', 'Female', 'Other', 'Prefer not to say'])}
              {field('Blood Group',           'bloodGroup',  'text',
                ['A+', 'A−', 'B+', 'B−', 'AB+', 'AB−', 'O+', 'O−'])}
              {field('Height',                'height')}
              {field('Weight',                'weight')}
              {field('Diseases / Conditions', 'diseases')}
              {field('Current Medications',   'medications')}
              {field('Allergies',             'allergies')}
            </div>
          </Card>

          <Card
            title="Emergency Contacts"
            subtitle="Guardian and Doctor receive WhatsApp alerts"
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {field('Guardian Name',      'guardianName')}
              {field('Guardian Phone',     'guardianPhone',    'tel')}
              {field('Patient Phone',      'phone',            'tel')}
              {field('Emergency Contact',  'emergencyContact', 'tel')}
              {field('Doctor Phone',       'doctorPhone',      'tel')}
              {field('Ambulance Number',   'ambulancePhone',   'tel')}
            </div>
          </Card>

          <Card title="Address">
            <div className="grid grid-cols-1 gap-4">
              {field('Full Address', 'address')}
            </div>
          </Card>

        </div>
      </div>

      {/* ── Patient Location ────────────────────────────────── */}
      <Card title="Patient Location" subtitle="Included in emergency WhatsApp alerts">
        <PatientLocation />
      </Card>

    </div>
  );
}
