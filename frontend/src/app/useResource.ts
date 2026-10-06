import { useCallback, useEffect, useRef, useState } from 'react';
import { publicError, type ApiError } from '../api/client';

// Latest request wins. Changing routes/unmounting discards old read responses.
export function useResource<T>(load: () => Promise<T>) {
  const generation = useRef(0);
  const [state, setState] = useState<{ data?: T; error?: ApiError; loading: boolean }>({ loading: true });
  const reload = useCallback(async () => {
    const current = ++generation.current;
    setState(previous => ({ ...previous, error: undefined, loading: true }));
    try {
      const data = await load();
      if (generation.current === current) setState({ data, loading: false });
    } catch (failure) {
      if (generation.current === current) setState(previous => ({ ...previous, error: publicError(failure), loading: false }));
    }
  }, [load]);
  useEffect(() => { void reload(); return () => { generation.current++; }; }, [reload]);
  return { ...state, reload };
}
