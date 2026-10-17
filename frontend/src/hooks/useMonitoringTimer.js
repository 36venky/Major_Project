/**
 * useMonitoringTimer – Tracks elapsed monitoring duration.
 * Updates device.monitoringDuration in global state every second.
 */
import { useEffect, useRef } from 'react';
import { useApp } from '../context/AppContext';

function formatDuration(seconds) {
  const h = String(Math.floor(seconds / 3600)).padStart(2, '0');
  const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
  const s = String(seconds % 60).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

export function useMonitoringTimer() {
  const { state, dispatch } = useApp();
  const secondsRef = useRef(0);
  const timerRef = useRef(null);

  useEffect(() => {
    if (state.isMonitoring && !state.isPaused) {
      timerRef.current = setInterval(() => {
        secondsRef.current += 1;
        dispatch({
          type: 'UPDATE_DEVICE',
          payload: { monitoringDuration: formatDuration(secondsRef.current) },
        });
      }, 1000);
    } else {
      clearInterval(timerRef.current);
    }
    return () => clearInterval(timerRef.current);
  }, [state.isMonitoring, state.isPaused, dispatch]);
}
