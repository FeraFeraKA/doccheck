import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { updateRunArchive } from './runStatusApi';

const dateFormat = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' });

export function RunArchiveAction({ runId, initialArchivedAt, onChange }: {
  runId: string;
  initialArchivedAt?: string;
  onChange: (timestamp?: string) => void;
}) {
  const active = useRef<AbortController>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => () => active.current?.abort(), []);

  async function change() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError(false);
    try {
      const archivedAt = await updateRunArchive(runId, !initialArchivedAt, controller.signal);
      if (!controller.signal.aborted) onChange(archivedAt);
    } catch {
      if (!controller.signal.aborted) setError(true);
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <div className="run-archive-action">
    <button type="button" disabled={busy} onClick={() => { void change(); }}>
      {initialArchivedAt ? 'Вернуть из архива' : 'В архив'}
    </button>
    <span role="status">
      {initialArchivedAt && <Link to="/archive">В архиве · {dateFormat.format(new Date(initialArchivedAt))}</Link>}
    </span>
    {error && <span role="alert">Не удалось изменить состояние архива.</span>}
  </div>;
}