/**
 * Timeline – Chronological list of monitoring events.
 */
import Card from './Card';
import { useApp } from '../context/AppContext';
import { formatDateTime } from '../utils/helpers';
import {
  Play, Square, Wifi, WifiOff, AlertTriangle,
  RefreshCw, Edit3, Droplets,
} from 'lucide-react';

const iconMap = {
  play:     { icon: Play,         bg: 'bg-emerald-100', text: 'text-emerald-600' },
  stop:     { icon: Square,       bg: 'bg-slate-100',   text: 'text-slate-500' },
  wifi:     { icon: Wifi,         bg: 'bg-blue-100',    text: 'text-blue-600' },
  'wifi-off':{ icon: WifiOff,     bg: 'bg-red-100',     text: 'text-red-600' },
  alert:    { icon: AlertTriangle,bg: 'bg-amber-100',   text: 'text-amber-600' },
  refresh:  { icon: RefreshCw,    bg: 'bg-blue-100',    text: 'text-blue-600' },
  edit:     { icon: Edit3,        bg: 'bg-purple-100',  text: 'text-purple-600' },
  droplets: { icon: Droplets,     bg: 'bg-amber-100',   text: 'text-amber-600' },
};

export default function Timeline({ maxItems = 6 }) {
  const { state } = useApp();
  const events = state.timeline.slice(0, maxItems);

  return (
    <Card title="Timeline" subtitle="Recent monitoring events">
      <ol className="relative border-l border-slate-200 ml-2 space-y-4">
        {events.map((ev, idx) => {
          const config = iconMap[ev.icon] || iconMap.play;
          const Icon = config.icon;
          return (
            <li key={ev.id} className="ml-4 animate-slide-in">
              <div className={`absolute -left-2 w-4 h-4 rounded-full flex items-center justify-center ${config.bg}`}>
                <Icon className={`w-2 h-2 ${config.text}`} />
              </div>
              <p className="text-xs font-semibold text-slate-700">{ev.event}</p>
              <p className="text-[10px] text-slate-400 mt-0.5">{formatDateTime(ev.time)}</p>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
