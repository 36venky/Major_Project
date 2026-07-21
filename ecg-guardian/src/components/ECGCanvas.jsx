/**
 * ECGCanvas – Real-time scrolling ECG waveform rendered on HTML Canvas.
 *
 * Features:
 * - Smooth scrolling green trace on dark ECG grid background
 * - Pause / Resume
 * - Zoom (amplitude scale)
 * - Export as PNG
 * - Fullscreen toggle
 * - Displays sampling frequency and current BPM
 */
import { useRef, useEffect, useState, useCallback } from 'react';
import {
  Pause, Play, ZoomIn, ZoomOut, Download, Maximize2, Minimize2
} from 'lucide-react';
import { useApp } from '../context/AppContext';

const TRACE_COLOR = '#00e676';
const GRID_MAJOR = '#1a3a2a';
const GRID_MINOR = '#112a1e';
const BG_COLOR   = '#0a1a10';
const SCROLL_SPEED = 2; // pixels per frame

export default function ECGCanvas() {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const animRef = useRef(null);
  const bufferRef = useRef([]);
  const posRef = useRef(0);       // current x draw position
  const pausedRef = useRef(false);
  const zoomRef = useRef(1);

  const { state } = useApp();
  const [paused, setPaused] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Feed new ECG data into local buffer
  useEffect(() => {
    bufferRef.current = state.ecgData.slice(-600);
  }, [state.ecgData]);

  // Sync refs with state (avoid stale closures in rAF)
  useEffect(() => { pausedRef.current = paused; }, [paused]);
  useEffect(() => { zoomRef.current = zoom; }, [zoom]);

  /* ── Drawing loop ──────────────────────────────────────── */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    function drawGrid() {
      const { width, height } = canvas;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = BG_COLOR;
      ctx.fillRect(0, 0, width, height);

      // Minor grid (small squares, 10px)
      ctx.strokeStyle = GRID_MINOR;
      ctx.lineWidth = 0.5;
      for (let x = 0; x < width; x += 10) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
      }
      for (let y = 0; y < height; y += 10) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
      }
      // Major grid (50px)
      ctx.strokeStyle = GRID_MAJOR;
      ctx.lineWidth = 1;
      for (let x = 0; x < width; x += 50) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
      }
      for (let y = 0; y < height; y += 50) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
      }
    }

    let prevImageData = null;
    let localPos = 0;
    let dataIdx = 0;

    function frame() {
      animRef.current = requestAnimationFrame(frame);
      if (pausedRef.current) return;

      const { width, height } = canvas;
      const mid = height / 2;
      const amp = (height * 0.38) * zoomRef.current;

      // Scroll existing content left by SCROLL_SPEED pixels
      const imageData = ctx.getImageData(SCROLL_SPEED, 0, width - SCROLL_SPEED, height);
      ctx.putImageData(imageData, 0, 0);

      // Clear the right edge strip
      ctx.fillStyle = BG_COLOR;
      ctx.fillRect(width - SCROLL_SPEED - 1, 0, SCROLL_SPEED + 2, height);

      // Redraw vertical grid lines at right edge
      const rightStart = width - SCROLL_SPEED;
      for (let x = 0; x < SCROLL_SPEED; x++) {
        const absX = (localPos + x) % 50;
        if (absX === 0) {
          ctx.strokeStyle = GRID_MAJOR;
          ctx.lineWidth = 1;
        } else if ((localPos + x) % 10 === 0) {
          ctx.strokeStyle = GRID_MINOR;
          ctx.lineWidth = 0.5;
        } else continue;
        ctx.beginPath();
        ctx.moveTo(rightStart + x, 0);
        ctx.lineTo(rightStart + x, height);
        ctx.stroke();
      }
      // Horizontal grid lines redraw
      ctx.strokeStyle = GRID_MINOR;
      ctx.lineWidth = 0.5;
      for (let y = 0; y < height; y += 10) {
        ctx.beginPath(); ctx.moveTo(rightStart, y); ctx.lineTo(width, y); ctx.stroke();
      }
      ctx.strokeStyle = GRID_MAJOR;
      ctx.lineWidth = 1;
      for (let y = 0; y < height; y += 50) {
        ctx.beginPath(); ctx.moveTo(rightStart, y); ctx.lineTo(width, y); ctx.stroke();
      }

      // Draw new ECG trace at right edge
      const buf = bufferRef.current;
      if (buf.length > 1) {
        ctx.beginPath();
        ctx.strokeStyle = TRACE_COLOR;
        ctx.lineWidth = 1.5;
        ctx.shadowColor = '#00e676';
        ctx.shadowBlur = 4;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';

        const step = SCROLL_SPEED;
        for (let s = 0; s < step; s++) {
          const i = (dataIdx + s) % buf.length;
          const val = buf[i]?.value ?? 0;
          const y = mid - val * amp;
          if (s === 0) ctx.moveTo(width - step + s, y);
          else ctx.lineTo(width - step + s, y);
        }
        ctx.stroke();
        ctx.shadowBlur = 0;
        dataIdx = (dataIdx + step) % buf.length;
      }

      localPos += SCROLL_SPEED;
    }

    drawGrid();
    animRef.current = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(animRef.current);
  }, []);

  /* ── Resize handler ────────────────────────────────────── */
  useEffect(() => {
    const obs = new ResizeObserver(() => {
      const canvas = canvasRef.current;
      const container = containerRef.current;
      if (canvas && container) {
        canvas.width = container.clientWidth;
        canvas.height = container.clientHeight;
      }
    });
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  /* ── Controls ──────────────────────────────────────────── */
  const togglePause = () => setPaused(p => !p);

  const adjustZoom = (dir) => {
    setZoom(z => Math.max(0.5, Math.min(3, z + dir * 0.25)));
  };

  const exportImage = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const link = document.createElement('a');
    link.download = `ecg_${Date.now()}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  }, []);

  const toggleFullscreen = () => {
    const el = containerRef.current?.parentElement;
    if (!isFullscreen) {
      el?.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
    setIsFullscreen(p => !p);
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Controls bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={togglePause}
          className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors
            ${paused
              ? 'bg-blue-600 text-white border-blue-600 hover:bg-blue-700'
              : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
            }`}
        >
          {paused ? <><Play className="w-3 h-3" /> Resume</> : <><Pause className="w-3 h-3" /> Pause</>}
        </button>
        <button onClick={() => adjustZoom(1)} className="icon-btn" title="Zoom In">
          <ZoomIn className="w-4 h-4" />
        </button>
        <button onClick={() => adjustZoom(-1)} className="icon-btn" title="Zoom Out">
          <ZoomOut className="w-4 h-4" />
        </button>
        <button onClick={exportImage} className="icon-btn" title="Export Image">
          <Download className="w-4 h-4" />
        </button>
        <button onClick={toggleFullscreen} className="icon-btn" title="Fullscreen">
          {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
        </button>

        <div className="ml-auto flex items-center gap-3 text-xs text-slate-400">
          <span>Fs: {state.device.samplingRate}</span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            {state.heartRate.current} BPM
          </span>
          <span>Zoom: {zoom.toFixed(2)}×</span>
        </div>
      </div>

      {/* Canvas */}
      <div ref={containerRef} className="relative w-full rounded-xl overflow-hidden" style={{ height: 220 }}>
        <canvas
          ref={canvasRef}
          width={800}
          height={220}
          className="w-full h-full"
          style={{ display: 'block' }}
        />
        {paused && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/40 text-white text-sm font-semibold tracking-wide rounded-xl">
            ⏸ PAUSED
          </div>
        )}
      </div>

      {/* Inline style for icon buttons */}
      <style>{`
        .icon-btn {
          width: 30px; height: 30px;
          display: flex; align-items: center; justify-content: center;
          border-radius: 8px; border: 1px solid #e2e8f0;
          background: white; color: #64748b;
          cursor: pointer; transition: background 0.15s;
        }
        .icon-btn:hover { background: #f1f5f9; }
      `}</style>
    </div>
  );
}
