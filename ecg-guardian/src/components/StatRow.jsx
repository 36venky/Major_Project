/**
 * StatRow – A labeled key-value row used in info cards.
 */
export default function StatRow({ label, value, valueClass = 'text-slate-800' }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-50 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-xs font-semibold ${valueClass}`}>{value ?? '—'}</span>
    </div>
  );
}
