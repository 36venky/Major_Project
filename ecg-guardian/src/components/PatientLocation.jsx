/**
 * PatientLocation – Interactive patient location management.
 *
 * Features:
 *  - Address text search → Nominatim geocoding → map pan + marker
 *  - Click anywhere on map to place / drag marker → reverse geocode
 *  - Coordinate display (lat / lng)
 *  - Save to backend (PUT /patients/{id}/location)
 *  - Clear location (DELETE /patients/{id}/location)
 *  - "Open in Google Maps" button after save
 *  - Loads existing saved location on mount
 *
 * Uses Leaflet + react-leaflet (OpenStreetMap tiles — no API key needed).
 * Geocoding via Nominatim (free, no key).
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { MapContainer, TileLayer, Marker, useMapEvents, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  MapPin, Search, Save, Trash2, ExternalLink,
  Loader2, CheckCircle, XCircle, Map,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import { getLocation, saveLocation, clearLocation } from '../services/api';

// ── Fix Leaflet's broken default marker icon paths (Vite/webpack issue) ──
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

const NOMINATIM = 'https://nominatim.openstreetmap.org';
const DEFAULT_CENTER = [20.5937, 78.9629]; // India centre
const DEFAULT_ZOOM   = 5;

// ── Helper: fly map to position ───────────────────────────
function FlyTo({ position }) {
  const map = useMap();
  useEffect(() => {
    if (position) map.flyTo(position, 15, { duration: 1.2 });
  }, [position, map]);
  return null;
}

// ── Helper: click-on-map handler ──────────────────────────
function MapClickHandler({ onMapClick }) {
  useMapEvents({
    click(e) {
      onMapClick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

// ── Nominatim fetch with timeout + error handling ─────────
async function nominatimSearch(query) {
  const url = `${NOMINATIM}/search?q=${encodeURIComponent(query)}&format=json&limit=1&addressdetails=1`;
  const res = await fetch(url, {
    headers: { 'Accept-Language': 'en', 'User-Agent': 'ECGGuardian/1.0' },
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) throw new Error('Geocoding service unavailable');
  const data = await res.json();
  if (!data.length) throw new Error('Location not found');
  return { lat: parseFloat(data[0].lat), lng: parseFloat(data[0].lon), display: data[0].display_name };
}

async function nominatimReverse(lat, lng) {
  const url = `${NOMINATIM}/reverse?lat=${lat}&lon=${lng}&format=json`;
  const res = await fetch(url, {
    headers: { 'Accept-Language': 'en', 'User-Agent': 'ECGGuardian/1.0' },
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data.display_name ?? null;
}

// ── Main component ────────────────────────────────────────
export default function PatientLocation() {
  const { state } = useApp();
  const patientId = state.patient?.id || 'P-001';

  // form state
  const [addressInput, setAddressInput] = useState('');
  const [coords,       setCoords]       = useState(null);   // { lat, lng }
  const [displayAddr,  setDisplayAddr]  = useState('');
  const [mapsLink,     setMapsLink]     = useState('');
  const [mapVisible,   setMapVisible]   = useState(false);
  const [flyTarget,    setFlyTarget]    = useState(null);

  // async state
  const [searching, setSearching] = useState(false);
  const [saving,    setSaving]    = useState(false);
  const [clearing,  setClearing]  = useState(false);
  const [saved,     setSaved]     = useState(false);
  const [error,     setError]     = useState('');

  const searchAbortRef = useRef(null);

  // ── Load existing location on mount ──────────────────
  useEffect(() => {
    let cancelled = false;
    getLocation(patientId)
      .then(data => {
        if (cancelled) return;
        if (data.latitude && data.longitude) {
          const c = { lat: data.latitude, lng: data.longitude };
          setCoords(c);
          setDisplayAddr(data.location_address || '');
          setMapsLink(data.maps_link || '');
          setAddressInput(data.location_address || '');
          setFlyTarget([c.lat, c.lng]);
          setMapVisible(true);
        }
      })
      .catch(() => { /* no saved location — silent */ });
    return () => { cancelled = true; };
  }, [patientId]);

  // ── Address search ────────────────────────────────────
  const handleSearch = useCallback(async () => {
    const q = addressInput.trim();
    if (!q) { setError('Please enter an address to search.'); return; }
    if (searchAbortRef.current) searchAbortRef.current.abort();
    setSearching(true);
    setError('');
    try {
      const result = await nominatimSearch(q);
      setCoords({ lat: result.lat, lng: result.lng });
      setDisplayAddr(result.display);
      setFlyTarget([result.lat, result.lng]);
      setMapVisible(true);
      setSaved(false);
    } catch (err) {
      setError(err.message === 'Location not found'
        ? 'Location not found. Try a more specific address.'
        : 'Unable to connect to geocoding service. Check your internet connection.');
    } finally {
      setSearching(false);
    }
  }, [addressInput]);

  // ── Map click / marker drag → reverse geocode ─────────
  const handleMapClick = useCallback(async (lat, lng) => {
    setCoords({ lat, lng });
    setSaved(false);
    setError('');
    try {
      const addr = await nominatimReverse(lat, lng);
      if (addr) {
        setDisplayAddr(addr);
        setAddressInput(addr);
      }
    } catch { /* keep previous address */ }
  }, []);

  // ── Save location ─────────────────────────────────────
  const handleSave = useCallback(async () => {
    if (!coords) { setError('Please select a valid location first.'); return; }
    setSaving(true);
    setError('');
    try {
      const data = await saveLocation(patientId, {
        latitude:         coords.lat,
        longitude:        coords.lng,
        location_address: displayAddr || addressInput || undefined,
      });
      setMapsLink(data.maps_link || '');
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(`Failed to save location: ${err.message}`);
    } finally {
      setSaving(false);
    }
  }, [coords, displayAddr, addressInput, patientId]);

  // ── Clear location ────────────────────────────────────
  const handleClear = useCallback(async () => {
    setClearing(true);
    setError('');
    try {
      await clearLocation(patientId);
      setCoords(null);
      setDisplayAddr('');
      setAddressInput('');
      setMapsLink('');
      setFlyTarget(null);
      setSaved(false);
    } catch (err) {
      setError(`Failed to clear location: ${err.message}`);
    } finally {
      setClearing(false);
    }
  }, [patientId]);

  const hasLocation = coords !== null;

  return (
    <div className="space-y-4">
      {/* ── Header ──────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <MapPin className="w-4 h-4 text-blue-600" />
          <h3 className="text-sm font-semibold text-slate-800">Patient Location</h3>
        </div>
        {hasLocation && (
          <button
            onClick={handleClear}
            disabled={clearing}
            className="flex items-center gap-1 text-xs text-red-500 hover:text-red-700
                       transition-colors disabled:opacity-50"
          >
            {clearing
              ? <Loader2 className="w-3 h-3 animate-spin" />
              : <Trash2 className="w-3 h-3" />}
            Clear Location
          </button>
        )}
      </div>

      {/* ── Address input + buttons ──────────────────── */}
      <div className="flex gap-2">
        <input
          type="text"
          value={addressInput}
          onChange={e => { setAddressInput(e.target.value); setSaved(false); }}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          placeholder="Enter patient address (e.g. 2nd Cross, Chickpet, Bangalore)"
          className="flex-1 text-sm border border-slate-200 rounded-lg px-3 py-2
                     text-slate-800 placeholder:text-slate-400
                     focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400"
        />
      </div>

      <div className="flex gap-2 flex-wrap">
        <button
          onClick={handleSearch}
          disabled={searching}
          className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg
                     bg-blue-600 text-white hover:bg-blue-700 transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {searching
            ? <><Loader2 className="w-4 h-4 animate-spin" /> Searching…</>
            : <><Search className="w-4 h-4" /> Search Location</>}
        </button>

        <button
          onClick={() => setMapVisible(v => !v)}
          className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg
                     border border-slate-200 bg-white text-slate-600
                     hover:bg-slate-50 transition-colors"
        >
          <Map className="w-4 h-4" />
          {mapVisible ? 'Hide Map' : 'Select on Map'}
        </button>
      </div>

      {/* ── Error banner ─────────────────────────────── */}
      {error && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50
                        border border-red-200 rounded-lg px-3 py-2">
          <XCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {/* ── Interactive map ───────────────────────────── */}
      {mapVisible && (
        <div className="rounded-xl overflow-hidden border border-slate-200 shadow-sm"
             style={{ height: 320 }}>
          <MapContainer
            center={flyTarget ?? DEFAULT_CENTER}
            zoom={flyTarget ? 15 : DEFAULT_ZOOM}
            style={{ height: '100%', width: '100%' }}
            scrollWheelZoom
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            {/* Fly to searched / loaded position */}
            {flyTarget && <FlyTo position={flyTarget} />}

            {/* Click handler */}
            <MapClickHandler onMapClick={handleMapClick} />

            {/* Draggable marker */}
            {coords && (
              <Marker
                position={[coords.lat, coords.lng]}
                draggable
                eventHandlers={{
                  dragend(e) {
                    const { lat, lng } = e.target.getLatLng();
                    handleMapClick(lat, lng);
                  },
                }}
              />
            )}
          </MapContainer>
        </div>
      )}

      {/* Map hint */}
      {mapVisible && (
        <p className="text-[11px] text-slate-400">
          Click anywhere on the map or drag the marker to update the location.
        </p>
      )}

      {/* ── Coordinates + address preview ────────────── */}
      {hasLocation && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-3 space-y-1.5">
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>
              <span className="text-slate-400 block">Latitude</span>
              <span className="font-mono font-semibold text-slate-700">
                {coords.lat.toFixed(7)}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block">Longitude</span>
              <span className="font-mono font-semibold text-slate-700">
                {coords.lng.toFixed(7)}
              </span>
            </div>
          </div>
          {displayAddr && (
            <div>
              <span className="text-[10px] text-slate-400 block uppercase tracking-wide">
                Selected Address
              </span>
              <p className="text-xs text-slate-700 leading-relaxed">{displayAddr}</p>
            </div>
          )}
        </div>
      )}

      {/* ── Save button ───────────────────────────────── */}
      {hasLocation && (
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg
                       bg-emerald-600 text-white hover:bg-emerald-700 transition-colors
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</>
              : <><Save className="w-4 h-4" /> Save Location</>}
          </button>

          {/* Saved confirmation */}
          {saved && (
            <span className="flex items-center gap-1.5 text-xs font-medium text-emerald-700
                             bg-emerald-50 border border-emerald-200 px-3 py-1.5 rounded-lg">
              <CheckCircle className="w-3.5 h-3.5" /> Location saved
            </span>
          )}
        </div>
      )}

      {/* ── Open in Google Maps ───────────────────────── */}
      {mapsLink && (
        <a
          href={mapsLink}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 text-sm font-medium text-blue-600
                     hover:text-blue-800 underline underline-offset-2 transition-colors"
        >
          <ExternalLink className="w-4 h-4" />
          Open in Google Maps
        </a>
      )}
    </div>
  );
}
