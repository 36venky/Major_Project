/**
 * AddPatientModal – Professional patient registration form.
 * Posts to POST /patients. On success dispatches UPDATE_PATIENT + shows toast.
 */
import { useState } from 'react';
import { X, UserPlus, Loader2 } from 'lucide-react';
import { useApp } from '../context/AppContext';
import { getAuthHeaders } from '../services/auth';

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

const BLOOD_GROUPS  = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'];
const GENDERS       = ['Male', 'Female', 'Other'];

const INITIAL = {
  name: '', age: '', gender: 'Male', phone: '', emergency_contact: '',
  blood_group: 'B+', height: '', weight: '', diseases: '',
  medications: '', allergies: '', address: '',
};

function validate(f) {
  const errs = {};
  if (!f.name || f.name.trim().length < 2)   errs.name = 'Full name must be at least 2 characters.';
  const age = parseInt(f.age, 10);
  if (isNaN(age) || age < 0 || age > 150)    errs.age  = 'Age must be between 0 and 150.';
  if (!f.gender)                             errs.gender = 'Select a gender.';
  if (!f.blood_group)                        errs.blood_group = 'Select a blood group.';
  if (f.phone && !/^\+?\d{7,15}$/.test(f.phone.replace(/\s/g, '')))
    errs.phone = 'Enter a valid phone number (7–15 digits).';
  if (f.emergency_contact && !/^\+?\d{7,15}$/.test(f.emergency_contact.replace(/\s/g, '')))
    errs.emergency_contact = 'Enter a valid emergency contact number.';
  return errs;
}

export default function AddPatientModal({ onClose }) {
  const { dispatch } = useApp();
  const [fields, setFields]  = useState(INITIAL);
  const [errors, setErrors]  = useState({});
  const [loading, setLoading] = useState(false);
  const [serverErr, setServerErr] = useState('');

  const set = (k, v) => setFields(f => ({ ...f, [k]: v }));

  async function handleSubmit(e) {
    e.preventDefault();
    const errs = validate(fields);
    setErrors(errs);
    if (Object.keys(errs).length) return;

    setLoading(true);
    setServerErr('');

    const headers = await getAuthHeaders();

    try {
      const res = await fetch(`${API_BASE}/patients`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify({
          name:              fields.name.trim(),
          age:               parseInt(fields.age, 10),
          gender:            fields.gender,
          blood_group:       fields.blood_group,
          height:            fields.height || null,
          weight:            fields.weight || null,
          guardian_phone:    fields.emergency_contact || null,
          phone:             fields.phone || null,
          emergency_contact: fields.emergency_contact || null,
          diseases:          fields.diseases || null,
          medications:       fields.medications || null,
          allergies:         fields.allergies || null,
          address:           fields.address || null,
        }),
      });

      const body = await res.json();
      if (!res.ok) {
        setServerErr(body.message || body.detail || 'Failed to create patient.');
        setLoading(false);
        return;
      }

      // Update global patient list and show toast
      dispatch({ type: 'ADD_PATIENT_TO_LIST', payload: body });
      dispatch({
        type: 'ADD_NOTIFICATION',
        payload: {
          id:          `n-${Date.now()}`,
          title:       'Patient Registered',
          description: `Patient ID: ${body.patient_id}`,
          severity:    'info',
          time:        new Date().toISOString(),
        },
      });

      onClose();
    } catch (err) {
      setServerErr('Network error — please try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[92vh] flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center">
              <UserPlus className="w-4 h-4 text-blue-600" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-800">Add New Patient</h2>
              <p className="text-xs text-slate-400">Patient ID will be auto-generated</p>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="overflow-y-auto flex-1 px-6 py-5">
          {serverErr && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {serverErr}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Full Name */}
            <Field label="Full Name *" error={errors.name} colSpan>
              <input className={input(errors.name)} value={fields.name}
                onChange={e => set('name', e.target.value)} placeholder="e.g. Arjun Sharma" />
            </Field>

            {/* Age */}
            <Field label="Age *" error={errors.age}>
              <input className={input(errors.age)} type="number" min="0" max="150"
                value={fields.age} onChange={e => set('age', e.target.value)} placeholder="e.g. 45" />
            </Field>

            {/* Gender */}
            <Field label="Gender *" error={errors.gender}>
              <select className={input(errors.gender)} value={fields.gender}
                onChange={e => set('gender', e.target.value)}>
                {GENDERS.map(g => <option key={g}>{g}</option>)}
              </select>
            </Field>

            {/* Blood Group */}
            <Field label="Blood Group *" error={errors.blood_group}>
              <select className={input(errors.blood_group)} value={fields.blood_group}
                onChange={e => set('blood_group', e.target.value)}>
                {BLOOD_GROUPS.map(b => <option key={b}>{b}</option>)}
              </select>
            </Field>

            {/* Phone */}
            <Field label="Phone Number" error={errors.phone}>
              <input className={input(errors.phone)} value={fields.phone}
                onChange={e => set('phone', e.target.value)} placeholder="+91 98765 43210" />
            </Field>

            {/* Emergency Contact */}
            <Field label="Emergency Contact" error={errors.emergency_contact}>
              <input className={input(errors.emergency_contact)} value={fields.emergency_contact}
                onChange={e => set('emergency_contact', e.target.value)} placeholder="+91 98765 43210" />
            </Field>

            {/* Height */}
            <Field label="Height" error={errors.height}>
              <input className={input()} value={fields.height}
                onChange={e => set('height', e.target.value)} placeholder="e.g. 172 cm" />
            </Field>

            {/* Weight */}
            <Field label="Weight" error={errors.weight}>
              <input className={input()} value={fields.weight}
                onChange={e => set('weight', e.target.value)} placeholder="e.g. 74 kg" />
            </Field>

            {/* Existing Diseases */}
            <Field label="Existing Diseases" error={null} colSpan>
              <textarea rows={2} className={input() + ' resize-none'} value={fields.diseases}
                onChange={e => set('diseases', e.target.value)} placeholder="e.g. Diabetes, Hypertension" />
            </Field>

            {/* Medications */}
            <Field label="Current Medications" error={null} colSpan>
              <textarea rows={2} className={input() + ' resize-none'} value={fields.medications}
                onChange={e => set('medications', e.target.value)} placeholder="e.g. Metformin 500mg" />
            </Field>

            {/* Allergies */}
            <Field label="Allergies" error={null} colSpan>
              <input className={input()} value={fields.allergies}
                onChange={e => set('allergies', e.target.value)} placeholder="e.g. Penicillin, Pollen" />
            </Field>

            {/* Address */}
            <Field label="Address" error={null} colSpan>
              <textarea rows={2} className={input() + ' resize-none'} value={fields.address}
                onChange={e => set('address', e.target.value)} placeholder="Full address" />
            </Field>
          </div>
        </form>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-100 flex justify-end gap-3">
          <button type="button" onClick={onClose}
            className="px-4 py-2 text-sm text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={loading}
            className="flex items-center gap-2 px-5 py-2 text-sm font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-60 transition-colors"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {loading ? 'Registering…' : 'Register Patient'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────
function input(err) {
  return `w-full text-sm px-3 py-2 border rounded-lg outline-none focus:ring-2 transition-colors
    ${err
      ? 'border-red-300 focus:ring-red-200 bg-red-50'
      : 'border-slate-200 focus:ring-blue-100 focus:border-blue-400 bg-white'}`;
}

function Field({ label, error, children, colSpan = false }) {
  return (
    <div className={colSpan ? 'sm:col-span-2' : ''}>
      <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
      {children}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}
