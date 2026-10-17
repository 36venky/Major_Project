/**
 * RiskChart – Risk % vs Day using Plotly.
 * Fetches history from GET /patients/{id}/risk/history.
 * Falls back to empty-state if < 2 data points.
 */
import { useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import { useApp } from '../context/AppContext';
import { getAuthHeaders } from '../services/auth';
import { BASE_URL as API_BASE } from '../services/apiClient';

export default function RiskChart() {
  const { state } = useApp();
  // patient may be null while the backend fetch is in-flight or DB is empty
  const patientId = state.patient?.id ?? null;

  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  useEffect(() => {
    if (!patientId) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    getAuthHeaders().then(headers => {
      fetch(`${API_BASE}/patients/${patientId}/risk/history`, {
        headers: {
          ...headers,
          'ngrok-skip-browser-warning': 'true',
        },
      })
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.json();
        })
        .then(data => {
          if (cancelled) return;
          setHistory(Array.isArray(data) ? data : []);
          setLoading(false);
        })
        .catch(err => {
          if (cancelled) return;
          setError(err.message);
          setLoading(false);
        });
    });

    return () => { cancelled = true; };
  }, [patientId]); // only re-fetch when patient changes, not on every WS frame

  if (loading) {
    return (
      <div className="h-52 flex items-center justify-center text-slate-400 text-sm">
        Loading risk history…
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-52 flex items-center justify-center text-red-400 text-sm">
        Failed to load risk history
      </div>
    );
  }

  if (history.length < 2) {
    return (
      <div className="h-52 flex flex-col items-center justify-center text-slate-400 text-sm text-center px-6 gap-2">
        <span className="text-2xl">📊</span>
        <p className="font-medium text-slate-500">No risk history yet</p>
        <p className="text-xs text-slate-400">
          Click <strong>Start</strong> to begin a monitoring session.<br />
          Risk predictions will appear here as data accumulates.
        </p>
      </div>
    );
  }

  const xs     = history.map(r => new Date(r.timestamp).toLocaleDateString());
  const ys     = history.map(r => r.risk_percentage);
  const labels = history.map(r => r.risk_level);
  const colors = history.map(r =>
    r.risk_level === 'High' ? '#ef4444' :
    r.risk_level === 'Moderate' ? '#f59e0b' : '#10b981'
  );

  return (
    <Plot
      data={[{
        x: xs,
        y: ys,
        type: 'scatter',
        mode: 'lines+markers',
        line:    { color: '#6366f1', width: 2 },
        marker:  { color: colors, size: 7 },
        text:    labels,
        hovertemplate: '<b>%{x}</b><br>Risk: %{y:.1f}%<br>Level: %{text}<extra></extra>',
      }]}
      layout={{
        autosize: true,
        margin:   { t: 8, b: 40, l: 48, r: 8 },
        paper_bgcolor: 'transparent',
        plot_bgcolor:  'transparent',
        xaxis: {
          title:     { text: 'Date', font: { size: 11, color: '#64748b' } },
          gridcolor:  '#e2e8f0',
          tickfont:   { size: 10, color: '#94a3b8' },
        },
        yaxis: {
          range:     [0, 100],
          title:     { text: 'Risk %', font: { size: 11, color: '#64748b' } },
          gridcolor:  '#e2e8f0',
          tickfont:   { size: 10, color: '#94a3b8' },
        },
        showlegend: false,
      }}
      config={{
        displayModeBar: true,
        modeBarButtonsToRemove: ['select2d', 'lasso2d', 'toImage'],
        responsive: true,
      }}
      style={{ width: '100%', height: 210 }}
      useResizeHandler
    />
  );
}
