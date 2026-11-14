import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import './source-drawer.css';
import { formatLocation } from './reviewResult';
import type { PageAddress } from './reviewResult';
import { OfficeReader } from './OfficeReader';
import { PdfReader } from './PdfReader';
import { SourcePreviewSkeleton } from './SourcePreviewSkeleton';
import { isVisibleAddress, pageHighlights, sourceBox, sourceColor, sourceField, sourceFields, sourceMark } from './sourceHighlights';
import type { SourceBox, SourceField, SourceHighlight, SourceImageHighlight } from './sourceHighlights';
import {
  getSourceEvidence, getSourceFragmentPreview, getSourceOriginal, InvalidSourceResponseError, SourceHttpError,
} from './sourceApi';
import type { SourceEvidence } from './sourceApi';
import { WorkspaceIcon } from './WorkspaceIcon';

interface SourceDocument {
  id: string;
  name: string;
  format: string | null;
}

interface DocumentSourcePreviewProps {
  runId: string;
  document: SourceDocument | null;
  evidenceId: string | null;
  reportPage?: PageAddress;
  highlights?: readonly SourceHighlight[];
  active?: boolean;
  compact?: boolean;
  view?: DocumentView;
  onViewChange?: (view: DocumentView) => void;
}

export interface DocumentView {
  zoom: number;
  hiddenFields: ReadonlySet<SourceField>;
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

export function DocumentSourcePreview({
  runId, document, evidenceId, reportPage, highlights,
  active = true, compact = false, view, onViewChange,
}: DocumentSourcePreviewProps) {
  const [attempt, setAttempt] = useState(0);

  if (document === null) return <p>Документ источника недоступен.</p>;

  const key = JSON.stringify([runId, document.id, document.format, attempt]);
  return <SelectedDocumentSource
    key={key}
    runId={runId}
    document={document}
    evidenceId={evidenceId}
    reportPage={reportPage}
    highlights={highlights}
    active={active}
    compact={compact}
    view={view}
    onViewChange={onViewChange}
    onRetry={() => setAttempt((current) => current + 1)}
  />;
}

const noHighlights: readonly SourceHighlight[] = [];
const initialView: DocumentView = { zoom: 100, hiddenFields: new Set() };

function SelectedDocumentSource({
  runId, document, evidenceId, reportPage, highlights = noHighlights,
  active, compact, view, onViewChange, onRetry,
}: {
  runId: string;
  document: SourceDocument;
  evidenceId: string | null;
  reportPage?: PageAddress;
  highlights?: readonly SourceHighlight[];
  active: boolean;
  compact: boolean;
  view?: DocumentView;
  onViewChange?: (view: DocumentView) => void;
  onRetry: () => void;
}) {
  const [localView, setLocalView] = useState(initialView);
  const { zoom, hiddenFields } = view ?? localView;
  const updateView = onViewChange ?? setLocalView;
  const [original, setOriginal] = useState<RequestState<string>>({ status: 'loading' });
  const [selection, setSelection] = useState(evidenceId);
  const [evidence, setEvidence] = useState<RequestState<SourceEvidence>>({ status: 'loading' });
  if (selection !== evidenceId) {
    setSelection(evidenceId);
    setEvidence({ status: 'loading' });
  }
  const { id: documentId, format } = document;
  const visibleHighlights = useMemo(() => highlights.filter(({ locator }) => isVisibleAddress(locator, format)),
    [format, highlights]);
  const enabledHighlights = useMemo(() => visibleHighlights.filter(({ kind }) => !hiddenFields.has(kind)),
    [visibleHighlights, hiddenFields]);
  const markersByPage = useMemo(() => format === 'pdf' || format === 'png'
    ? pageHighlights(enabledHighlights)
    : undefined, [format, enabledHighlights]);

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

    return () => {
      controller.abort();
      if (url !== undefined) URL.revokeObjectURL(url);
    };
  }, [runId, documentId, format]);

  useEffect(() => {
    if (evidenceId === null) return;
    const controller = new AbortController();
    void getSourceEvidence(runId, documentId, evidenceId, controller.signal).then((value) => {
      if (!controller.signal.aborted) setEvidence({ status: 'ready', value });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setEvidence({ status: 'error', message: sourceError(error, 'evidence') });
      }
    });
    return () => controller.abort();
  }, [runId, documentId, evidenceId]);

  const address = evidence.status === 'ready' && locatorMatchesDocument(evidence.value, format)
    ? evidence.value.locator : null;
  const evidencePage = address?.kind === 'page' ? address : undefined;
  const page = evidencePage ?? (evidenceId === null && (format === 'pdf' || format === 'png') ? reportPage : undefined);
  const scopeBox = page === reportPage ? sourceBox(reportPage?.bbox) : undefined;
  const hasAddressedText = compact && format === 'pdf' && evidencePage != null && evidencePage.bbox == null && evidenceId !== null;
  const selectedField = evidence.status === 'ready' && address && (isVisibleAddress(address, format) || hasAddressedText)
    ? sourceField(evidence.value.kind) : scopeBox ? 'source' : undefined;
  const enabledSelection = selectedField && !hiddenFields.has(selectedField) ? selectedField : undefined;
  const availableFields = new Set(visibleHighlights.map(({ kind }) => kind));
  if (selectedField) availableFields.add(selectedField);
  const addressPending = evidenceId !== null && evidence.status === 'loading';
  const previewPending = addressPending || (original.status === 'loading' && format !== 'xlsx' && format !== 'docx');
  const canRetry = original.status === 'error' || evidence.status === 'error';
  const pdfUrl = original.status === 'ready'
    ? page ? `${original.value}#page=${page.page}` : original.value
    : null;
  const office = format === 'xlsx' || format === 'docx' ? format : undefined;
  const usePdfReader = compact && format === 'pdf';
  const compactImage = compact && format === 'png';
  const download = original.status === 'ready'
    ? <a href={original.value} download={document.name}
        className={compactImage ? 'source-viewer-image-download' : undefined}
        title={compactImage ? 'Скачать оригинал' : undefined}>
      {compactImage && <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 3v12m-5-5 5 5 5-5M5 16v4h14v-4" />
      </svg>}
      <span className={compactImage ? 'sr-only' : undefined}>Скачать оригинал</span>
    </a> : null;
  const fragment = evidence.status === 'ready'
    ? <div><small>Выбранный фрагмент</small><strong>{evidence.value.raw_value}</strong></div>
    : null;
  const retry = canRetry
    ? <button type="button" onClick={onRetry}>Повторить загрузку источника</button> : null;

  function pdfFallback(currentPage: number) {
    if (!compact || !navigator.pdfViewerEnabled || original.status !== 'ready') {
      return <div className="source-viewer-placeholder">
        <p>Страница открывается в PDF-просмотрщике браузера.</p>
      </div>;
    }
    return <iframe className="source-viewer-pdf" title={`Просмотр документа: ${document.name}`}
      src={`${original.value}#page=${currentPage}&view=FitH&toolbar=0`} />;
  }

  const showAddress = !compact || Boolean(reportPage && page === reportPage) || evidence.status !== 'loading';
  return <section aria-label="Просмотр источника" className="source-viewer">
    {showAddress && <div className="source-viewer-heading">
      {!compact && <strong className="source-viewer-name" title={document.name}>{document.name}</strong>}
      {evidenceId === null && (page
        ? <p>Строка КФЗ · {formatLocation(page)}</p>
        : !compact && <p>Адрес фрагмента отсутствует.</p>)}
      {evidence.status === 'error' && <p role="alert">{evidence.message}</p>}
      {evidence.status === 'ready' && (address === null
        ? <p>Адрес фрагмента не поддерживается для этого формата.</p>
        : <p><strong>Адрес</strong> <span>{formatLocation(address)}</span></p>)}
    </div>}
    {availableFields.size > 0 && <fieldset className="source-field-legend">
      <legend>Извлечённые данные</legend>
      <div>
        {sourceFields.filter(([kind]) => availableFields.has(kind)).map(([kind, label]) => <label key={kind}
          style={sourceColor(kind)}>
          <input type="checkbox" checked={!hiddenFields.has(kind)} onChange={(event) => {
            const next = new Set(hiddenFields);
            if (event.currentTarget.checked) next.delete(kind);
            else next.add(kind);
            updateView({ zoom, hiddenFields: next });
          }} />
          {label}
        </label>)}
      </div>
    </fieldset>}
    {original.status === 'ready' && format !== 'png' && <div className="source-viewer-toolbar" role="group" aria-label="Действия с оригиналом">
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
    {previewPending && original.status !== 'error' && <SourcePreviewSkeleton />}
    {original.status === 'error' && <div className="source-viewer-placeholder"><p role="alert">{original.message}</p></div>}
    {!previewPending && original.status === 'ready' && format === 'png' && (
      <SourceImage key={original.value} url={original.value} name={document.name} page={page?.page ?? (compact ? 1 : undefined)}
        zoom={zoom} onZoomChange={(zoom) => updateView({ zoom, hiddenFields })}
        box={sourceBox(evidencePage?.bbox) ?? scopeBox} selected={enabledSelection} markers={markersByPage?.get(1) ?? []}
        active={active} download={download} fragment={fragment} retry={retry} />
    )}
    {!previewPending && original.status === 'ready' && format === 'pdf' && (usePdfReader ?
      <PdfReader runId={runId} documentId={documentId} sourceId={evidenceId}
      startPage={page?.page ?? 1} fallback={pdfFallback}
      renderPage={(url, currentPage) => <SourceImage key={url} url={url}
        name={document.name} active={active}
        box={page?.page === currentPage ? sourceBox(evidencePage?.bbox) ?? scopeBox : undefined}
        selected={enabledSelection}
        markers={markersByPage?.get(currentPage) ?? []}
        zoom={zoom} onZoomChange={(zoom) => updateView({ zoom, hiddenFields })} />} />
      : pdfFallback(page?.page ?? 1))}
    {!previewPending && original.status !== 'error' && office && <OfficeReader
      runId={runId} documentId={documentId} format={office} locator={address ?? undefined}
      evidenceId={evidenceId} selectedField={enabledSelection} highlights={enabledHighlights} active={active}
      fallback={address && evidenceId ? <SourceFragmentText runId={runId} documentId={documentId}
        evidenceId={evidenceId} field={enabledSelection} /> : null} />}
    {original.status === 'ready' && format !== 'pdf' && format !== 'png' && !office &&
      <div className="source-viewer-placeholder"><p>Предпросмотр этого формата недоступен.</p></div>}
    {hasAddressedText &&
      <SourceFragmentText key={evidenceId} runId={runId} documentId={documentId}
        evidenceId={evidenceId} field={enabledSelection} />}
    {(original.status !== 'ready' || format !== 'png') && ((!office && !hasAddressedText && fragment) || retry) &&
      <div className="source-viewer-footer">
      {!office && !hasAddressedText && fragment}{retry}
    </div>}
  </section>;
}

