import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { getPdfPage } from './documentPreviewApi';
import type { SourceEvidence } from './sourceApi';
import type { SourceTone } from './OfficeReader';
import { WorkspaceIcon } from './WorkspaceIcon';

type Box = Extract<SourceEvidence['locator'], {kind: 'page'}>['bbox'];

export function PdfReader({ runId, documentId, startPage, box, tone, fallback, renderPage }: {
  runId: string;
  documentId: string;
  startPage: number;
  box?: Box;
  tone?: SourceTone;
  fallback: ReactNode;
  renderPage: (url: string, page: number, box: Box, tone?: SourceTone) => ReactNode;
}) {
  const [page, setPage] = useState(startPage);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<{ page: number; attempt: number; pages?: number; url?: string }>();
  const current = status?.page === page && status.attempt === attempt ? status : undefined;
  const pages = status?.pages;

  useEffect(() => {
    const abort = new AbortController();
    let url: string | undefined;
    void getPdfPage(runId, documentId, page, abort.signal).then(
      ({ image, pages }) => {
        if (abort.signal.aborted) return;
        url = URL.createObjectURL(image);
        setStatus({ page, attempt, pages, url });
      },
      () => {
        if (!abort.signal.aborted) setStatus((last) => ({ page, attempt, pages: last?.pages }));
      },
    );
    return () => {
      abort.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [runId, documentId, page, attempt]);

  function go(next: number) {
    if (pages !== undefined && next >= 1 && next <= pages) setPage(next);
  }

  return <>
    {pages !== undefined && <div className="document-reader-controls document-reader-paging" role="group" aria-label="Страницы PDF">
      <button type="button" aria-label="Предыдущая страница" aria-disabled={page === 1}
        tabIndex={page === 1 ? -1 : undefined}
        onClick={() => go(page - 1)}><WorkspaceIcon name="chevron" size={15} /></button>
      <span aria-live="polite">Страница {page} / {pages}</span>
      <button type="button" aria-label="Следующая страница" aria-disabled={page === pages}
        tabIndex={page === pages ? -1 : undefined}
        onClick={() => go(page + 1)}><WorkspaceIcon name="chevron" size={15} /></button>
      <button className="reader-source-jump" type="button" aria-disabled={page === startPage}
        tabIndex={page === startPage ? -1 : undefined}
        onClick={() => go(startPage)}>К источнику</button>
    </div>}
    {!current
      ? <div className="source-viewer-placeholder"><p role="status">Загрузка страницы PDF…</p></div>
      : current.url
        ? renderPage(current.url, page, page === startPage ? box : undefined, tone)
        : <>
          {fallback}
          <div className="source-viewer-placeholder source-reader-retry">
            <p role="status">Предпросмотр страницы с подсветкой недоступен.</p>
            <button type="button" onClick={() => setAttempt((previous) => previous + 1)}>Повторить предпросмотр</button>
          </div>
        </>}
  </>;
}
