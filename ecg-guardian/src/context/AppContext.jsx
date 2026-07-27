/**
 * AppContext – Global application state.
 * Added: riskPrediction, patientList, ADD_PATIENT_TO_LIST, SET_RISK_PREDICTION
 */
import { createContext, useContext, useReducer, useCallback, useRef } from 'react';

const initialState = {
  patient: {
    id:               'P-001',
    name:             'Arjun Sharma',
    age:              45,
    gender:           'Male',
    bloodGroup:       'B+',
    height:           '172 cm',
    weight:           '74 kg',
    guardianName:     'Priya Sharma',
    emergencyContact: '+91 98765 43210',
  },
  patientList: [],   // all registered patients (for selector)
  device: {
    connected:         true,
    port:              'COM6',
    samplingRate:      '250 Hz',
    signalQuality:     92,
    monitoringDuration:'00:00:00',
    status:            'Active',
  },
  heartRate: {
    current:     72,
    status:      'Normal',
    normalRange: '60–100 BPM',
    trend:       'stable',
    history:     [],
  },
  weeklyHealth: {
    bloodPressure: '118/76 mmHg',
    bloodSugar:    '98 mg/dL',
    lastUpdated:   new Date().toISOString(),
  },
  aiAnalysis: {
    rhythm:         null,
    confidence:     null,
    riskLevel:      null,
    heartRateTrend: 'Stable',
    signalQuality:  'Good',
    recentEvents:   [],
  },
  riskPrediction: null,  // { risk_percentage, risk_level, timestamp, majority_label }
  alerts: [
    {
      id: 'a1', type: 'info', severity: 'low',
      title: 'Monitoring Started',
      description: 'ECG monitoring session has begun.',
      time: new Date().toISOString(), status: 'active',
    },
  ],
  timeline: [
    { id: 't1', event: 'Monitoring Started', time: new Date().toISOString(), icon: 'play', color: 'green' },
  ],
  ecgData:       [],
  isMonitoring:  true,
  isPaused:      false,
  notifications: [],
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
          trend: next > prev + 3 ? 'up' : next < prev - 3 ? 'down' : 'stable',
          history: [...state.heartRate.history.slice(-59), next],
          status: next <= 60 ? 'Bradycardia' : next >= 100 ? 'Tachycardia' : 'Normal',
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

    case 'ADD_PATIENT_TO_LIST': {
      // Add new patient to patientList, avoid duplicates
      const exists = state.patientList.some(p => p.patient_id === action.payload.patient_id);
      return {
        ...state,
        patientList: exists
          ? state.patientList.map(p => p.patient_id === action.payload.patient_id ? action.payload : p)
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

    default:
      return state;
  }
}

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(appReducer, initialState);
  const wsRef = useRef(null);

  const addAlert = useCallback((alert) => {
    const id = `a-${Date.now()}`;
    dispatch({ type: 'ADD_ALERT', payload: { id, time: new Date().toISOString(), status: 'active', ...alert } });
    dispatch({
      type: 'ADD_NOTIFICATION',
      payload: { id, title: alert.title, description: alert.description, severity: alert.severity, time: new Date().toISOString() },
    });
  }, []);

  const addTimelineEvent = useCallback((event) => {
    dispatch({
      type: 'ADD_TIMELINE_EVENT',
      payload: { id: `t-${Date.now()}`, time: new Date().toISOString(), ...event },
    });
  }, []);

  return (
    <AppContext.Provider value={{ state, dispatch, wsRef, addAlert, addTimelineEvent }}>
      {children}
    </AppContext.Provider>
  );
}

export const useApp = () => {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used within AppProvider');
  return ctx;
};
