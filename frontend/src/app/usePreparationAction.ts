import { useEffect, useRef, useState } from 'react';
import { publicError, type ApiError } from '../api/client';

// A single explicit attempt. Navigation discards completion, never replays work.
export function usePreparationAction<T>() {
  const active = useRef(true), gate = useRef(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState<ApiError>();
  const [result, setResult] = useState<T>();
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function run(work: () => Promise<T>, completed?: (value: T) => Promise<void>) {
    if (gate.current || !active.current) return;
    gate.current = true; setBusy(true); setError(undefined); setResult(undefined);
    try {
      const value = await work();
      if (!active.current) return;
      setResult(value);
      await completed?.(value);
    } catch (failure) { if (active.current) setError(publicError(failure)); }
    finally { gate.current = false; if (active.current) setBusy(false); }
  }
  return { busy, error, result, run };
}
