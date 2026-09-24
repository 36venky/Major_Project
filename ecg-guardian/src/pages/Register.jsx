/**
 * Register.jsx – 6-step onboarding wizard for ECG Guardian.
 *
 * Step 1 → Account          (full name, email, password, role)
 * Step 2 → Patient          (patient name, DOB, gender, blood group, phone, notes)
 * Step 3 → Emergency Contacts (guardian, doctor, ambulance)
 * Step 4 → Medical Info     (conditions, allergies, medications, history)
 * Step 5 → Location         (address search / map click / current location)
 * Step 6 → Review & Submit
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Heart, User, Users, Stethoscope, MapPin, CheckCircle,
  Eye, EyeOff, Loader2, AlertCircle, ChevronLeft,
  ChevronRight, Phone, Navigation, Search,
  Check, Edit2, ExternalLink, ArrowRight,
} from 'lucide-react';
import { MapContainer, TileLayer, Marker, useMapEvents, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { registerUser, loginWithCredentials } from '../services/auth';
import { apiPost } from '../services/apiClient';
import { useApp } from '../context/AppContext';

// Fix Leaflet default marker icon (broken by Vite's asset pipeline)
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: new URL('leaflet/dist/images/marker-icon-2x.png', import.meta.url).href,
  iconUrl:       new URL('leaflet/dist/images/marker-icon.png',    import.meta.url).href,
  shadowUrl:     new URL('leaflet/dist/images/marker-shadow.png',  import.meta.url).href,
});

// ── Constants ─────────────────────────────────────────────
const BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'O+', 'O-', 'AB+', 'AB-'];
const GENDERS      = ['Male', 'Female', 'Other', 'Prefer not to say'];
const ROLES        = [
  { value: 'guardian', label: 'Guardian / Family Member' },
  { value: 'doctor',   label: 'Doctor / Medical Professional' },
  { value: 'admin',    label: 'Administrator' },
];

const STEPS = [
  { id: 1, label: 'Account',   icon: User },
  { id: 2, label: 'Patient',   icon: Heart },
  { id: 3, label: 'Contacts',  icon: Users },
  { id: 4, label: 'Medical',   icon: Stethoscope },
  { id: 5, label: 'Location',  icon: MapPin },
  { id: 6, label: 'Review',    icon: CheckCircle },
];

// ── Initial data ──────────────────────────────────────────
const INIT = {
  // Step 1
  fullName: '', email: '', password: '', confirmPassword: '', role: 'guardian',
  phone: '', specialization: '', hospital: '', licenseNumber: '',

  // Step 2
  patientName: '', dob: '', gender: 'Male', bloodGroup: 'B+',
  patientPhone: '', patientNotes: '', height: '', weight: '',

  // Step 3
  guardianName: '', guardianRelation: '', guardianPhone: '',
  doctorName: '', doctorHospital: '', doctorPhone: '',
  ambulanceName: '', ambulancePhone: '',

  // Step 4
  cardiacCondition: '', allergies: '', medications: '',
  cardiacHistory: '', medNotes: '',

  // Step 5
  addressSearch: '', latitude: '', longitude: '',
  locationAddress: '', mapsLink: '',
};

// ── Validators ────────────────────────────────────────────
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_RE = /^\+?[\d\s\-().]{7,20}$/;

function validateStep(step, d) {
  const errs = {};
  if (step === 1) {
    if (!d.fullName.trim())              errs.fullName = 'Full name is required.';
    if (!EMAIL_RE.test(d.email))         errs.email    = 'Enter a valid email address.';
    if (d.password.length < 6)           errs.password = 'Password must be at least 6 characters.';
    if (d.password !== d.confirmPassword) errs.confirmPassword = 'Passwords do not match.';
    if (d.role === 'doctor' && !d.specialization.trim())
      errs.specialization = 'Specialization is required for doctors.';
  }
  if (step === 2) {
    if (!d.patientName.trim()) errs.patientName = 'Patient name is required.';
    if (!d.dob)                errs.dob         = 'Date of birth is required.';
    if (!d.gender)             errs.gender      = 'Select a gender.';
    if (!d.bloodGroup)         errs.bloodGroup  = 'Select a blood group.';
    if (d.patientPhone && !PHONE_RE.test(d.patientPhone))
      errs.patientPhone = 'Enter a valid phone number.';
  }
  if (step === 3) {
    if (!d.guardianName.trim())  errs.guardianName  = 'Guardian name is required.';
    if (!d.guardianPhone.trim()) errs.guardianPhone = 'Guardian phone is required.';
    else if (!PHONE_RE.test(d.guardianPhone)) errs.guardianPhone = 'Enter a valid phone number.';
    if (d.doctorPhone && !PHONE_RE.test(d.doctorPhone))
      errs.doctorPhone = 'Enter a valid phone number.';
    if (d.ambulancePhone && !PHONE_RE.test(d.ambulancePhone))
      errs.ambulancePhone = 'Enter a valid phone number.';
  }
  return errs;
}

// ── Age from DOB ──────────────────────────────────────────
function ageFromDob(dob) {
  if (!dob) return 0;
  const today = new Date();
  const birth = new Date(dob);
  let age = today.getFullYear() - birth.getFullYear();
  const m = today.getMonth() - birth.getMonth();
  if (m < 0 || (m === 0 && today.getDate() < birth.getDate())) age--;
  return Math.max(0, age);
}

// ── Sub-components ────────────────────────────────────────

function FieldError({ msg }) {
  if (!msg) return null;
  return <p className="mt-1 text-xs text-red-600 flex items-center gap-1"><AlertCircle className="w-3 h-3 inline" />{msg}</p>;
}

function Label({ children, required }) {
  return (
    <label className="block text-sm font-medium text-slate-700 mb-1">
      {children}{required && <span className="text-red-500 ml-0.5">*</span>}
    </label>
  );
}

function Input({ error, ...props }) {
  return (
    <input
      {...props}
      className={`w-full text-sm px-3 py-2.5 border rounded-xl outline-none transition-all
        focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400
        ${error ? 'border-red-300 bg-red-50' : 'border-slate-200 bg-white'}
        ${props.disabled ? 'opacity-60 cursor-not-allowed bg-slate-50' : ''}`}
    />
  );
}

function Select({ error, children, ...props }) {
  return (
    <select
      {...props}
      className={`w-full text-sm px-3 py-2.5 border rounded-xl outline-none transition-all
        focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 bg-white
        ${error ? 'border-red-300 bg-red-50' : 'border-slate-200'}`}
    >
      {children}
    </select>
  );
}

function Textarea({ error, ...props }) {
  return (
    <textarea
      rows={3}
      {...props}
      className={`w-full text-sm px-3 py-2.5 border rounded-xl outline-none transition-all resize-none
        focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400
        ${error ? 'border-red-300 bg-red-50' : 'border-slate-200 bg-white'}`}
    />
  );
}

function SectionTitle({ icon: Icon, children, color = 'blue' }) {
  const colors = {
    blue: 'bg-blue-100 text-blue-600',
    green: 'bg-green-100 text-green-600',
    orange: 'bg-orange-100 text-orange-600',
    purple: 'bg-purple-100 text-purple-600',
    red: 'bg-red-100 text-red-600',
  };
  return (
    <div className="flex items-center gap-2 mb-4">
      <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${colors[color]}`}>
        <Icon className="w-4 h-4" />
      </div>
      <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">{children}</h3>
    </div>
  );
}

// ── Progress Bar ──────────────────────────────────────────
function ProgressBar({ current }) {
  return (
    <div className="w-full mb-8">
      {/* Mobile: compact pill progress */}
      <div className="flex sm:hidden items-center justify-between mb-2">
        <span className="text-xs font-medium text-slate-500">
          Step {current} of {STEPS.length}
        </span>
        <span className="text-xs font-semibold text-blue-600">{STEPS[current - 1].label}</span>
      </div>
      <div className="flex sm:hidden h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-600 rounded-full transition-all duration-500"
          style={{ width: `${(current / STEPS.length) * 100}%` }}
        />
      </div>

      {/* Desktop: labeled step dots */}
      <div className="hidden sm:flex items-center justify-between relative">
        {/* connector line */}
        <div className="absolute top-4 left-0 right-0 h-0.5 bg-slate-100 z-0" />
        <div
          className="absolute top-4 left-0 h-0.5 bg-blue-600 z-0 transition-all duration-500"
          style={{ width: `${((current - 1) / (STEPS.length - 1)) * 100}%` }}
        />
        {STEPS.map(s => {
          const Icon = s.icon;
          const done = s.id < current;
          const active = s.id === current;
          return (
            <div key={s.id} className="flex flex-col items-center z-10">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center border-2 transition-all duration-300
                ${done   ? 'bg-blue-600 border-blue-600 text-white' :
                  active ? 'bg-white border-blue-600 text-blue-600' :
                           'bg-white border-slate-200 text-slate-300'}`}>
                {done ? <Check className="w-4 h-4" /> : <Icon className="w-3.5 h-3.5" />}
              </div>
              <span className={`mt-1.5 text-[11px] font-medium transition-colors
                ${active ? 'text-blue-600' : done ? 'text-slate-500' : 'text-slate-300'}`}>
                {s.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Step 1: Account ───────────────────────────────────────
function StepAccount({ data, onChange, errors }) {
  const [showPw, setShowPw]   = useState(false);
  const [showCpw, setShowCpw] = useState(false);
  return (
    <div className="space-y-5">
      <div>
        <Label required>Full Name</Label>
        <Input placeholder="e.g. Venkatesh Raju" value={data.fullName}
          onChange={e => onChange('fullName', e.target.value)} error={errors.fullName} />
        <FieldError msg={errors.fullName} />
      </div>

      <div>
        <Label required>Email Address</Label>
        <Input type="email" placeholder="you@example.com" value={data.email}
          onChange={e => onChange('email', e.target.value)} error={errors.email} />
        <FieldError msg={errors.email} />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <Label required>Password</Label>
          <div className="relative">
            <Input type={showPw ? 'text' : 'password'} placeholder="Min 6 characters"
              value={data.password} onChange={e => onChange('password', e.target.value)}
              error={errors.password} />
            <button type="button" onClick={() => setShowPw(p => !p)}
              className="absolute right-3 top-2.5 text-slate-400 hover:text-slate-600">
              {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          <FieldError msg={errors.password} />
        </div>
        <div>
          <Label required>Confirm Password</Label>
          <div className="relative">
            <Input type={showCpw ? 'text' : 'password'} placeholder="Repeat password"
              value={data.confirmPassword}
              onChange={e => onChange('confirmPassword', e.target.value)}
              error={errors.confirmPassword} />
            <button type="button" onClick={() => setShowCpw(p => !p)}
              className="absolute right-3 top-2.5 text-slate-400 hover:text-slate-600">
              {showCpw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          <FieldError msg={errors.confirmPassword} />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <Label required>Role</Label>
          <Select value={data.role} onChange={e => onChange('role', e.target.value)}>
            {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
          </Select>
        </div>
        <div>
          <Label>Phone Number</Label>
          <Input type="tel" placeholder="+91 98765 43210" value={data.phone}
            onChange={e => onChange('phone', e.target.value)} />
        </div>
      </div>

      {data.role === 'doctor' && (
        <div className="p-4 bg-blue-50 rounded-xl border border-blue-100 space-y-4">
          <p className="text-xs font-semibold text-blue-700 uppercase tracking-wide">Professional Details</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <Label required>Specialization</Label>
              <Input placeholder="e.g. Cardiologist" value={data.specialization}
                onChange={e => onChange('specialization', e.target.value)}
                error={errors.specialization} />
              <FieldError msg={errors.specialization} />
            </div>
            <div>
              <Label>Hospital / Clinic</Label>
              <Input placeholder="e.g. Apollo Hospital" value={data.hospital}
                onChange={e => onChange('hospital', e.target.value)} />
            </div>
          </div>
          <div>
            <Label>Medical License Number</Label>
            <Input placeholder="e.g. MH-12345" value={data.licenseNumber}
              onChange={e => onChange('licenseNumber', e.target.value)} />
          </div>
        </div>
      )}
    </div>
  );
}

// ── Step 2: Patient Info ──────────────────────────────────
function StepPatient({ data, onChange, errors }) {
  return (
    <div className="space-y-5">
      <div>
        <Label required>Patient Full Name</Label>
        <Input placeholder="e.g. Arjun Sharma" value={data.patientName}
          onChange={e => onChange('patientName', e.target.value)} error={errors.patientName} />
        <FieldError msg={errors.patientName} />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <Label required>Date of Birth</Label>
          <Input type="date" value={data.dob} max={new Date().toISOString().split('T')[0]}
            onChange={e => onChange('dob', e.target.value)} error={errors.dob} />
          <FieldError msg={errors.dob} />
          {data.dob && (
            <p className="mt-1 text-xs text-slate-400">Age: {ageFromDob(data.dob)} years</p>
          )}
        </div>
        <div>
          <Label required>Gender</Label>
          <Select value={data.gender} onChange={e => onChange('gender', e.target.value)}>
            {GENDERS.map(g => <option key={g}>{g}</option>)}
          </Select>
          <FieldError msg={errors.gender} />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <Label required>Blood Group</Label>
          <Select value={data.bloodGroup} onChange={e => onChange('bloodGroup', e.target.value)}>
            {BLOOD_GROUPS.map(b => <option key={b}>{b}</option>)}
          </Select>
          <FieldError msg={errors.bloodGroup} />
        </div>
        <div>
          <Label>Patient Phone Number</Label>
          <Input type="tel" placeholder="+91 98765 43210" value={data.patientPhone}
            onChange={e => onChange('patientPhone', e.target.value)} error={errors.patientPhone} />
          <FieldError msg={errors.patientPhone} />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <Label>Height</Label>
          <Input placeholder="e.g. 172 cm" value={data.height}
            onChange={e => onChange('height', e.target.value)} />
        </div>
        <div>
          <Label>Weight</Label>
          <Input placeholder="e.g. 74 kg" value={data.weight}
            onChange={e => onChange('weight', e.target.value)} />
        </div>
      </div>

      <div>
        <Label>Additional Notes</Label>
        <Textarea placeholder="Any other relevant information about the patient…"
          value={data.patientNotes} onChange={e => onChange('patientNotes', e.target.value)} />
      </div>
    </div>
  );
}

// ── Step 3: Emergency Contacts ────────────────────────────
function StepContacts({ data, onChange, errors }) {
  return (
    <div className="space-y-6">
      {/* Guardian */}
      <div className="p-4 bg-blue-50 rounded-xl border border-blue-100">
        <SectionTitle icon={Users} color="blue">Guardian</SectionTitle>
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <Label required>Guardian Name</Label>
              <Input placeholder="e.g. Priya Sharma" value={data.guardianName}
                onChange={e => onChange('guardianName', e.target.value)} error={errors.guardianName} />
              <FieldError msg={errors.guardianName} />
            </div>
            <div>
              <Label>Relationship</Label>
              <Input placeholder="e.g. Wife, Son, Daughter" value={data.guardianRelation}
                onChange={e => onChange('guardianRelation', e.target.value)} />
            </div>
          </div>
          <div>
            <Label required>Guardian Phone</Label>
            <Input type="tel" placeholder="+91 98765 43210" value={data.guardianPhone}
              onChange={e => onChange('guardianPhone', e.target.value)} error={errors.guardianPhone} />
            <FieldError msg={errors.guardianPhone} />
          </div>
        </div>
      </div>

      {/* Doctor */}
      <div className="p-4 bg-green-50 rounded-xl border border-green-100">
        <SectionTitle icon={Stethoscope} color="green">Doctor / Cardiologist</SectionTitle>
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <Label>Doctor Name</Label>
              <Input placeholder="e.g. Dr. Ramesh Kumar" value={data.doctorName}
                onChange={e => onChange('doctorName', e.target.value)} />
            </div>
            <div>
              <Label>Hospital / Clinic</Label>
              <Input placeholder="e.g. Apollo Hospital" value={data.doctorHospital}
                onChange={e => onChange('doctorHospital', e.target.value)} />
            </div>
          </div>
          <div>
            <Label>Doctor Phone</Label>
            <Input type="tel" placeholder="+91 98765 43210" value={data.doctorPhone}
              onChange={e => onChange('doctorPhone', e.target.value)} error={errors.doctorPhone} />
            <FieldError msg={errors.doctorPhone} />
            <p className="text-xs text-slate-400 mt-1">Used for WhatsApp emergency alerts</p>
          </div>
        </div>
      </div>

      {/* Ambulance */}
      <div className="p-4 bg-red-50 rounded-xl border border-red-100">
        <SectionTitle icon={Phone} color="red">Ambulance / Emergency Service</SectionTitle>
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <Label>Service Name</Label>
              <Input placeholder="e.g. Apollo Ambulance" value={data.ambulanceName}
                onChange={e => onChange('ambulanceName', e.target.value)} />
            </div>
            <div>
              <Label>Ambulance Phone</Label>
              <Input type="tel" placeholder="+91 104 or +91 112" value={data.ambulancePhone}
                onChange={e => onChange('ambulancePhone', e.target.value)} error={errors.ambulancePhone} />
              <FieldError msg={errors.ambulancePhone} />
            </div>
          </div>
          <p className="text-xs text-slate-400">Used for WhatsApp emergency alerts on critical conditions</p>
        </div>
      </div>
    </div>
  );
}

// ── Step 4: Medical Info ──────────────────────────────────
function StepMedical({ data, onChange }) {
  return (
    <div className="space-y-5">
      <div className="p-3 bg-amber-50 rounded-xl border border-amber-100">
        <p className="text-xs text-amber-700">
          All fields in this section are optional. Providing accurate medical history helps
          ECG Guardian provide better cardiac risk assessment.
        </p>
      </div>

      <div>
        <Label>Existing Cardiac Condition</Label>
        <Input placeholder="e.g. Hypertension, Arrhythmia, Heart failure…" value={data.cardiacCondition}
          onChange={e => onChange('cardiacCondition', e.target.value)} />
      </div>

      <div>
        <Label>Known Allergies</Label>
        <Input placeholder="e.g. Penicillin, Aspirin, Pollen…" value={data.allergies}
          onChange={e => onChange('allergies', e.target.value)} />
      </div>

      <div>
        <Label>Current Medications</Label>
        <Textarea placeholder="e.g. Metformin 500mg twice daily, Atorvastatin 20mg…"
          value={data.medications} onChange={e => onChange('medications', e.target.value)} />
      </div>

      <div>
        <Label>Previous Cardiac History</Label>
        <Textarea placeholder="e.g. Heart attack in 2021, stent placement, bypass surgery…"
          value={data.cardiacHistory} onChange={e => onChange('cardiacHistory', e.target.value)} />
      </div>

      <div>
        <Label>Additional Medical Notes</Label>
        <Textarea placeholder="Any other information relevant to cardiac monitoring…"
          value={data.medNotes} onChange={e => onChange('medNotes', e.target.value)} />
      </div>
    </div>
  );
}

// ── Step 5: Location ──────────────────────────────────────
function StepLocation({ data, onChange }) {
  const [searching, setSearching]       = useState(false);
  const [locating,  setLocating]        = useState(false);
  const [mapReady,  setMapReady]        = useState(false);
  const [mapError,  setMapError]        = useState('');
  const [searchErr, setSearchErr]       = useState('');
  const [geoErr,    setGeoErr]          = useState('');
  const mapRef        = useRef(null);
  const leafletMapRef = useRef(null);
  const markerRef     = useRef(null);

  const hasLocation = data.latitude && data.longitude;

  // Build Google Maps URL
  const buildMapsLink = (lat, lng) =>
    `https://www.google.com/maps?q=${lat},${lng}`;

  // Reverse geocode using Nominatim (free, no key required)
  const reverseGeocode = useCallback(async (lat, lng) => {
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}&zoom=18&addressdetails=1`,
        { headers: { 'Accept-Language': 'en' } }
      );
      if (res.ok) {
        const d = await res.json();
        return d.display_name || `${lat}, ${lng}`;
      }
    } catch { /* ignore */ }
    return `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
  }, []);

  // Forward geocode (address → lat/lng)
  const forwardGeocode = useCallback(async (address) => {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(address)}&limit=1`,
      { headers: { 'Accept-Language': 'en' } }
    );
    if (!res.ok) throw new Error('Geocoding request failed.');
    const results = await res.json();
    if (!results.length) throw new Error('No results found for that address.');
    return { lat: parseFloat(results[0].lat), lng: parseFloat(results[0].lon), display: results[0].display_name };
  }, []);

  // Set location and update all related fields
  const setLocation = useCallback(async (lat, lng, knownAddress) => {
    const address = knownAddress || await reverseGeocode(lat, lng);
    const mapsLink = buildMapsLink(lat, lng);
    onChange('latitude',        String(lat.toFixed(6)));
    onChange('longitude',       String(lng.toFixed(6)));
    onChange('locationAddress', address);
    onChange('mapsLink',        mapsLink);
    onChange('addressSearch',   address);
  }, [onChange, reverseGeocode]);

  // Move/create Leaflet marker
  const placeMarker = useCallback((map, lat, lng) => {
    if (!window.L) return;
    const L = window.L;
    if (markerRef.current) {
      markerRef.current.setLatLng([lat, lng]);
    } else {
      const icon = L.divIcon({
        html: `<div style="
          width:32px;height:32px;background:#2563eb;border-radius:50% 50% 50% 0;
          transform:rotate(-45deg);border:3px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.3)">
        </div>`,
        iconSize: [32, 32],
        iconAnchor: [16, 32],
        className: '',
      });
      markerRef.current = L.marker([lat, lng], { icon, draggable: true }).addTo(map);
      markerRef.current.on('dragend', async (e) => {
        const { lat: newLat, lng: newLng } = e.target.getLatLng();
        await setLocation(newLat, newLng);
      });
    }
    map.setView([lat, lng], 15);
  }, [setLocation]);

  // Init Leaflet map
  useEffect(() => {
    if (!mapRef.current || leafletMapRef.current) return;

    // Load Leaflet CSS if not already loaded
    if (!document.getElementById('leaflet-css')) {
      const link = document.createElement('link');
      link.id   = 'leaflet-css';
      link.rel  = 'stylesheet';
      link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      document.head.appendChild(link);
    }

    // Use Leaflet from node_modules (already installed)
    import('leaflet').then(L_module => {
      const L = L_module.default || L_module;
      window.L = L;

      // Fix default marker icon paths
      delete L.Icon.Default.prototype._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
        iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
        shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
      });

      const map = L.map(mapRef.current, { zoomControl: true }).setView([20.5937, 78.9629], 5);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19,
      }).addTo(map);

      map.on('click', async (e) => {
        const { lat, lng } = e.latlng;
        placeMarker(map, lat, lng);
        await setLocation(lat, lng);
      });

      leafletMapRef.current = map;
      setMapReady(true);

      // If location already set, show it on map
      if (data.latitude && data.longitude) {
        placeMarker(map, parseFloat(data.latitude), parseFloat(data.longitude));
      }
    }).catch(() => setMapError('Could not load map. Check your internet connection.'));

    return () => {
      if (leafletMapRef.current) {
        leafletMapRef.current.remove();
        leafletMapRef.current = null;
        markerRef.current = null;
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // When external location changes, update map marker
  useEffect(() => {
    if (leafletMapRef.current && data.latitude && data.longitude) {
      placeMarker(leafletMapRef.current, parseFloat(data.latitude), parseFloat(data.longitude));
    }
  }, [data.latitude, data.longitude, placeMarker]);

  // Search handler
  const handleSearch = async () => {
    if (!data.addressSearch.trim()) return;
    setSearching(true);
    setSearchErr('');
    try {
      const { lat, lng, display } = await forwardGeocode(data.addressSearch);
      await setLocation(lat, lng, display);
    } catch (e) {
      setSearchErr(e.message);
    } finally {
      setSearching(false);
    }
  };

  // Current location
  const handleCurrentLocation = () => {
    if (!navigator.geolocation) {
      setGeoErr('Geolocation is not supported by your browser.');
      return;
    }
    setLocating(true);
    setGeoErr('');
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        await setLocation(pos.coords.latitude, pos.coords.longitude);
        setLocating(false);
      },
      (err) => {
        setGeoErr(
          err.code === 1
            ? 'Location permission denied. Please enter the address manually.'
            : 'Unable to get your location. Please enter the address manually.'
        );
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  return (
    <div className="space-y-5">
      <div className="p-3 bg-blue-50 rounded-xl border border-blue-100">
        <p className="text-xs text-blue-700">
          Patient location is used to generate a Google Maps link sent with emergency alerts.
          You can update this later from the Patients page.
        </p>
      </div>

      {/* Address search */}
      <div>
        <Label>Search Address</Label>
        <div className="flex gap-2">
          <Input placeholder="e.g. 2nd Cross, Chickpet, Bangalore"
            value={data.addressSearch}
            onChange={e => onChange('addressSearch', e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()} />
          <button
            type="button"
            onClick={handleSearch}
            disabled={searching}
            className="shrink-0 flex items-center gap-1.5 px-4 py-2.5 bg-blue-600 text-white text-sm
              font-medium rounded-xl hover:bg-blue-700 disabled:opacity-60 transition-colors"
          >
            {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            <span className="hidden sm:inline">Search</span>
          </button>
        </div>
        {searchErr && <p className="mt-1 text-xs text-red-600">{searchErr}</p>}
      </div>

      {/* Current location button */}
      <button
        type="button"
        onClick={handleCurrentLocation}
        disabled={locating}
        className="w-full flex items-center justify-center gap-2 py-2.5 border-2 border-dashed
          border-blue-200 text-blue-600 text-sm font-medium rounded-xl hover:bg-blue-50
          disabled:opacity-60 transition-all"
      >
        {locating
          ? <><Loader2 className="w-4 h-4 animate-spin" /> Getting your location…</>
          : <><Navigation className="w-4 h-4" /> Use My Current Location</>}
      </button>
      {geoErr && <p className="text-xs text-red-600 -mt-2">{geoErr}</p>}

      {/* Map */}
      <div>
        <Label>Select on Map</Label>
        <p className="text-xs text-slate-400 mb-2">Click anywhere on the map to set location. Drag the marker to adjust.</p>
        {mapError ? (
          <div className="h-56 rounded-xl border border-red-200 bg-red-50 flex items-center justify-center text-sm text-red-600">
            {mapError}
          </div>
        ) : (
          <div
            ref={mapRef}
            className="w-full rounded-xl border border-slate-200 overflow-hidden"
            style={{ height: '280px' }}
          />
        )}
        {!mapReady && !mapError && (
          <div className="flex items-center gap-2 mt-2 text-xs text-slate-400">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Loading map…
          </div>
        )}
      </div>

      {/* Selected location display */}
      {hasLocation && (
        <div className="p-4 bg-green-50 rounded-xl border border-green-200">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-start gap-2">
              <Check className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-green-800">Location selected</p>
                <p className="text-xs text-green-700 mt-0.5 break-all">{data.locationAddress}</p>
                <p className="text-xs text-slate-500 mt-1">
                  {data.latitude}, {data.longitude}
                </p>
              </div>
            </div>
            <a
              href={data.mapsLink} target="_blank" rel="noopener noreferrer"
              className="shrink-0 flex items-center gap-1 text-xs text-blue-600 hover:underline"
            >
              <ExternalLink className="w-3 h-3" />
              Maps
            </a>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Step 6: Review ────────────────────────────────────────
function StepReview({ data, onEdit }) {
  const row = (label, value) =>
    value ? (
      <div className="flex justify-between items-start py-1.5 border-b border-slate-50 last:border-0">
        <span className="text-xs text-slate-500 shrink-0 w-36">{label}</span>
        <span className="text-xs font-medium text-slate-800 text-right break-all">{value}</span>
      </div>
    ) : null;

  const Section = ({ title, color, icon: Icon, fields, stepId }) => {
    const hasContent = fields.some(([, v]) => v);
    if (!hasContent) return null;
    const colors = {
      blue: 'bg-blue-50 border-blue-100 text-blue-700',
      green: 'bg-green-50 border-green-100 text-green-700',
      orange: 'bg-orange-50 border-orange-100 text-orange-700',
      purple: 'bg-purple-50 border-purple-100 text-purple-700',
      red: 'bg-red-50 border-red-100 text-red-700',
    };
    return (
      <div className={`p-4 rounded-xl border ${colors[color]}`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Icon className="w-4 h-4" />
            <span className="text-xs font-bold uppercase tracking-wide">{title}</span>
          </div>
          <button type="button" onClick={() => onEdit(stepId)}
            className="flex items-center gap-1 text-xs underline opacity-70 hover:opacity-100">
            <Edit2 className="w-3 h-3" />Edit
          </button>
        </div>
        <div className="bg-white/70 rounded-lg px-3 py-1">
          {fields.map(([label, value]) => row(label, value))}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      <div className="p-3 bg-blue-50 rounded-xl border border-blue-100">
        <p className="text-xs text-blue-700">
          Review your information below. Click <strong>Edit</strong> on any section to go back and make changes.
        </p>
      </div>

      <Section title="Account" icon={User} color="blue" stepId={1} fields={[
        ['Full Name',       data.fullName],
        ['Email',          data.email],
        ['Role',           ROLES.find(r => r.value === data.role)?.label],
        ['Phone',          data.phone],
        ['Specialization', data.specialization],
        ['Hospital',       data.hospital],
      ]} />

      <Section title="Patient" icon={Heart} color="green" stepId={2} fields={[
        ['Patient Name',  data.patientName],
        ['Date of Birth', data.dob],
        ['Age',           data.dob ? `${ageFromDob(data.dob)} years` : ''],
        ['Gender',        data.gender],
        ['Blood Group',   data.bloodGroup],
        ['Phone',         data.patientPhone],
        ['Height',        data.height],
        ['Weight',        data.weight],
      ]} />

      <Section title="Emergency Contacts" icon={Users} color="orange" stepId={3} fields={[
        ['Guardian',           data.guardianName],
        ['Relationship',       data.guardianRelation],
        ['Guardian Phone',     data.guardianPhone],
        ['Doctor',             data.doctorName],
        ['Doctor Hospital',    data.doctorHospital],
        ['Doctor Phone',       data.doctorPhone],
        ['Ambulance Service',  data.ambulanceName],
        ['Ambulance Phone',    data.ambulancePhone],
      ]} />

      <Section title="Medical" icon={Stethoscope} color="purple" stepId={4} fields={[
        ['Cardiac Condition', data.cardiacCondition],
        ['Allergies',        data.allergies],
        ['Medications',      data.medications],
        ['Cardiac History',  data.cardiacHistory],
        ['Medical Notes',    data.medNotes],
      ]} />

      <Section title="Location" icon={MapPin} color="red" stepId={5} fields={[
        ['Address',   data.locationAddress],
        ['Latitude',  data.latitude],
        ['Longitude', data.longitude],
      ]} />

      {data.mapsLink && (
        <a href={data.mapsLink} target="_blank" rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-sm text-blue-600 hover:underline">
          <ExternalLink className="w-4 h-4" />
          Open patient location in Google Maps
        </a>
      )}
    </div>
  );
}

// ── Main Wizard ───────────────────────────────────────────
export default function Register() {
  const navigate     = useNavigate();
  const { dispatch } = useApp();

  const [step,    setStep]    = useState(1);
  const [data,    setData]    = useState(INIT);
  const [errors,  setErrors]  = useState({});
  const [submitting, setSub]  = useState(false);
  const [serverErr, setServerErr] = useState('');

  const onChange = (key, val) => {
    setData(d => ({ ...d, [key]: val }));
    if (errors[key]) setErrors(e => { const n = { ...e }; delete n[key]; return n; });
  };

  const handleNext = () => {
    const errs = validateStep(step, data);
    if (Object.keys(errs).length) { setErrors(errs); return; }
    setErrors({});
    setStep(s => Math.min(s + 1, 6));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleBack = () => {
    setErrors({});
    setStep(s => Math.max(s - 1, 1));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleEdit = (targetStep) => {
    setStep(targetStep);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleSubmit = async () => {
    setSub(true);
    setServerErr('');

    // Generate username from email prefix
    const username = data.email.split('@')[0].replace(/[^a-z0-9_]/gi, '_').toLowerCase();

    // 1. Register user account
    try {
      await registerUser({
        username,
        email:            data.email,
        password:         data.password,
        confirm_password: data.confirmPassword,
        full_name:        data.fullName,
        role:             data.role,
        phone:            data.phone         || null,
        specialization:   data.specialization || null,
        hospital:         data.hospital       || null,
        license_number:   data.licenseNumber  || null,
      });
    } catch (err) {
      setServerErr(err.message);
      setSub(false);
      return;
    }

    // 2. Auto-login
    try {
      const { user } = await loginWithCredentials(data.email, data.password);
      dispatch({ type: 'SET_AUTH_USER', payload: user });
    } catch (_err) {
      setServerErr('Account created but login failed. Please go to the login page.');
      setSub(false);
      return;
    }

    // 3. Create patient record — send every field the wizard collects
    const age      = ageFromDob(data.dob);
    // Merge cardiac condition + cardiac history into diseases field
    const diseases = [data.cardiacCondition, data.cardiacHistory].filter(Boolean).join('; ') || null;
    // Merge patient notes + medical notes into the notes field
    const notes    = [data.patientNotes, data.medNotes].filter(Boolean).join('\n\n') || null;

    try {
      const patientPayload = {
        // Core demographics
        name:              data.patientName,
        age,
        dob:               data.dob          || null,
        gender:            data.gender,
        blood_group:       data.bloodGroup,
        phone:             data.patientPhone  || null,
        height:            data.height        || null,
        weight:            data.weight        || null,
        // Guardian
        guardian_name:     data.guardianName     || null,
        guardian_phone:    data.guardianPhone    || null,
        guardian_relation: data.guardianRelation || null,
        emergency_contact: data.guardianPhone    || null,
        // Doctor
        doctor_name:       data.doctorName     || null,
        doctor_hospital:   data.doctorHospital || null,
        doctor_phone:      data.doctorPhone    || null,
        // Ambulance
        ambulance_name:    data.ambulanceName  || null,
        ambulance_phone:   data.ambulancePhone || null,
        // Medical
        diseases,
        medications:       data.medications || null,
        allergies:         data.allergies   || null,
        notes,
        // Location
        address:           data.locationAddress || null,
        location:          data.latitude && data.longitude
                             ? `${data.latitude},${data.longitude}` : null,
        location_address:  data.locationAddress || null,
        maps_link:         data.mapsLink        || null,
        registration_date: new Date().toISOString(),
      };


      // Use apiPost so the token is automatically attached
      const newPatient = await apiPost('/patients', patientPayload);

      // Map backend response to frontend camelCase shape and push to context
      const { patientFromBackend } = await import('../context/AppContext');
      const mapped = patientFromBackend(newPatient);
      dispatch({ type: 'ADD_PATIENT_TO_LIST', payload: mapped });
      dispatch({ type: 'SET_PATIENT',         payload: mapped });
    } catch {
      // Patient creation failure is non-fatal — user can add from Patients page
    }

    setSub(false);
    navigate('/', { replace: true });
  };

  const stepTitles = [
    'Create Your Account',
    'Patient Information',
    'Emergency Contacts',
    'Medical Information',
    'Patient Location',
    'Review & Complete',
  ];

  const stepSubtitles = [
    'Set up your ECG Guardian login credentials',
    'Enter the details of the patient being monitored',
    'Add contacts for emergency WhatsApp alerts',
    'Optional: help us provide better cardiac risk assessment',
    'Optional: used to generate location link in emergency alerts',
    'Confirm all information before creating your account',
  ];

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-slate-50 py-8 px-4">
      <div className="w-full max-w-2xl mx-auto">

        {/* Brand header */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded-2xl bg-blue-600 flex items-center justify-center mb-3 shadow-lg">
            <Heart className="w-6 h-6 text-white" fill="currentColor" />
          </div>
          <h1 className="text-xl font-bold text-slate-800">ECG Guardian</h1>
          <p className="text-sm text-slate-400 mt-0.5">AI-Based Remote Cardiac Monitoring</p>
        </div>

        {/* Progress */}
        <ProgressBar current={step} />

        {/* Card */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
          {/* Card header */}
          <div className="px-6 py-5 border-b border-slate-100 bg-slate-50/60">
            <h2 className="text-lg font-semibold text-slate-800">{stepTitles[step - 1]}</h2>
            <p className="text-sm text-slate-400 mt-0.5">{stepSubtitles[step - 1]}</p>
          </div>

          {/* Card body */}
          <div className="px-6 py-6">
            {serverErr && (
              <div className="mb-5 flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{serverErr}</span>
              </div>
            )}

            {step === 1 && <StepAccount  data={data} onChange={onChange} errors={errors} />}
            {step === 2 && <StepPatient  data={data} onChange={onChange} errors={errors} />}
            {step === 3 && <StepContacts data={data} onChange={onChange} errors={errors} />}
            {step === 4 && <StepMedical  data={data} onChange={onChange} />}
            {step === 5 && <StepLocation data={data} onChange={onChange} />}
            {step === 6 && <StepReview   data={data} onEdit={handleEdit} />}
          </div>

          {/* Card footer */}
          <div className="px-6 py-4 border-t border-slate-100 bg-slate-50/60 flex items-center justify-between gap-3">
            {step > 1 ? (
              <button
                type="button"
                onClick={handleBack}
                className="flex items-center gap-1.5 px-4 py-2.5 text-sm text-slate-600 border
                  border-slate-200 rounded-xl hover:bg-white transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
                Back
              </button>
            ) : (
              <Link to="/login"
                className="flex items-center gap-1.5 px-4 py-2.5 text-sm text-slate-600 border
                  border-slate-200 rounded-xl hover:bg-white transition-colors">
                <ChevronLeft className="w-4 h-4" />
                Sign In
              </Link>
            )}

            {step < 6 ? (
              <button
                type="button"
                onClick={handleNext}
                className="flex items-center gap-1.5 px-6 py-2.5 text-sm font-semibold
                  bg-blue-600 text-white rounded-xl hover:bg-blue-700 active:scale-95
                  transition-all shadow-sm"
              >
                Continue
                <ChevronRight className="w-4 h-4" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={submitting}
                className="flex items-center gap-2 px-6 py-2.5 text-sm font-semibold
                  bg-green-600 text-white rounded-xl hover:bg-green-700 active:scale-95
                  disabled:opacity-60 transition-all shadow-sm"
              >
                {submitting
                  ? <><Loader2 className="w-4 h-4 animate-spin" />Creating Account…</>
                  : <><CheckCircle className="w-4 h-4" />Complete Registration</>}
              </button>
            )}
          </div>
        </div>

        {/* Footer link */}
        <p className="text-center text-sm text-slate-400 mt-6">
          Already have an account?{' '}
          <Link to="/login" className="text-blue-600 font-medium hover:underline">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