function SourceFragmentText({ runId, documentId, evidenceId, field }: {
  runId: string;
  documentId: string;
  evidenceId: string;
  field?: SourceField;
}) {
  const [preview, setPreview] = useState<RequestState<Awaited<ReturnType<typeof getSourceFragmentPreview>>>>({ status: 'loading' });
  useEffect(() => {
    const controller = new AbortController();
    void getSourceFragmentPreview(runId, documentId, evidenceId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setPreview({ status: 'ready', value });
      })
      .catch(() => {
        if (!controller.signal.aborted) setPreview({ status: 'error', message: 'Не удалось загрузить текст фрагмента.' });
      });
    return () => controller.abort();
  }, [runId, documentId, evidenceId]);

  return <section className="source-fragment-text" aria-label="Текст исходного фрагмента">
    {preview.status === 'loading' && <p role="status">Загрузка текста фрагмента…</p>}
    {preview.status === 'error' && <p role="status">{preview.message}</p>}
    {preview.status === 'ready' && (preview.value
      ? <p>{preview.value.match
        ? <>{preview.value.match[0]}{field
          ? <mark {...sourceMark(undefined, field)}>{preview.value.match[1]}</mark>
          : preview.value.match[1]}{preview.value.match[2]}</>
        : preview.value.text}</p>
      : <p>Текст фрагмента недоступен.</p>)}
  </section>;
}

