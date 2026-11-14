import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import './source-drawer.css';
import { formatLocation } from './reviewResult';
import {
  getSourceEvidence, getSourceOriginal, InvalidSourceResponseError, SourceHttpError,
} from './sourceApi';
import type { SourceEvidence } from './sourceApi';

interface SourceDocument {
  id: string;
  name: string;
  format: string | null;
}

interface DocumentSourcePreviewProps {
  runId: string;
  document: SourceDocument | null;
  evidenceId: string | null;
}

type RequestState<T> =
  | { status: 'loading' }
  | { status: 'ready'; value: T }
  | { status: 'error'; message: string };

function sourceError(error: unknown, subject: 'document' | 'evidence'): string {
  if (error instanceof SourceHttpError) {
    if (error.code === 'run_not_found') return 'Проверка недоступна.';
    if (error.code === 'document_not_found') return 'Оригинал документа недоступен.';
    if (error.code === 'result_pending') return 'Адрес станет доступен после обработки проверки.';
    if (error.code === 'run_failed') return 'Проверка завершилась без результата.';
    if (error.status === 404) {
      return subject === 'document' ? 'Оригинал документа недоступен.' : 'Адрес фрагмента недоступен.';
    }
    if (error.status === 503) return 'Хранилище источников временно недоступно.';
  }
  if (error instanceof InvalidSourceResponseError) {
    return 'API вернул некорректные данные источника.';
  }
  return subject === 'document' ? 'Не удалось загрузить оригинал.' : 'Не удалось загрузить адрес.';
}

function originalMediaType(format: string | null): string {
  switch (format) {
    case 'pdf': return 'application/pdf';
    case 'png': return 'image/png';
    case 'xlsx': return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    case 'docx': return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    default: return 'application/octet-stream';
  }
}

function locatorMatchesDocument(evidence: SourceEvidence, format: string | null): boolean {
  switch (format) {
    case 'pdf': return evidence.locator.kind === 'page';
    case 'png': return evidence.locator.kind === 'page' && evidence.locator.page === 1;
    case 'xlsx': return evidence.locator.kind === 'sheet';
    case 'docx': return evidence.locator.kind === 'paragraph' || evidence.locator.kind === 'table_cell';
    default: return false;
  }
}

export function DocumentSourcePreview({ runId, document, evidenceId }: DocumentSourcePreviewProps) {
  const [attempt, setAttempt] = useState(0);

  if (document === null) return <p>Документ источника недоступен.</p>;

  const key = JSON.stringify([runId, document.id, document.format, evidenceId, attempt]);
  return <SelectedDocumentSource
    key={key}
    runId={runId}
    document={document}
    evidenceId={evidenceId}
    onRetry={() => setAttempt((current) => current + 1)}
  />;
}

function SelectedDocumentSource({ runId, document, evidenceId, onRetry }: {
  runId: string;
  document: SourceDocument;
  evidenceId: string | null;
  onRetry: () => void;
}) {
  const [original, setOriginal] = useState<RequestState<string>>({ status: 'loading' });
  const [evidence, setEvidence] = useState<RequestState<SourceEvidence>>({ status: 'loading' });
  const { id: documentId, format } = document;

  useEffect(() => {
    const controller = new AbortController();
    let url: string | undefined;
    void getSourceOriginal(runId, documentId, controller.signal).then((blob) => {
      if (controller.signal.aborted) return;
      url = URL.createObjectURL(blob.slice(0, blob.size, originalMediaType(format)));
      setOriginal({ status: 'ready', value: url });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setOriginal({ status: 'error', message: sourceError(error, 'document') });
      }
    });

    if (evidenceId !== null) {
      void getSourceEvidence(runId, documentId, evidenceId, controller.signal).then((value) => {
        if (!controller.signal.aborted) setEvidence({ status: 'ready', value });
      }).catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setEvidence({ status: 'error', message: sourceError(error, 'evidence') });
        }
      });
    }

    return () => {
      controller.abort();
      if (url !== undefined) URL.revokeObjectURL(url);
    };
  }, [runId, documentId, format, evidenceId]);

  const address = evidence.status === 'ready' && locatorMatchesDocument(evidence.value, format)
    ? evidence.value.locator : null;
  const page = address?.kind === 'page' ? address : null;
  const canRetry = original.status === 'error' || evidence.status === 'error';
  const pdfUrl = original.status === 'ready'
    ? page ? `${original.value}#page=${page.page}` : original.value
    : null;
  const download = original.status === 'ready'
    ? <a href={original.value} download={document.name}>Скачать оригинал</a> : null;
  const fragment = evidence.status === 'ready'
    ? <div><small>Выбранный фрагмент</small><strong>{evidence.value.raw_value}</strong></div>
    : null;
  const retry = canRetry
    ? <button type="button" onClick={onRetry}>Повторить загрузку источника</button> : null;

  return <section aria-label="Просмотр источника" className="source-viewer">
    <div className="source-viewer-heading"><strong>{document.name}</strong>
      {evidenceId === null && <p>Адрес фрагмента отсутствует.</p>}
      {evidenceId !== null && evidence.status === 'loading' && <p role="status">Загрузка адреса…</p>}
      {evidence.status === 'error' && <p role="alert">{evidence.message}</p>}
      {evidence.status === 'ready' && (address === null
        ? <p>Адрес фрагмента не поддерживается для этого формата.</p>
        : <p><strong>Адрес</strong> <span>{formatLocation(address)}</span></p>)}
    </div>
    {original.status === 'ready' && format !== 'png' && <div className="source-viewer-toolbar">
      {format === 'pdf' && page && <span>Стр. {page.page}</span>}
      {format === 'pdf' && pdfUrl && (
        <a
          href={pdfUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          {page ? `Открыть страницу ${page.page} PDF (в новой вкладке)` : 'Открыть PDF (в новой вкладке)'}
        </a>
      )}
      {download}
    </div>}
    {original.status === 'loading' && <div className="source-viewer-placeholder"><p role="status">Загрузка оригинала…</p></div>}
    {original.status === 'error' && <div className="source-viewer-placeholder"><p role="alert">{original.message}</p></div>}
    {original.status === 'ready' && format === 'png' && (
      <SourceImage key={original.value} url={original.value} name={document.name} page={page?.page}
        box={page?.bbox} download={download} fragment={fragment} retry={retry} />
    )}
    {original.status === 'ready' && format !== 'png' && <div className="source-viewer-placeholder">
      {format === 'pdf' && <p>Страница открывается в PDF-просмотрщике браузера.</p>}
      {(format === 'xlsx' || format === 'docx') && (
        <p>Для просмотра по адресу откройте скачанный файл в офисном приложении.</p>
      )}
      {format !== 'pdf' && format !== 'png' && format !== 'xlsx' && format !== 'docx' && (
        <p>Предпросмотр этого формата недоступен.</p>
      )}
    </div>}
    {(original.status !== 'ready' || format !== 'png') && (fragment || retry) && <div className="source-viewer-footer">
      {fragment}{retry}
    </div>}
  </section>;
}

