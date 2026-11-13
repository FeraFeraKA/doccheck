import { useEffect, useState } from 'react';
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

  return <section aria-label="Просмотр источника" className="mt-3 space-y-2">
    <p><strong>{document.name}</strong></p>
    {evidenceId === null && <p>Адрес фрагмента отсутствует.</p>}
    {evidenceId !== null && evidence.status === 'loading' && <p role="status">Загрузка адреса…</p>}
    {evidence.status === 'error' && <p role="alert">{evidence.message}</p>}
    {evidence.status === 'ready' && (address === null
      ? <p>Адрес фрагмента не поддерживается для этого формата.</p>
      : <p><strong>Адрес</strong> {formatLocation(address)}</p>)}
    {original.status === 'loading' && <p role="status">Загрузка оригинала…</p>}
    {original.status === 'error' && <p role="alert">{original.message}</p>}
    {original.status === 'ready' && <>
      <p><a href={original.value} download={document.name}>Скачать оригинал</a></p>
      {format === 'pdf' && (
        <a
          href={page ? `${original.value}#page=${page.page}` : original.value}
          target="_blank"
          rel="noopener noreferrer"
        >
          {page ? `Открыть страницу ${page.page} PDF (в новой вкладке)` : 'Открыть PDF (в новой вкладке)'}
        </a>
      )}
      {format === 'png' && (
        <SourceImage key={original.value} url={original.value} name={document.name} box={page?.bbox} />
      )}
      {(format === 'xlsx' || format === 'docx') && (
        <p>Для просмотра по адресу откройте скачанный файл в офисном приложении.</p>
      )}
      {format !== 'pdf' && format !== 'png' && format !== 'xlsx' && format !== 'docx' && (
        <p>Предпросмотр этого формата недоступен.</p>
      )}
    </>}
    {canRetry && <button type="button" onClick={onRetry}>Повторить загрузку источника</button>}
  </section>;
}

function SourceImage({ url, name, box }: {
  url: string;
  name: string;
  box?: [number, number, number, number] | null;
}) {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  if (state === 'error') return <p role="alert">Предпросмотр изображения недоступен.</p>;

  return <div className="relative inline-block max-w-full">
    <img
      src={url}
      alt={name}
      className="block h-auto max-w-full"
      onLoad={() => setState('ready')}
      onError={() => setState('error')}
    />
    {state === 'ready' && box && <span
      aria-hidden="true"
      className="pointer-events-none absolute border-2 border-rose-600"
      style={{
        left: `${box[0] * 100}%`,
        top: `${box[1] * 100}%`,
        width: `${(box[2] - box[0]) * 100}%`,
        height: `${(box[3] - box[1]) * 100}%`,
      }}
    />}
  </div>;
}
