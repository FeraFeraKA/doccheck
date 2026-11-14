import { useEffect, useRef, useState } from 'react';
import { updateRunArchive } from './runStatusApi';
import { getConclusionWorkbook, saveConclusionWorkbook, XlsxDownload } from './XlsxDownload';
import { WorkspaceIcon } from './WorkspaceIcon';

const dateFormat = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' });

export function RunArchiveAction({ runId, initialArchivedAt, onChange }: {
  runId: string;
  initialArchivedAt?: string;
  onChange: (timestamp?: string) => void;
}) {
  const active = useRef<AbortController>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => () => active.current?.abort(), []);

  async function change() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError('');
    try {
      let workbook: Blob | undefined;
      if (!initialArchivedAt) {
        try {
          workbook = await getConclusionWorkbook(runId, controller.signal);
        } catch {
          if (!controller.signal.aborted) setError('Не удалось скачать XLSX. Повторите попытку.');
          return;
        }
        if (controller.signal.aborted) return;
      }
      const archivedAt = await updateRunArchive(runId, !initialArchivedAt, controller.signal);
      if (controller.signal.aborted) return;
      onChange(archivedAt);
      if (workbook) {
        try {
          saveConclusionWorkbook(workbook, runId);
        } catch {
          setError('Проверка принята. Скачайте XLSX повторно.');
        }
      }
    } catch {
      if (!controller.signal.aborted) setError(initialArchivedAt
        ? 'Не удалось вернуть проверку из архива.' : 'Не удалось принять проверку. Повторите попытку.');
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <div className="run-archive-action">
    {initialArchivedAt && <p className="run-accepted" role="status">
      <WorkspaceIcon name="check" size={16} /> Принят · {dateFormat.format(new Date(initialArchivedAt))}
    </p>}
    {initialArchivedAt && <XlsxDownload runId={runId} />}
    <button type="button" className={initialArchivedAt ? undefined : 'run-accept-button'}
      disabled={busy} onClick={() => { void change(); }}>
      {!initialArchivedAt && <WorkspaceIcon name="download" size={16} />}
      {initialArchivedAt ? 'Вернуть из архива' : 'Принять и скачать заключение'}
    </button>
    {busy && <span role="status">{initialArchivedAt ? 'Возвращаем из архива…' : 'Готовим заключение…'}</span>}
    {error && <span role="alert">{error}</span>}
  </div>;
}
