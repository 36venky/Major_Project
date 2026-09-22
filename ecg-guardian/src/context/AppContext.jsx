/**
 * AppContext – Global application state.
 *
 * Auth persistence
 * ────────────────
 * Tokens + user profile live in localStorage so the user stays logged in
 * across page refreshes and browser restarts (handled by auth.js / App.jsx).
 *
 * Patient persistence — REMOVED
 * ──────────────────────────────
 * The active patient is NOT stored in localStorage.  It is always fetched
 * fresh from GET /patients after login.  This prevents stale patient IDs
 * (e.g. from a previous database) from breaking the UI.
 *
 * On every login / page load:
 *   - listPatients() is called once authUser is set
 *   - The first patient in the list becomes the active patient
 *   - If no patients exist yet, patient is null
 *
 * LOGOUT resets all state including authUser and patient.
 */
import { createContext, useContext, useReducer, useCallback, useRef, useEffect } from 'react';
import { getUserInfo } from '../services/auth';
import { listPatients } from '../services/api';

// Hydrate auth user from localStorage on page load (tokens are in localStorage)
const _savedUser = getUserInfo();

const initialState = {
  authUser:       _savedUser || null,
  patient:        null,          // always fetched from backend — never persisted
  patientList:    [],
  patientLoading: false,
  patientError:   null,
  device: {
    connected:          false,
    hardwareConnected:  false,   // true only when a real ESP32 is on /ws/device
    port:               'WiFi (ESP32)',
    samplingRate:       '250 Hz',
    signalQuality:      0,
    monitoringDuration: '00:00:00',
    status:             'Connecting…',
  },
  heartRate: {
    current:     0,
    status:      'Unknown',
    normalRange: '60–100 BPM',
    trend:       'stable',
    history:     [],
  },
  weeklyHealth: {
    bloodPressure: null,
    bloodSugar:    null,
    lastUpdated:   null,
  },
  aiAnalysis: {
    rhythm:         null,
    confidence:     null,
    riskLevel:      null,
    heartRateTrend: 'Stable',
    signalQuality:  'Good',
    recentEvents:   [],
  },
  riskPrediction: null,
  alerts:         [],
  timeline:       [],
  ecgData:        [],
  isMonitoring:   false,
  isPaused:       false,
  notifications:  [],
};

function appReducer(state, action) {
  switch (action.type) {
    case 'SET_ECG_DATA':
      return { ...state, ecgData: action.payload };

    case 'APPEND_ECG':
      return { ...state, ecgData: [...state.ecgData.slice(-2500), ...action.payload] };

    case 'SET_HEART_RATE': {
      const prev = state.heartRate.current;
      const next = action.payload;
      return {
        ...state,
        heartRate: {
          ...state.heartRate,
          current: next,
          trend:   next > prev + 3 ? 'up' : next < prev - 3 ? 'down' : 'stable',
          history: [...state.heartRate.history.slice(-59), next],
          status:  next <= 60 ? 'Bradycardia' : next >= 100 ? 'Tachycardia' : 'Normal',
        },
      };
    }

    case 'SET_AI_ANALYSIS':
      return { ...state, aiAnalysis: { ...state.aiAnalysis, ...action.payload } };

    case 'SET_RISK_PREDICTION':
      return { ...state, riskPrediction: action.payload };

    case 'ADD_ALERT':
      return { ...state, alerts: [action.payload, ...state.alerts] };

    case 'DISMISS_ALERT':
      return {
        ...state,
        alerts: state.alerts.map(a =>
          a.id === action.payload ? { ...a, status: 'dismissed' } : a
        ),
      };

    case 'ADD_TIMELINE_EVENT':
      return { ...state, timeline: [action.payload, ...state.timeline] };

    case 'SET_MONITORING':
      return { ...state, isMonitoring: action.payload };

    case 'SET_PAUSED':
      return { ...state, isPaused: action.payload };

    case 'UPDATE_WEEKLY_HEALTH':
      return { ...state, weeklyHealth: { ...action.payload, lastUpdated: new Date().toISOString() } };

    case 'UPDATE_PATIENT':
      return { ...state, patient: { ...state.patient, ...action.payload } };

    case 'SET_PATIENT':
      return { ...state, patient: action.payload, patientError: null };

    case 'SET_PATIENT_LOADING':
      return { ...state, patientLoading: action.payload };

    case 'SET_PATIENT_ERROR':
      return { ...state, patientError: action.payload, patientLoading: false };

    case 'ADD_PATIENT_TO_LIST': {
      const exists = state.patientList.some(p => p.id === action.payload.id);
      return {
        ...state,
        patientList: exists
          ? state.patientList.map(p => p.id === action.payload.id ? action.payload : p)
          : [action.payload, ...state.patientList],
      };
    }

    case 'SET_PATIENT_LIST':
      return { ...state, patientList: action.payload };

    case 'UPDATE_DEVICE':
      return { ...state, device: { ...state.device, ...action.payload } };

    case 'ADD_NOTIFICATION':
      return { ...state, notifications: [action.payload, ...state.notifications.slice(0, 9)] };

    case 'CLEAR_NOTIFICATION':
      return { ...state, notifications: state.notifications.filter(n => n.id !== action.payload) };

    case 'SET_AUTH_USER':
      return { ...state, authUser: action.payload };

    case 'LOGOUT':
      return {
        ...initialState,
        authUser:       null,
        patient:        null,
        patientList:    [],
        patientLoading: false,
        patientError:   null,
      };

    default:
      return state;
  }
}

