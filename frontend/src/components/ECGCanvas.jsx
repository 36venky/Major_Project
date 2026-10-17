/**
 * ECGCanvas – Real-time scrolling ECG waveform rendered on HTML Canvas.
 *
 * Features:
 * - Smooth scrolling green trace on dark ECG grid background
 * - Always draws the freshest samples from the tail of the buffer
 * - Pause / Resume
 * - Zoom (amplitude scale)
 * - Export as PNG
 * - Fullscreen toggle
 */
import { useRef, useEffect, useState, useCallback } from 'react';
import {
  Pause, Play, ZoomIn, ZoomOut, Download, Maximize2, Minimize2
} from 'lucide-react';
import { useApp } from '../context/AppContext';

const TRACE_COLOR  = '#00e676';
const GRID_MAJOR   = '#1a3a2a';
const GRID_MINOR   = '#112a1e';
const BG_COLOR     = '#0a1a10';
const SCROLL_SPEED = 2; // pixels per rAF frame

export default function ECGCanvas() {
  const canvasRef    = useRef(null);
  const containerRef = useRef(null);
  const animRef      = useRef(null);

  // bufferRef always holds the latest slice of ecgData
  const bufferRef  = useRef([]);
  // writeHeadRef tracks how many samples we have already rendered
  const writeHeadRef = useRef(0);

  const pausedRef = useRef(false);
  const zoomRef   = useRef(1);

  const { state } = useApp();
  const [paused, setPaused]         = useState(false);
  const [zoom, setZoom]             = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // ── Keep bufferRef in sync with incoming ecgData ──────────
  useEffect(() => {
    const incoming = state.ecgData;
    // If new data is longer than what we have, accept all of it
    bufferRef.current = incoming;
  }, [state.ecgData]);

  // Sync refs so rAF closure never goes stale
  useEffect(() => { pausedRef.current = paused; }, [paused]);
  useEffect(() => { zoomRef.current = zoom; },   [zoom]);

  /* ── Drawing loop ─────────────────────────────────────────── */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // ── Grid helper ───────────────────────────────────────────
    function drawGrid() {
      const { width, height } = canvas;
      ctx.fillStyle = BG_COLOR;
      ctx.fillRect(0, 0, width, height);
      // Minor grid every 10 px
      ctx.strokeStyle = GRID_MINOR;
      ctx.lineWidth = 0.5;
      for (let x = 0; x < width; x += 10) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
      }
      for (let y = 0; y < height; y += 10) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
      }
      // Major grid every 50 px
      ctx.strokeStyle = GRID_MAJOR;
      ctx.lineWidth = 1;
      for (let x = 0; x < width; x += 50) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
      }
      for (let y = 0; y < height; y += 50) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
      }
    }

    // scrollX accumulates sub-pixel drift so grid stays crisp
    let scrollX = 0;

    function frame() {
      animRef.current = requestAnimationFrame(frame);
      if (pausedRef.current) return;

      const { width, height } = canvas;
      if (width === 0 || height === 0) return; // canvas not visible yet

      const mid = height / 2;
      const buf = bufferRef.current;

      // ── Amplitude scaling ─────────────────────────────────
      let amp = height * 0.38 * zoomRef.current; // fallback
      if (buf.length > 1) {
        const sample = buf.slice(-Math.min(buf.length, 600));
        const vals   = sample.map(p => p.value ?? 0);
        const lo     = Math.min(...vals);
        const hi     = Math.max(...vals);
        const range  = hi - lo;
        if (range > 0.001) {
          amp = (height * 0.38 / (range / 2)) * zoomRef.current;
          amp = Math.max(height * 0.08, Math.min(height * 2.5, amp));
        }
      }

      // ── Scroll canvas left ────────────────────────────────
      const imgData = ctx.getImageData(SCROLL_SPEED, 0, width - SCROLL_SPEED, height);
      ctx.putImageData(imgData, 0, 0);

      // Clear right edge strip
      ctx.fillStyle = BG_COLOR;
      ctx.fillRect(width - SCROLL_SPEED - 1, 0, SCROLL_SPEED + 2, height);

      // Redraw grid at right edge
      scrollX += SCROLL_SPEED;
      const rightStart = width - SCROLL_SPEED;
      for (let x = 0; x < SCROLL_SPEED; x++) {
        const abs = (scrollX - SCROLL_SPEED + x);
        if (abs % 50 === 0) {
          ctx.strokeStyle = GRID_MAJOR; ctx.lineWidth = 1;
        } else if (abs % 10 === 0) {
          ctx.strokeStyle = GRID_MINOR; ctx.lineWidth = 0.5;
        } else continue;
        ctx.beginPath();
        ctx.moveTo(rightStart + x, 0);
        ctx.lineTo(rightStart + x, height);
        ctx.stroke();
      }
      ctx.strokeStyle = GRID_MINOR; ctx.lineWidth = 0.5;
      for (let y = 0; y < height; y += 10) {
        ctx.beginPath(); ctx.moveTo(rightStart, y); ctx.lineTo(width, y); ctx.stroke();
      }
      ctx.strokeStyle = GRID_MAJOR; ctx.lineWidth = 1;
      for (let y = 0; y < height; y += 50) {
        ctx.beginPath(); ctx.moveTo(rightStart, y); ctx.lineTo(width, y); ctx.stroke();
      }

      // ── Draw latest samples at right edge ────────────────
      if (buf.length >= 2) {
        // Take the freshest `SCROLL_SPEED + 1` samples so we connect
        // smoothly from the previous frame edge.
        const needed = SCROLL_SPEED + 1;
        const tail   = buf.slice(-needed);

        ctx.beginPath();
        ctx.strokeStyle = TRACE_COLOR;
        ctx.lineWidth   = 1.8;
        ctx.shadowColor = '#00e676';
        ctx.shadowBlur  = 5;
        ctx.lineJoin    = 'round';
        ctx.lineCap     = 'round';

        tail.forEach((pt, s) => {
          const val = pt.value ?? 0;
          const x   = rightStart + s;          // s=0 is one pixel left of the strip start; close enough
          const y   = mid - val * amp;
          if (s === 0) ctx.moveTo(x, y);
          else         ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.shadowBlur = 0;
      }
    }

    drawGrid();
    animRef.current = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(animRef.current);
  }, []); // runs once; reads mutable refs

  /* ── Resize handler ──────────────────────────────────────── */
  useEffect(() => {
    const obs = new ResizeObserver(() => {
      const canvas    = canvasRef.current;
      const container = containerRef.current;
      if (!canvas || !container) return;
      const w = container.clientWidth;
      const h = container.clientHeight || 260;
      if (w > 0) canvas.width  = w;
      if (h > 0) canvas.height = h;
    });
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  /* ── Controls ────────────────────────────────────────────── */
  const togglePause = () => setPaused(p => !p);
  const adjustZoom  = (dir) =>
    setZoom(z => Math.max(0.5, Math.min(3, parseFloat((z + dir * 0.25).toFixed(2)))));

  const exportImage = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const link    = document.createElement('a');
    link.download = `ecg_${Date.now()}.png`;
    link.href     = canvas.toDataURL('image/png');
    link.click();
  }, []);

  const toggleFullscreen = () => {
    const el = containerRef.current?.parentElement;
    if (!isFullscreen) el?.requestFullscreen?.();
    else               document.exitFullscreen?.();
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
        <button onClick={() => adjustZoom(1)}  className="icon-btn" title="Zoom In">
          <ZoomIn  className="w-4 h-4" />
        </button>
        <button onClick={() => adjustZoom(-1)} className="icon-btn" title="Zoom Out">
          <ZoomOut className="w-4 h-4" />
        </button>
        <button onClick={exportImage}      className="icon-btn" title="Export Image">
          <Download  className="w-4 h-4" />
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

      {/* Canvas container — explicit min-height so ResizeObserver never gets 0 */}
      <div
        ref={containerRef}
        className="relative w-full rounded-xl overflow-hidden"
        style={{ height: 260, minHeight: 260 }}
      >
        <canvas
          ref={canvasRef}
          width={800}
          height={260}
          className="w-full h-full"
          style={{ display: 'block' }}
        />
      </div>
    </div>
  );
}
