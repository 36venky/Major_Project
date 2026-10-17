/**
 * helpers.js – Shared utility functions.
 */

/** Format ISO timestamp to "Jul 16, 2026 · 10:45 AM" */
export function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  });
}

/** Format ISO timestamp to "10:45 AM" */
export function formatTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  });
}

/** Returns Tailwind color classes for severity level */
export function severityColor(severity) {
  switch (severity) {
    case 'critical': return { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-700', badge: 'bg-red-100 text-red-700', dot: 'bg-red-500' };
    case 'warning':  return { bg: 'bg-amber-50', border: 'border-amber-200', text: 'text-amber-700', badge: 'bg-amber-100 text-amber-700', dot: 'bg-amber-500' };
    case 'low':
    case 'info':     return { bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-700', badge: 'bg-blue-100 text-blue-700', dot: 'bg-blue-500' };
    default:         return { bg: 'bg-slate-50', border: 'border-slate-200', text: 'text-slate-700', badge: 'bg-slate-100 text-slate-700', dot: 'bg-slate-400' };
  }
}

/** Returns color classes for risk level */
export function riskColor(risk) {
  switch (risk?.toLowerCase()) {
    case 'low':      return 'text-emerald-600 bg-emerald-50';
    case 'medium':   return 'text-amber-600 bg-amber-50';
    case 'high':     return 'text-red-600 bg-red-50';
    case 'critical': return 'text-red-700 bg-red-100';
    default:         return 'text-slate-600 bg-slate-50';
  }
}

/** Clamp a number between min and max */
export const clamp = (val, min, max) => Math.min(Math.max(val, min), max);

/** Generate unique ID */
export const uid = () => `id-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
