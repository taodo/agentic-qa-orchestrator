import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client';
import { getOperations, type OperationsSnapshot } from '../api/operations';

export const OPERATIONS_REFRESH_MS = 7000;
export function useOperations(query: string, projectId: string, enabled: boolean) {
  const key = `${enabled}:${query}:${projectId}`;
  const [state, setState] = useState<{ key: string; data?: OperationsSnapshot; error?: ApiError; loading: boolean }>({ key, loading: true });
  const busy = useRef(false);
  const pending = useRef<(() => void) | undefined>(undefined);
  const refresh = useRef<() => void>(() => {});
  useEffect(() => {
    let alive = true, expired = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    function clear() { clearTimeout(timer); timer = undefined; }
    function schedule() {
      clear();
      if (alive && enabled && !expired && document.visibilityState !== 'hidden') timer = setTimeout(load, OPERATIONS_REFRESH_MS);
    }
    function load() {
      clear();
      if (!alive || !enabled || expired || document.visibilityState === 'hidden') return;
      if (busy.current) { pending.current = load; return; }
      busy.current = true;
      setState(previous => ({ key, data: previous.key === key ? previous.data : undefined, loading: true }));
      void getOperations(query, projectId).then(data => {
        if (alive) setState({ key, data, loading: false });
      }).catch(failure => {
        expired = failure instanceof ApiError && failure.code === 'HOST_AUTH_REQUIRED';
        if (alive) setState({ key, error: new ApiError(expired ? 'HOST_AUTH_REQUIRED' : 'OPERATIONS_UNAVAILABLE',
          expired ? 'Sign in again to continue.' : 'Operational snapshot unavailable. Refresh to try again.'), loading: false });
      }).finally(() => {
        busy.current = false;
        const next = pending.current; pending.current = undefined;
        if (next) next(); else schedule();
      });
    }
    function visibility() { if (document.visibilityState === 'hidden') clear(); else load(); }
    refresh.current = load;
    if (enabled) load();
    else setState({ key, loading: false });
    document.addEventListener('visibilitychange', visibility);
    return () => {
      alive = false; clear();
      if (pending.current === load) pending.current = undefined;
      document.removeEventListener('visibilitychange', visibility);
    };
  }, [key, query, projectId, enabled]);
  return { ...(state.key === key ? state : { key, loading: enabled }), refresh: () => refresh.current() };
}
