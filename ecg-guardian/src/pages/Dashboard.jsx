/**
 * Dashboard – Main overview page.
 *
 * "Add Patient" button removed — patients are now registered
 * through the /register onboarding wizard.
 * PatientSelector remains so the user can switch between existing patients.
 */
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
import PatientSelector  from '../components/PatientSelector';

export default function Dashboard() {
  return (
    <div className="space-y-6">

      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Dashboard</h1>
          <p className="text-sm text-slate-400 mt-0.5">Real-time ECG monitoring overview</p>
        </div>

        {/* Patient selector */}
        <PatientSelector />
      </div>

      {/* Info cards — 3 columns */}
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

    </div>
  );
}
