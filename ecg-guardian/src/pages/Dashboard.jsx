/**
 * Dashboard – Main overview page.
 *
 * Changes from original:
 *  - DeviceCard removed (Feature 3)
 *  - 3-column info card grid: PatientCard | HeartRateCard | WeeklyHealthCard
 *  - "Add Patient" button + AddPatientModal (Feature 2)
 *  - PatientSelector dropdown (Feature 2)
 *  - ECGCanvas → LiveECGChart with Plotly (Feature 1)
 *  - RiskCard + RiskChart added (Feature 5)
 */
import { useState } from 'react';
import { UserPlus } from 'lucide-react';

import PatientCard      from '../components/PatientCard';
import HeartRateCard    from '../components/HeartRateCard';
import WeeklyHealthCard from '../components/WeeklyHealthCard';
import LiveECGChart     from '../components/LiveECGChart';
import AIAnalysisCard   from '../components/AIAnalysisCard';
import AlertPanel       from '../components/AlertPanel';
import Timeline         from '../components/Timeline';
import RiskCard         from '../components/RiskCard';
import RiskChart        from '../components/RiskChart';
import Card             from '../components/Card';
import AddPatientModal  from '../components/AddPatientModal';
import PatientSelector  from '../components/PatientSelector';

export default function Dashboard() {
  const [showAddModal, setShowAddModal] = useState(false);

  return (
    <div className="space-y-6">

      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Dashboard</h1>
          <p className="text-sm text-slate-400 mt-0.5">Real-time ECG monitoring overview</p>
        </div>

        {/* Patient controls */}
        <div className="flex items-center gap-3 flex-wrap">
          <PatientSelector />
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-4 py-2 text-sm font-semibold
              bg-blue-600 text-white rounded-lg hover:bg-blue-700
              active:scale-95 transition-all shadow-sm"
          >
            <UserPlus className="w-4 h-4" />
            Add Patient
          </button>
        </div>
      </div>

      {/* Info cards — 3 columns (DeviceCard removed) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        <PatientCard />
        <HeartRateCard />
        <WeeklyHealthCard />
      </div>

      {/* Live ECG — Plotly chart */}
      <Card
        title="Live ECG Waveform"
        subtitle="Continuous monitoring — Lead II"
        noPad
      >
        <div className="p-4">
          <LiveECGChart windowSeconds={10} />
        </div>
      </Card>

      {/* Risk prediction row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <RiskCard />
        <div className="lg:col-span-2">
          <Card title="Risk vs Day" subtitle="Last 30 days — cardiac risk trend" noPad>
            <div className="px-2 pb-2">
              <RiskChart />
            </div>
          </Card>
        </div>
      </div>

      {/* Bottom row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <AIAnalysisCard />
        <AlertPanel />
        <Timeline />
      </div>

      {/* Add Patient Modal */}
      {showAddModal && (
        <AddPatientModal onClose={() => setShowAddModal(false)} />
      )}
    </div>
  );
}
