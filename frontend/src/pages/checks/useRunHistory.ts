import { useEffect, useState } from 'react';
import { loadRunHistory } from './checkData';
import type { CheckHistory, FindingFilter } from './checkData';

const refreshInterval = 3_000;

interface Snapshot {
  cursor?: string;
  finding?: FindingFilter;
  loader: typeof loadRunHistory;
  page?: CheckHistory;
  error: boolean;
}

export function useRunHistory({
  enabled = true, cursor, finding, loader = loadRunHistory, onPage,
}: {
  enabled?: boolean;
  cursor?: string;
  finding?: FindingFilter;
  loader?: typeof loadRunHistory;
  onPage?: (page: CheckHistory) => void;
} = {}) {
  const [revision, setRevision] = useState(0);
  const [snapshot, setSnapshot] = useState<Snapshot>();
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;

    async function update() {
      try {
        const page = await loader(controller.signal, cursor, finding);
        if (!controller.signal.aborted) {
          setSnapshot({ cursor, finding, loader, page, error: false });
          onPage?.(page);
        }
      } catch {
        if (!controller.signal.aborted) setSnapshot((previous) => ({
          cursor, finding, loader,
          page: previous?.cursor === cursor && previous?.finding === finding && previous?.loader === loader
            ? previous.page : undefined,
          error: true,
        }));
      }
      if (!controller.signal.aborted) timer = setTimeout(() => { void update(); }, refreshInterval);
    }

    void update();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [enabled, cursor, finding, loader, onPage, revision]);

  const current = snapshot?.cursor === cursor && snapshot?.finding === finding && snapshot?.loader === loader
    ? snapshot : undefined;
  return {
    page: current?.page,
    loading: enabled && !current,
    error: current?.error ?? false,
    refresh: () => setRevision((value) => value + 1),
  };
}
