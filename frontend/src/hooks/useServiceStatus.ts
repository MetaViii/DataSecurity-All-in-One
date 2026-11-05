import { useCallback, useEffect, useRef, useState } from 'react';
import { setToken } from '../api';

// Restoring a server session refreshes its token without replacing the graph.
export function useServiceStatus(ready: boolean) {
  const [connected, setConnected] = useState(true);
  const wasDisconnected = useRef(false);
  const pending = useRef<AbortController | null>(null);
  const check = useCallback(async () => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    const timeout = setTimeout(() => controller.abort(), 3500);
    try {
      const response = await fetch('/api/health', { signal: controller.signal, cache: 'no-store' });
      if (!response.ok || !(await response.json()).ok) throw new Error('unavailable');
      if (wasDisconnected.current) {
        const restored = await fetch('/api/bootstrap', {
          signal: controller.signal,
          cache: 'no-store',
        });
        if (!restored.ok) throw new Error('unavailable');
        setToken((await restored.json()).token);
      }
      wasDisconnected.current = false;
      setConnected(true);
    } catch {
      if (pending.current === controller) {
        wasDisconnected.current = true;
        setConnected(false);
      }
    } finally {
      clearTimeout(timeout);
      if (pending.current === controller) pending.current = null;
    }
  }, []);
  useEffect(() => {
    if (!ready) return;
    void check();
    const timer = setInterval(() => void check(), 8000);
    return () => {
      clearInterval(timer);
      pending.current?.abort();
      pending.current = null;
    };
  }, [ready, check]);
  return { connected, check };
}
