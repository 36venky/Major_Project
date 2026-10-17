/**
 * PatientCard – Displays patient demographic information and weekly health data.
 */
import { User, Activity, Droplets, Pencil } from 'lucide-react';
import Card from './Card';
import StatRow from './StatRow';
import { useApp } from '../context/AppContext';
import { formatDateTime } from '../utils/helpers';
import { useNavigate } from 'react-router-dom';

export default function PatientCard() {
  const { state } = useApp();
  const p = state.patient;
  const wh = state.weeklyHealth;
  const navigate = useNavigate();

  // Patient hasn't loaded yet (empty DB or still fetching)
  if (!p) {
    return (
      <Card title="Patient Information" subtitle="Demographic details">
        <div className="flex flex-col items-center justify-center py-6 text-slate-400 gap-2">
          <User className="w-8 h-8" />
          <p className="text-sm">No patient registered yet.</p>
        </div>
      </Card>
    );
  }

  return (
    <Card 
      title="Patient Information" 
      subtitle="Demographic & Health Summary"
      action={
        <button
          onClick={() => navigate('/settings')}
          className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 font-medium"
          title="Edit health information"
        >
          <Pencil className="w-3 h-3" />
          Edit
        </button>
      }
    >
      {/* Avatar + name */}
      <div className="flex items-center gap-3 mb-4">
        <div className="w-12 h-12 rounded-full bg-blue-100 flex items-center justify-center text-blue-700 font-bold text-lg">
          {p.name?.charAt(0) ?? '?'}
        </div>
        <div>
          <p className="text-sm font-bold text-slate-800">{p.name}</p>
          <p className="text-xs text-slate-400">{p.gender} · {p.bloodGroup}</p>
        </div>
      </div>

      {/* Basic Demographics */}
      <StatRow label="Age"               value={p.age ? `${p.age} years` : '—'} />
      <StatRow label="Guardian"          value={p.guardianName      || '—'} />
      <StatRow label="Emergency Contact" value={p.emergencyContact  || '—'} />

      {/* Divider */}
      <div className="my-4 border-t border-slate-100"></div>

      {/* Weekly Health Information */}
      <div className="space-y-3">
        {/* Blood Pressure */}
        <div className="flex items-center gap-3 p-3 rounded-lg bg-rose-50 border border-rose-100">
          <div className="w-8 h-8 rounded-lg bg-rose-100 flex items-center justify-center">
            <Activity className="w-4 h-4 text-rose-600" />
          </div>
          <div className="flex-1">
            <p className="text-[10px] text-slate-500 font-medium uppercase tracking-wide">Blood Pressure</p>
            <p className="text-sm font-bold text-slate-800">{wh.bloodPressure || '—'}</p>
          </div>
        </div>

        {/* Blood Sugar */}
        <div className="flex items-center gap-3 p-3 rounded-lg bg-amber-50 border border-amber-100">
          <div className="w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center">
            <Droplets className="w-4 h-4 text-amber-600" />
          </div>
          <div className="flex-1">
            <p className="text-[10px] text-slate-500 font-medium uppercase tracking-wide">Blood Sugar</p>
            <p className="text-sm font-bold text-slate-800">{wh.bloodSugar || '—'}</p>
          </div>
        </div>

        {wh.lastUpdated && (
          <p className="text-[10px] text-slate-400 text-right">
            Last updated: {formatDateTime(wh.lastUpdated)}
          </p>
        )}
      </div>
    </Card>
  );
}
