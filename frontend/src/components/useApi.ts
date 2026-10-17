import { useEffect, useState } from "react";

export interface ApiState<T> { data: T | null; error: string | null; loading: boolean }

/** Fetch on mount / dependency change; ignores responses of superseded requests. */
export function useApi<T>(load: () => Promise<T>, deps: unknown[]): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({ data: null, error: null, loading: true });
  useEffect(() => {
    let active = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    load().then(
      (data) => active && setState({ data, error: null, loading: false }),
      (error: Error) => active && setState({ data: null, error: error.message, loading: false }),
    );
    return () => { active = false; };
  }, deps);
  return state;
}
