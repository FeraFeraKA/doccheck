import { useEffect, useState } from 'react';

type LoadState<T> = { phase: 'loading' } | { phase: 'failed' } | { phase: 'ready'; data: T };

interface LoadRequest<T> {
  key: string;
  load: (key: string, signal: AbortSignal, onUpdate: (data: T) => void) => Promise<T>;
  attempt: number;
  state: LoadState<T>;
}

export function useCheckData<T>(key: string | undefined, load: LoadRequest<T>['load']) {
  const [attempt, setAttempt] = useState(0);
  const [request, setRequest] = useState<LoadRequest<T>>();

  useEffect(() => {
    if (key === undefined) return;
    const requestKey = key;
    const controller = new AbortController();
    function publish(state: LoadState<T>) {
      if (!controller.signal.aborted) setRequest({ key: requestKey, load, attempt, state });
    }

    void Promise.resolve().then(() => {
      controller.signal.throwIfAborted();
      return load(requestKey, controller.signal, (data) => publish({ phase: 'ready', data }));
    }).then(
      (data) => publish({ phase: 'ready', data }),
      () => publish({ phase: 'failed' }),
    );
    return () => controller.abort();
  }, [key, load, attempt]);

  const state = request && request.key === key && request.load === load && request.attempt === attempt
    ? request.state
    : { phase: 'loading' } as const;

  return { state, retry: () => setAttempt((current) => current + 1) };
}