function SourceImage({ url, name, page, box, download, fragment, retry }: {
  url: string;
  name: string;
  page?: number;
  box?: [number, number, number, number] | null;
  download: React.ReactNode;
  fragment: React.ReactNode;
  retry: React.ReactNode;
}) {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [zoom, setZoom] = useState(100);
  const [highlight, setHighlight] = useState(true);
  const mark = useRef<HTMLSpanElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const centered = useRef<string>(undefined);
  const boxKey = box?.join(',');

  function centerFragment() {
    const container = viewport.current;
    const target = mark.current;
    if (!container || !target || typeof container.scrollBy !== 'function') return;
    const bounds = container.getBoundingClientRect();
    const fragmentBounds = target.getBoundingClientRect();
    container.scrollBy({
      top: fragmentBounds.top + fragmentBounds.height / 2 - bounds.top - container.clientHeight / 2,
      left: fragmentBounds.left + fragmentBounds.width / 2 - bounds.left - container.clientWidth / 2,
    });
  }

  useLayoutEffect(() => {
    if (state !== 'ready' || !boxKey || !highlight || centered.current === boxKey) return;
    centered.current = boxKey;
    centerFragment();
  }, [state, boxKey, highlight]);

  return <>
    <div className="source-viewer-toolbar">
      {page && <span>Стр. {page}</span>}
      {state === 'ready' && <div className="source-viewer-zoom">
        <button type="button" aria-label="Уменьшить масштаб" disabled={zoom <= 75} onClick={() => setZoom(zoom - 25)}>−</button>
        <span aria-label="Масштаб документа">{zoom}%</span>
        <button type="button" aria-label="Увеличить масштаб" disabled={zoom >= 175} onClick={() => setZoom(zoom + 25)}>+</button>
        <button type="button" aria-label="Сбросить масштаб" disabled={zoom === 100} onClick={() => setZoom(100)}>↺</button>
      </div>}
      {box && state === 'ready' && <button type="button" aria-pressed={highlight}
        onClick={() => setHighlight(!highlight)}>Подсветка</button>}
      {download}
    </div>
    {state === 'error' ? <div className="source-viewer-placeholder"><p role="alert">Предпросмотр изображения недоступен.</p></div>
      : <div ref={viewport} className="source-viewer-viewport" role="region" tabIndex={0} aria-label={`Просмотр документа: ${name}`}>
      {state === 'loading' && <p role="status">Загрузка изображения…</p>}
      <div className="source-viewer-sheet" style={{ width: `${zoom}%` }}>
        <img
          src={url}
          alt={name}
          draggable={false}
          onLoad={() => setState('ready')}
          onError={() => setState('error')}
        />
        {state === 'ready' && box && highlight && <span
          ref={mark}
          aria-hidden="true"
          className="source-viewer-highlight"
          style={{
            left: `${box[0] * 100}%`,
            top: `${box[1] * 100}%`,
            width: `${(box[2] - box[0]) * 100}%`,
            height: `${(box[3] - box[1]) * 100}%`,
          }}
        />}
      </div>
    </div>}
    {(fragment || retry || (box && state === 'ready')) && <div className="source-viewer-footer">
      {fragment}
      {box && state === 'ready' && <button type="button" disabled={!highlight} onClick={centerFragment}>К фрагменту</button>}
      {retry}
    </div>}
  </>;
}
