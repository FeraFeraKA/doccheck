import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { getPdfPage } from './documentPreviewApi';
import { WorkspaceIcon } from './WorkspaceIcon';

export function PdfReader({ runId, documentId, startPage, sourceId, fallback, renderPage }: {
  runId: string;
  documentId: string;
  startPage: number;
  sourceId: string | null;
  fallback: (page: number) => ReactNode;
  renderPage: (url: string, page: number) => ReactNode;
}) {
  const [navigation, setNavigation] = useState({ start: startPage, sourceId, page: startPage });
  const atSource = navigation.start !== startPage || navigation.sourceId !== sourceId;
  if (atSource) setNavigation({ start: startPage, sourceId, page: startPage });
  const page = atSource ? startPage : navigation.page;
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
    if (pages !== undefined && next >= 1 && next <= pages) setNavigation({ start: startPage, sourceId, page: next });
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
        onClick={() => go(startPage)}>{sourceId === null ? 'К началу' : 'К источнику'}</button>
    </div>}
    {!current
      ? <div className="source-viewer-placeholder"><p role="status">Загрузка страницы PDF…</p></div>
      : current.url
        ? renderPage(current.url, page)
        : <>
          {fallback(page)}
          <div className="source-viewer-placeholder source-reader-retry">
            <p role="status">Предпросмотр страницы с подсветкой недоступен.</p>
            <button type="button" onClick={() => setAttempt((previous) => previous + 1)}>Повторить предпросмотр</button>
          </div>
        </>}
  </>;
}
