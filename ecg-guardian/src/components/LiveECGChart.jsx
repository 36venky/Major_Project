/**
 * LiveECGChart – Real-time scrolling ECG using Plotly.
 *
 * Reads ecgData from AppContext (populated by useWebSocket).
 * Keeps a sliding window of `windowSeconds` seconds worth of samples.
 * Shows ⚠ Disconnected overlay when backend is offline.
 */
import { useRef, useEffect, useState, useCallback } from 'react';
import Plot from 'react-plotly.js';
import { Pause, Play, ZoomIn, ZoomOut, Download } from 'lucide-react';
import { useApp } from '../context/AppContext';

const SAMPLING_RATE   = 250;   // Hz – matches backend
const DEFAULT_WINDOW  = 10;    // seconds visible

export default function LiveECGChart({ windowSeconds = DEFAULT_WINDOW }) {
  const { state } = useApp();
  const [paused, setPaused]       = useState(false);
  const [zoom, setZoom]           = useState(1);
  const [noData, setNoData]       = useState(false);

  const pausedRef        = useRef(false);
  const frozenDataRef    = useRef(null);   // snapshot taken when paused
  const noDataTimerRef   = useRef(null);
  const maxPoints        = windowSeconds * SAMPLING_RATE;

  // Keep paused ref in sync
  useEffect(() => { pausedRef.current = paused; }, [paused]);

  // No-data watchdog: set noData=true after 5 s of empty ecgData
  useEffect(() => {
    clearTimeout(noDataTimerRef.current);
    if (state.ecgData.length === 0) {
      noDataTimerRef.current = setTimeout(() => setNoData(true), 5000);
    } else {
      setNoData(false);
    }
    return () => clearTimeout(noDataTimerRef.current);
  }, [state.ecgData]);

  // Freeze data when pausing
  useEffect(() => {
    if (paused && frozenDataRef.current === null) {
      frozenDataRef.current = state.ecgData.slice(-maxPoints);
    }
    if (!paused) {
      frozenDataRef.current = null;
    }
  }, [paused]);

  // Build the displayed dataset
  const displayData = paused && frozenDataRef.current
    ? frozenDataRef.current
    : state.ecgData.slice(-maxPoints);

  const xs = displayData.map((_, i) => (i / SAMPLING_RATE).toFixed(3));
  const ys = displayData.map(d => (d.value ?? 0) * zoom);

  const xMax = displayData.length / SAMPLING_RATE;
  const xMin = Math.max(0, xMax - windowSeconds);

  // Auto-scale Y-axis from actual data with 15% padding
  const yRaw = displayData.map(d => (d.value ?? 0) * zoom);
  let yMin = -1.2, yMax = 1.2;  // sensible defaults when no data
  if (yRaw.length > 0) {
    const dataMin = Math.min(...yRaw);
    const dataMax = Math.max(...yRaw);
    const pad = Math.max((dataMax - dataMin) * 0.15, 0.05);
    yMin = dataMin - pad;
    yMax = dataMax + pad;
  }

  const exportCSV = useCallback(() => {
    const rows = displayData.map(d => `${d.time},${d.value}`).join('\n');
    const blob  = new Blob([`timestamp,value\n${rows}`], { type: 'text/csv' });
    const url   = URL.createObjectURL(blob);
    const a     = document.createElement('a');
    a.href      = url;
    a.download  = `ecg_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [displayData]);

  const isDisconnected = !state.device.connected;

  return (
    <div className="flex flex-col gap-3">
      {/* Controls */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setPaused(p => !p)}
          className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors
            ${paused
              ? 'bg-blue-600 text-white border-blue-600 hover:bg-blue-700'
              : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}`}
        >
          {paused ? <><Play className="w-3 h-3" />Resume</> : <><Pause className="w-3 h-3" />Pause</>}
        </button>

        <button
          onClick={() => setZoom(z => Math.min(3, parseFloat((z + 0.25).toFixed(2))))}
          title="Zoom In"
          className="icon-btn"
        ><ZoomIn className="w-4 h-4" /></button>

        <button
          onClick={() => setZoom(z => Math.max(0.5, parseFloat((z - 0.25).toFixed(2))))}
          title="Zoom Out"
          className="icon-btn"
        ><ZoomOut className="w-4 h-4" /></button>

        <button onClick={exportCSV} title="Export CSV" className="icon-btn">
          <Download className="w-4 h-4" />
        </button>

        <div className="ml-auto flex items-center gap-3 text-xs text-slate-400">
          <span className="flex items-center gap-1">
            <span className={`w-2 h-2 rounded-full ${isDisconnected ? 'bg-red-400' : 'bg-emerald-400 animate-pulse'}`} />
            {isDisconnected ? 'Disconnected' : `${state.heartRate.current} BPM`}
          </span>
          <span>Zoom {zoom.toFixed(2)}×</span>
          <span>Window {windowSeconds}s</span>
        </div>
      </div>

      {/* Chart */}
      <div className="relative w-full" style={{ height: 240 }}>
        {noData && !isDisconnected && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-900/80 rounded-xl z-10 text-slate-400 text-sm">
            No data received
          </div>
        )}
        {isDisconnected && (
          <div className="absolute top-2 left-1/2 -translate-x-1/2 z-10 bg-red-600 text-white text-xs font-semibold px-3 py-1 rounded-full shadow">
            ⚠ Disconnected — reconnecting…
          </div>
        )}
        {paused && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/30 rounded-xl z-10 text-white text-sm font-semibold tracking-wide pointer-events-none">
            ⏸ PAUSED
          </div>
        )}

        <Plot
          data={[{
            x: xs,
            y: ys,
            type: 'scatter',
            mode: 'lines',
            line: { color: '#00e676', width: 1.5 },
            hovertemplate: '%{y:.3f}<extra></extra>',
          }]}
          layout={{
            autosize: true,
            margin:   { t: 8, b: 32, l: 48, r: 8 },
            paper_bgcolor: '#0a1a10',
            plot_bgcolor:  '#0a1a10',
            xaxis: {
              range:      [xMin.toFixed(3), xMax.toFixed(3)],
              title:      { text: 'Time (s)', font: { color: '#4ade80', size: 11 } },
              gridcolor:  '#1a3a2a',
              zerolinecolor: '#1a3a2a',
              tickfont:   { color: '#4ade80', size: 10 },
              fixedrange: false,
            },
            yaxis: {
              range:      [yMin, yMax],
              title:      { text: 'Amplitude', font: { color: '#4ade80', size: 11 } },
              gridcolor:  '#1a3a2a',
              zerolinecolor: '#1a3a2a',
              tickfont:   { color: '#4ade80', size: 10 },
              fixedrange: false,
            },
            showlegend: false,
          }}
          config={{
            displayModeBar: false,
            responsive:     true,
          }}
          style={{ width: '100%', height: '100%' }}
          useResizeHandler
        />
      </div>

      <style>{`
        .icon-btn {
          width:32px;height:32px;
          display:flex;align-items:center;justify-content:center;
          border-radius:8px;border:1px solid #e2e8f0;
          background:white;color:#64748b;
          cursor:pointer;transition:background 0.15s;
        }
        .icon-btn:hover{background:#f1f5f9;}
      `}</style>
    </div>
  );
}
