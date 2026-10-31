import { useCallback, useEffect, useState } from 'react';

/** Tiny data-loading hook: runs `fn` on mount / when deps change. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    run()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e : new Error(String(e))))
      .finally(() => setLoading(false));
  }, [run]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { data, error, loading, reload };
}
