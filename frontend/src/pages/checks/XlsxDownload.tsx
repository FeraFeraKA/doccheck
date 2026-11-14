import { useEffect, useRef, useState } from 'react';

const xlsxType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

export async function getConclusionWorkbook(runId: string, signal: AbortSignal) {
  const response = await fetch(`/api/v0/runs/${encodeURIComponent(runId)}/exports/xlsx`, {
    signal: AbortSignal.any([signal, AbortSignal.timeout(30_000)]), redirect: 'error', cache: 'no-store',
  });
  if (response.status !== 200 || response.headers.get('Content-Type') !== xlsxType) {
    throw new Error('Invalid XLSX export response');
  }
  const file = await response.blob();
  if (file.size === 0) throw new Error('Empty XLSX export response');
  return file;
}

export function saveConclusionWorkbook(file: Blob, runId: string) {
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = `doccheck-${runId}.xlsx`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export function XlsxDownload({ runId }: { runId: string }) {
  const active = useRef<AbortController | null>(null);
  const [state, setState] = useState<'idle' | 'loading' | 'failed'>('idle');

  useEffect(() => () => active.current?.abort(), []);

  async function download() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setState('loading');
    try {
      const file = await getConclusionWorkbook(runId, controller.signal);
      controller.signal.throwIfAborted();
      saveConclusionWorkbook(file, runId);
      setState('idle');
    } catch {
      if (!controller.signal.aborted) setState('failed');
    } finally {
      active.current = null;
    }
  }

  return <>
    <button type="button" disabled={state === 'loading'} onClick={download}>Скачать XLSX</button>
    {state === 'loading' && <p role="status">Подготовка XLSX…</p>}
    {state === 'failed' && <p role="alert">Не удалось скачать XLSX. Повторите попытку.</p>}
  </>;
}