const AppContext = createContext(null);

// ── Backend → camelCase mapper (single source of truth) ───
export function patientFromBackend(b) {
  return {
    id:               b.patient_id,
    name:             b.name,
    age:              b.age,
    dob:              b.dob              ?? null,
    gender:           b.gender,
    bloodGroup:       b.blood_group,
    height:           b.height          ?? '',
    weight:           b.weight          ?? '',
    // Guardian
    guardianName:     b.guardian_name     ?? '',
    guardianPhone:    b.guardian_phone    ?? '',
    guardianRelation: b.guardian_relation ?? '',
    // Patient contact
    phone:            b.phone             ?? '',
    emergencyContact: b.emergency_contact ?? '',
    // Doctor
    doctorName:       b.doctor_name       ?? '',
    doctorHospital:   b.doctor_hospital   ?? '',
    doctorPhone:      b.doctor_phone      ?? '',
    // Ambulance
    ambulanceName:    b.ambulance_name    ?? '',
    ambulancePhone:   b.ambulance_phone   ?? '',
    // Medical
    diseases:         b.diseases    ?? '',
    medications:      b.medications ?? '',
    allergies:        b.allergies   ?? '',
    notes:            b.notes       ?? '',
    // Address / location
    address:          b.address          ?? '',
    location:         b.location         ?? null,
    locationAddress:  b.location_address ?? null,
    mapsLink:         b.maps_link        ?? null,
    createdAt:        b.created_at,
  };
}

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(appReducer, initialState);
  const wsRef = useRef(null);

  /**
   * refreshPatients — fetches GET /patients and sets the first patient as active.
   * Called once when authUser is set (login or page refresh with valid token).
   */
  const refreshPatients = useCallback(async () => {
    if (!state.authUser) return;
    dispatch({ type: 'SET_PATIENT_LOADING', payload: true });
    try {
      const patients = await listPatients();
      const mapped   = patients.map(patientFromBackend);
      dispatch({ type: 'SET_PATIENT_LIST', payload: mapped });
      // Always use the first patient — no localStorage preference
      dispatch({ type: 'SET_PATIENT', payload: mapped.length > 0 ? mapped[0] : null });
      dispatch({ type: 'SET_PATIENT_LOADING', payload: false });
    } catch (err) {
      dispatch({ type: 'SET_PATIENT_ERROR', payload: err.message });
    }
  }, [state.authUser]);

  // Fetch patients once when auth state becomes available
  useEffect(() => {
    if (state.authUser) {
      refreshPatients();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.authUser]);

  const addAlert = useCallback((alert) => {
    const id = `a-${Date.now()}`;
    dispatch({ type: 'ADD_ALERT',        payload: { id, time: new Date().toISOString(), status: 'active', ...alert } });
    dispatch({ type: 'ADD_NOTIFICATION', payload: { id, title: alert.title, description: alert.description, severity: alert.severity, time: new Date().toISOString() } });
  }, []);

  const addTimelineEvent = useCallback((event) => {
    dispatch({
      type: 'ADD_TIMELINE_EVENT',
      payload: { id: `t-${Date.now()}`, time: new Date().toISOString(), ...event },
    });
  }, []);

  return (
    <AppContext.Provider value={{ state, dispatch, wsRef, addAlert, addTimelineEvent, refreshPatients }}>
      {children}
    </AppContext.Provider>
  );
}

export const useApp = () => {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
};
