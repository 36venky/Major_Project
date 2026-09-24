/**
 * HeartRateCard – Displays current BPM with trend arrow and sparkline.
 */
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer, Tooltip } from 'recharts';
import Card from './Card';
import { useApp } from '../context/AppContext';

const statusColor = {
  Normal:       { text: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  Tachycardia:  { text: 'text-red-600',     bg: 'bg-red-50',     border: 'border-red-200' },
  Bradycardia:  { text: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200' },
};

export default function HeartRateCard() {
  const { state } = useApp();
  const hr = state.heartRate;
  const colors = statusColor[hr.status] || statusColor.Normal;
  const sparkData = hr.history.slice(-20).map((v, i) => ({ i, v }));

  const TrendIcon = hr.trend === 'up' ? TrendingUp : hr.trend === 'down' ? TrendingDown : Minus;
  const trendColor = hr.trend === 'up' ? 'text-red-500' : hr.trend === 'down' ? 'text-blue-500' : 'text-slate-400';

  return (
    <Card title="Heart Rate" subtitle="Real-time BPM">
      <div className="flex items-end justify-between gap-4">
        {/* BPM display */}
        <div>
          <div className="flex items-end gap-2 mt-1">
            <span className="text-5xl font-bold text-slate-800 leading-none tabular-nums">
              {hr.current}
            </span>
            <span className="text-sm text-slate-400 mb-1">BPM</span>
            <TrendIcon className={`w-4 h-4 mb-1.5 ${trendColor}`} />
          </div>
          <div className={`inline-flex items-center gap-1.5 mt-2 text-xs font-semibold px-2.5 py-1 rounded-full border
            ${colors.text} ${colors.bg} ${colors.border}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${hr.status === 'Normal' ? 'bg-emerald-500 animate-pulse' : 'bg-current'}`} />
            {hr.status}
          </div>
          <p className="text-[10px] text-slate-400 mt-2">Normal: {hr.normalRange}</p>
        </div>

        {/* Sparkline */}
        <div className="flex-1 h-16">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={sparkData}>
              <Tooltip
                contentStyle={{ fontSize: 10, padding: '2px 6px', border: 'none', background: '#f8fafc' }}
                formatter={(v) => [`${v} BPM`, '']}
                labelFormatter={() => ''}
              />
              <Line
                type="monotone"
                dataKey="v"
                stroke={hr.status === 'Normal' ? '#10b981' : hr.status === 'Tachycardia' ? '#ef4444' : '#f59e0b'}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Card>
  );
}
