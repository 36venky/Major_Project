/**
 * SidebarContext – provides sidebar open/closed state.
 * Persists preference to localStorage so it survives page refreshes.
 */
import { createContext, useContext, useState, useCallback } from 'react';

const LS_KEY = 'ecg_sidebar_open';

const SidebarContext = createContext(null);

export function SidebarProvider({ children }) {
  const [open, setOpen] = useState(() => {
    try {
      const v = localStorage.getItem(LS_KEY);
      return v === null ? true : v === 'true';
    } catch {
      return true;
    }
  });

  const toggle = useCallback(() => {
    setOpen(prev => {
      const next = !prev;
      try { localStorage.setItem(LS_KEY, String(next)); } catch { /* ignore */ }
      return next;
    });
  }, []);

  return (
    <SidebarContext.Provider value={{ open, toggle }}>
      {children}
    </SidebarContext.Provider>
  );
}

export function useSidebar() {
  const ctx = useContext(SidebarContext);
  if (!ctx) throw new Error('useSidebar must be inside SidebarProvider');
  return ctx;
}
