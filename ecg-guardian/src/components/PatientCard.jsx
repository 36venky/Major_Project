/**
 * PatientCard – Displays patient demographic information.
 */
import { User } from 'lucide-react';
import Card from './Card';
import StatRow from './StatRow';
import { useApp } from '../context/AppContext';

export default function PatientCard() {
  const { state } = useApp();
  const p = state.patient;

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
    <Card title="Patient Information" subtitle="Demographic details">
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

      <StatRow label="Age"               value={p.age ? `${p.age} years` : '—'} />
      <StatRow label="Height"            value={p.height            || '—'} />
      <StatRow label="Weight"            value={p.weight            || '—'} />
      <StatRow label="Guardian"          value={p.guardianName      || '—'} />
      <StatRow label="Emergency Contact" value={p.emergencyContact  || '—'} />
    </Card>
  );
}
