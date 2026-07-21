/**
 * WeeklyHealthCard – Blood pressure and blood sugar summary.
 * Values are manually updated by patient/guardian via the health update form.
 */
import { Pencil, Droplets, Activity } from 'lucide-react';
import Card from './Card';
import { useApp } from '../context/AppContext';
import { formatDateTime } from '../utils/helpers';
import { useNavigate } from 'react-router-dom';

export default function WeeklyHealthCard() {
  const { state } = useApp();
  const wh = state.weeklyHealth;
  const navigate = useNavigate();

  return (
    <Card
      title="Weekly Health Summary"
      subtitle="Manually updated"
      action={
        <button
          onClick={() => navigate('/settings')}
          className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 font-medium"
        >
          <Pencil className="w-3 h-3" />
          Edit
        </button>
      }
    >
      <div className="space-y-3">
        {/* Blood Pressure */}
        <div className="flex items-center gap-3 p-3 rounded-lg bg-rose-50 border border-rose-100">
          <div className="w-8 h-8 rounded-lg bg-rose-100 flex items-center justify-center">
            <Activity className="w-4 h-4 text-rose-600" />
          </div>
          <div className="flex-1">
            <p className="text-[10px] text-slate-500 font-medium uppercase tracking-wide">Blood Pressure</p>
            <p className="text-sm font-bold text-slate-800">{wh.bloodPressure}</p>
          </div>
        </div>

        {/* Blood Sugar */}
        <div className="flex items-center gap-3 p-3 rounded-lg bg-amber-50 border border-amber-100">
          <div className="w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center">
            <Droplets className="w-4 h-4 text-amber-600" />
          </div>
          <div className="flex-1">
            <p className="text-[10px] text-slate-500 font-medium uppercase tracking-wide">Blood Sugar</p>
            <p className="text-sm font-bold text-slate-800">{wh.bloodSugar}</p>
          </div>
        </div>

        <p className="text-[10px] text-slate-400 text-right">
          Last updated: {formatDateTime(wh.lastUpdated)}
        </p>
      </div>
    </Card>
  );
}
