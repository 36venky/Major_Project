/**
 * Badge – Small inline status pill.
 */
const variants = {
  green:  'bg-emerald-50 text-emerald-700 border-emerald-200',
  red:    'bg-red-50 text-red-700 border-red-200',
  amber:  'bg-amber-50 text-amber-700 border-amber-200',
  blue:   'bg-blue-50 text-blue-700 border-blue-200',
  slate:  'bg-slate-100 text-slate-600 border-slate-200',
};

export default function Badge({ label, variant = 'slate', dot = false }) {
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${variants[variant] ?? variants.slate}`}>
      {dot && <span className={`w-1.5 h-1.5 rounded-full ${variant === 'green' ? 'bg-emerald-500' : variant === 'red' ? 'bg-red-500' : variant === 'amber' ? 'bg-amber-500' : 'bg-blue-500'}`} />}
      {label}
    </span>
  );
}
