import { useCallback, useEffect, useRef, useState } from 'react';

/** Tiny data-loading hook: runs `fn` on mount / when deps change.
 *  Only the latest request may set state: a slower, older response (StrictMode's double mount, a quick
 *  reload) must not overwrite newer data or reset the page while the reviewer is editing. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps);

  const reload = useCallback(() => {
    const id = ++latest.current;
    setLoading(true);
    setError(null);
    run()
      .then((d) => id === latest.current && setData(d))
      .catch((e: unknown) => id === latest.current && setError(e instanceof Error ? e : new Error(String(e))))
      .finally(() => id === latest.current && setLoading(false));
  }, [run]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { data, error, loading, reload };
}
