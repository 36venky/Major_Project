/**
 * DeviceCard – Shows real-time device connection and signal information.
 */
import { Cpu } from 'lucide-react';
import Card from './Card';
import StatRow from './StatRow';
import Badge from './Badge';
import { useApp } from '../context/AppContext';

export default function DeviceCard() {
  const { state } = useApp();
  const d = state.device;
  const q = d.signalQuality;

  const qualityVariant = q >= 80 ? 'green' : q >= 50 ? 'amber' : 'red';

  return (
    <Card title="Device Information" subtitle="Sensor & connection status">
      <StatRow
        label="Status"
        value={<Badge label={d.status} variant={d.connected ? 'green' : 'red'} dot />}
      />
      <StatRow label="COM Port"          value={d.port} />
      <StatRow label="Sampling Rate"     value={d.samplingRate} />
      <StatRow
        label="Signal Quality"
        value={
          <div className="flex items-center gap-2">
            <div className="w-16 h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500
                  ${q >= 80 ? 'bg-emerald-500' : q >= 50 ? 'bg-amber-400' : 'bg-red-500'}`}
                style={{ width: `${q}%` }}
              />
            </div>
            <span className={`text-xs font-semibold
              ${q >= 80 ? 'text-emerald-600' : q >= 50 ? 'text-amber-600' : 'text-red-600'}`}>
              {q}%
            </span>
          </div>
        }
      />
      <StatRow label="Duration"          value={d.monitoringDuration} />
    </Card>
  );
}