function SourceImage({ url, name, page, box, selected, markers, active, download, fragment, retry, zoom, onZoomChange }: {
  url: string;
  name: string;
  page?: number;
  box?: SourceBox;
  selected?: SourceField;
  markers: readonly SourceImageHighlight[];
  active: boolean;
  download?: React.ReactNode;
  fragment?: React.ReactNode;
  retry?: React.ReactNode;
  zoom: number;
  onZoomChange: (zoom: number) => void;
}) {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');

  const mark = useRef<HTMLSpanElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const centered = useRef<string>(undefined);
  const boxKey = box?.join(',');
  const matchingKinds = markers.find((item) => item.box.join(',') === boxKey)?.kinds;

  function centerFragment() {
    const container = viewport.current;
    const target = mark.current;
    if (!container || !target || typeof container.scrollBy !== 'function') return false;
    const bounds = container.getBoundingClientRect();
    const fragmentBounds = target.getBoundingClientRect();
    if (container.clientWidth === 0 || container.clientHeight === 0 ||
      fragmentBounds.width === 0 || fragmentBounds.height === 0) return false;
    container.scrollBy({
      top: fragmentBounds.top + fragmentBounds.height / 2 - bounds.top - container.clientHeight / 2,
      left: fragmentBounds.left + fragmentBounds.width / 2 - bounds.left - container.clientWidth / 2,
    });
    return true;
  }

  useLayoutEffect(() => {
    if (!active || state !== 'ready' || !boxKey || centered.current === boxKey) return;
    if (centerFragment()) centered.current = boxKey;
  }, [active, state, boxKey]);

  return <>
    <div className="source-viewer-toolbar" role="group" aria-label="Настройки просмотра">
      <div className="source-viewer-controls">
        {page && <span>Стр. {page}</span>}
        <div className="source-viewer-zoom">
          <button type="button" aria-label="Уменьшить масштаб" disabled={state !== 'ready' || zoom <= 75}
            onClick={() => onZoomChange(zoom - 25)}><WorkspaceIcon name="minus" size={18} /></button>
          <span aria-label="Масштаб документа">{zoom}%</span>
          <button type="button" aria-label="Увеличить масштаб" disabled={state !== 'ready'}
            onClick={() => onZoomChange(zoom + 25)}><WorkspaceIcon name="plus" size={18} /></button>
          <button type="button" aria-label="Сбросить масштаб" disabled={state !== 'ready' || zoom === 100}
            onClick={() => onZoomChange(100)}><WorkspaceIcon name="reset" size={18} /></button>
        </div>
      </div>
      {download}
    </div>
    {state === 'error' ? <div className="source-viewer-placeholder"><p role="alert">Предпросмотр изображения недоступен.</p></div>
      : <div ref={viewport} className="source-viewer-viewport" role="region" tabIndex={0} aria-label={`Просмотр документа: ${name}`}>
      {state === 'loading' && <SourcePreviewSkeleton />}
      <div className="source-viewer-sheet" style={{ width: `${zoom}%` }}>
        <img
          src={url}
          alt={name}
          hidden={state === 'loading'}
          draggable={false}
          onLoad={() => setState('ready')}
          onError={() => setState('error')}
        />
        {state === 'ready' && markers.map((item) => {
          const key = item.box.join(',');
          return key !== boxKey && <ImageHighlight key={key} box={item.box} kinds={item.kinds} />;
        })}
        {state === 'ready' && box &&
          <ImageHighlight mark={mark} box={box} kinds={matchingKinds} selected={selected} />}
      </div>
    </div>}
    {(fragment || retry || (box && state === 'ready')) && <div className="source-viewer-footer">
      {fragment}
      {box && state === 'ready' && <button type="button" onClick={centerFragment}>К фрагменту</button>}
      {retry}
    </div>}
  </>;
}

function ImageHighlight({ box, kinds, selected, mark }: {
  box: SourceBox;
  kinds?: ReadonlySet<SourceField>;
  selected?: SourceField;
  mark?: React.Ref<HTMLSpanElement>;
}) {
  const decoration = sourceMark(kinds, selected);
  return <span ref={mark} aria-hidden="true" className="source-viewer-highlight"
    {...decoration} data-hidden={!decoration}
    style={{
      ...decoration?.style,
      left: `${box[0] * 100}%`,
      top: `${box[1] * 100}%`,
      width: `${(box[2] - box[0]) * 100}%`,
      height: `${(box[3] - box[1]) * 100}%`,
    }} />;
}
