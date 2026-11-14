import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { DocumentSourcePreview } from './DocumentSourcePreview';
import type { DocumentImageView } from './DocumentSourcePreview';
import { SourceContext } from './SourceContext';
import { preserveSourceViewport } from './SourceDrawer';
import { formatLocation } from './reviewResult';
import type { PageAddress, ReviewResult } from './reviewResult';
import { strongestTone } from './sourceHighlights';
import type { SourceTone } from './sourceHighlights';
import { WorkspaceIcon } from './WorkspaceIcon';
import './source-workspace.css';

type Evidence = ReviewResult['evidence'][number];
type Row = ReviewResult['rows'][number];
const reportScopeAddressId = 'scope:report';
const documentOverviewId = '';

interface Selection {
  documentId: string;
  evidenceId?: string;
  scopeOnly?: boolean;
  row?: Row;
  rowEvidenceIds: readonly string[];
}

export function useSourceWorkspace({
  result, storedRunId, initialDocumentId, initialEvidenceId, initialScopeOnly,
  onClose, onEvidenceChange, onSelectionChange,
}: {
  result: ReviewResult;
  storedRunId?: string;
  initialDocumentId?: string;
  initialEvidenceId?: string;
  initialScopeOnly?: boolean;
  onClose?: () => void;
  onEvidenceChange?: (id: string | undefined) => void;
  onSelectionChange?: (documentId: string, evidenceId?: string, scopeOnly?: boolean) => void;
}) {
  const { documents, evidence } = result;
  const report = documents.find(({ id }) => id === result.scope.report_document_id)
    ?? documents.find(({ role }) => role === 'report');
  const evidenceById = useMemo(() => new Map(evidence.map((item) => [item.id, item])), [evidence]);
  const evidenceByDocument = useMemo(() => {
    const byDocument = new Map<string, Evidence[]>();
    for (const item of evidence) {
      const previous = byDocument.get(item.document_id);
      if (previous) previous.push(item);
      else byDocument.set(item.document_id, [item]);
    }
    return byDocument;
  }, [evidence]);
  const tonesByEvidenceId = useMemo(() => {
    const tones = new Map<string, SourceTone>();
    for (const row of result.rows) {
      const status = row.status;
      if (status !== 'discrepancy' && status !== 'unverified' && status !== 'verified') continue;
      const ids = [...row.reported_evidence_refs,
        ...(row.calculation?.components.flatMap(({ amount_refs }) => amount_refs) ?? [])];
      for (const id of ids) {
        const tone = strongestTone(tones.get(id), status);
        if (tone) tones.set(id, tone);
      }
    }
    return tones;
  }, [result.rows]);
  const [initialSelection] = useState(() => {
    if (initialDocumentId === undefined || !documents.some(({ id }) => id === initialDocumentId)) return;
    const evidenceId = evidenceByDocument.get(initialDocumentId)?.find(({ id }) => id === initialEvidenceId)?.id;
    const scopeOnly = !evidenceId && initialScopeOnly && initialDocumentId === report?.id
      && result.scope.report_row_locator != null && 'page' in result.scope.report_row_locator;
    return { documentId: initialDocumentId, evidenceId, scopeOnly, rowEvidenceIds: [] };
  });
  const [open, setOpen] = useState(Boolean(initialSelection));
  const [selection, setSelection] = useState<Selection | undefined>(initialSelection);
  const [focusRequest, setFocusRequest] = useState(initialSelection ? 1 : 0);
  const returnFocusRoot = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const defaultDocumentId = report?.id ?? documents[0]?.id;
  const scopeAddressId = useMemo(() => {
    let id = reportScopeAddressId;
    while (evidenceById.has(id)) id += ':';
    return id;
  }, [evidenceById]);

  function show(next: Selection | undefined, from?: HTMLElement) {
    trigger.current = from ?? null;
    setSelection(next);
    if (next) onSelectionChange?.(next.documentId, next.evidenceId);
    setFocusRequest((previous) => previous + 1);
    setOpen(true);
  }

  function openEvidence(evidenceId: string, from?: HTMLElement, row?: Row, evidenceIds: readonly string[] = [evidenceId]) {
    const source = evidenceById.get(evidenceId);
    if (source) show({ documentId: source.document_id, evidenceId, row, rowEvidenceIds: evidenceIds }, from);
  }

  function openDocument(documentId: string, from?: HTMLElement, evidenceId?: string) {
    if (!documents.some(({ id }) => id === documentId)) return;
    const selectedEvidence = evidenceByDocument.get(documentId)?.find(({ id }) => id === evidenceId);
    show({ documentId, evidenceId: selectedEvidence?.id, rowEvidenceIds: [] }, from);
  }

  function close() {
    setOpen(false);
    onClose?.();
    const routeFocus = returnFocusRoot.current?.closest('main')?.querySelector<HTMLElement>(
      '[aria-label="Разделы проверки"] [aria-current="page"]',
    );
    const target = trigger.current?.isConnected ? trigger.current : routeFocus;
    requestAnimationFrame(() => target?.focus({ preventScroll: !window.matchMedia('(max-width: 700px)').matches }));
  }

  const clear = useCallback(() => {
    setOpen(false);
    setSelection(undefined);
    trigger.current = null;
  }, []);

  function selectEvidence(evidenceId: string) {
    if (evidenceId === documentOverviewId || evidenceId === scopeAddressId) {
      if (!documentId) return;
      const scopeOnly = evidenceId === scopeAddressId && Boolean(reportPage);
      onEvidenceChange?.(undefined);
      onSelectionChange?.(documentId, undefined, scopeOnly);
      setSelection((previous) => ({ ...previous, documentId, evidenceId: undefined, scopeOnly,
        rowEvidenceIds: previous?.rowEvidenceIds ?? [] }));
      return;
    }
    const source = evidenceById.get(evidenceId);
    if (!source) return;
    onEvidenceChange?.(evidenceId);
    onSelectionChange?.(source.document_id, evidenceId);
    setSelection({ ...selection, documentId: source.document_id, evidenceId, scopeOnly: false,
      rowEvidenceIds: selection?.rowEvidenceIds ?? [] });
  }

  const rowSources = (selection?.rowEvidenceIds ?? []).flatMap((id) => {
    const item = evidenceById.get(id);
    return item ? [item] : [];
  });
  const documentId = selection?.documentId ?? defaultDocumentId;
  const reportLocator = documentId === report?.id ? result.scope.report_row_locator : undefined;
  const reportPage: PageAddress | undefined = reportLocator && 'page' in reportLocator ? reportLocator : undefined;
  const documentSources = documentId ? evidenceByDocument.get(documentId) ?? [] : [];
  const sources = [...new Map([...rowSources, ...documentSources].map((item) => [item.id, item])).values()];
  const selected = selection?.evidenceId === undefined ? undefined : evidenceById.get(selection.evidenceId);
  const row = selection?.row;
  const unverifiedRows = result.rows.filter((item) => item.status === 'unverified' && item.reported_value === null);
  const selectedRow = selected && rowSources.some(({ id }) => id === selected.id) ? row : undefined;
  const status = selectedRow?.status ?? (selected && tonesByEvidenceId.get(selected.id));
  const tone: SourceTone | undefined = status === 'discrepancy' || status === 'unverified' || status === 'verified'
    ? status : undefined;
  const highlights = documentSources.flatMap(({ id, locator }) => {
    const tone = tonesByEvidenceId.get(id);
    return tone ? [{ locator, tone }] : [];
  });

  function selectDocument(id: string) {
    if (id === documentId) return;
    onEvidenceChange?.(undefined);
    onSelectionChange?.(id);
    setSelection((previous) => ({ ...previous, documentId: id, evidenceId: undefined, scopeOnly: false,
      rowEvidenceIds: previous?.rowEvidenceIds ?? [] }));
  }

  return {
    open, documentId, defaultDocumentId, evidenceId: selected?.id, rowId: open ? selectedRow?.id : undefined,
    openEvidence, openDocument, close, clear, returnFocusRoot, focusRequest, row,
    selectDocument, selectEvidence, selected, documents, sources, storedRunId, unverifiedRows,
    tone, highlights,
    scopeAddressId, reportPage, scopeOnly: selection?.scopeOnly ?? false,
  };
}

export function ResultSourceWorkspace({ result, storedRunId }: { result: ReviewResult; storedRunId?: string }) {
  const workspace = useSourceWorkspace({ result, storedRunId });
  return <SourceWorkspace workspace={workspace} />;
}

function PanelIcon({ name }: { name: 'previous' | 'next' | 'expand' | 'collapse' | 'close' }) {
  const paths = {
    previous: 'm15 18-6-6 6-6',
    next: 'm9 18 6-6-6-6',
    expand: 'M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3m13-5v3a2 2 0 0 1-2 2h-3',
    collapse: 'M8 3v5H3m13-5v5h5M8 21v-5H3m13 5v-5h5',
    close: 'm6 6 12 12M18 6 6 18',
  };
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

export function SourceWorkspace({ workspace }: { workspace: ReturnType<typeof useSourceWorkspace> }) {
  const { open, close, focusRequest, returnFocusRoot } = workspace;
  const panelId = useId();
  const panel = useRef<HTMLDialogElement>(null);
  const lastFocus = useRef(0);
  const sizeControl = useRef<HTMLButtonElement>(null);
  const closeControl = useRef<HTMLButtonElement>(null);
  const [imageViews, setImageViews] = useState(() => new Map<string, DocumentImageView>());
  const [fullscreen, setFullscreen] = useState(false);
  const restoreViewport = useRef<() => void>(undefined);
  if (!open && fullscreen) setFullscreen(false);
  const expanded = open && fullscreen;

  useLayoutEffect(() => {
    const element = panel.current;
    if (!element || !open) return;
    if (expanded) {
      element.close();
      element.showModal();
      const previousOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      sizeControl.current?.focus({ preventScroll: true });
      restoreViewport.current?.();
      restoreViewport.current = undefined;
      return () => {
        element.close();
        document.body.style.overflow = previousOverflow;
      };
    }
    element.open = true;
    if (restoreViewport.current) {
      sizeControl.current?.focus({ preventScroll: true });
      restoreViewport.current();
      restoreViewport.current = undefined;
    }
  }, [open, expanded]);

  useLayoutEffect(() => {
    if (!open || focusRequest === lastFocus.current) return;
    lastFocus.current = focusRequest;
    if (window.matchMedia('(max-width: 700px)').matches) {
      panel.current?.scrollIntoView({ block: 'start' });
    }
    closeControl.current?.focus({ preventScroll: true });
  }, [open, focusRequest]);

  useEffect(() => {
    if (!open || expanded) return;
    function handleEscape(event: KeyboardEvent) {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      if (event.target instanceof Element && event.target.closest('dialog:modal')) return;
      event.preventDefault();
      close();
    }
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [open, expanded, close]);

  function toggleFullscreen() {
    if (panel.current) restoreViewport.current = preserveSourceViewport(panel.current);
    setFullscreen((previous) => !previous);
  }

  const documentIndex = workspace.documents.findIndex(({ id }) => id === workspace.documentId);
  const selectedDocument = workspace.documents[documentIndex];
  const filenameById = new Map(workspace.documents.map(({ id, name }) => [id, name]));
  const evidenceIndex = workspace.sources.findIndex(({ id }) => id === workspace.evidenceId);
  const scopeLabel = workspace.reportPage && formatLocation(workspace.reportPage);
  const showScopeAddress = scopeLabel && (workspace.scopeOnly || !workspace.sources.some(({ locator }) =>
    formatLocation(locator) === scopeLabel));
  const hasAddresses = workspace.sources.length > 0 || Boolean(showScopeAddress);
  function unverifiedReading(source: Evidence): string | undefined {
    const candidates = workspace.row ? [workspace.row] : workspace.unverifiedRows;
    const row = candidates.find((item) => item.status === 'unverified' && item.reported_value === null
      && item.reported_evidence_refs.includes(source.id));
    if (!row) return;
    const ids = [...new Set(row.reported_evidence_refs)];
    const number = ids.length > 1 ? ` ${ids.indexOf(source.id) + 1}` : '';
    return `Непроверенное чтение${number}`;
  }
  const selectedReading = workspace.selected && unverifiedReading(workspace.selected);
  const picker = hasAddresses && <div className="source-document-select source-evidence-select">
    {workspace.row && <button type="button" aria-label="Предыдущий источник" disabled={evidenceIndex <= 0}
      onClick={() => workspace.selectEvidence(workspace.sources[evidenceIndex - 1].id)}><PanelIcon name="previous" /></button>}
    <select aria-label={workspace.row ? 'Доказательство' : 'Адрес доказательства'}
      value={workspace.evidenceId ?? (workspace.scopeOnly ? workspace.scopeAddressId : documentOverviewId)}
      onChange={(event) => workspace.selectEvidence(event.currentTarget.value)}>
      <option value={documentOverviewId}>Документ целиком</option>
      {showScopeAddress && <option value={workspace.scopeAddressId}>
        Строка КФЗ · {scopeLabel}
      </option>}
      {workspace.sources.map((source) => {
        const reading = unverifiedReading(source);
        return <option key={source.id} value={source.id}>
          {reading && `${reading} · `}
          {workspace.row && `${filenameById.get(source.document_id) ?? 'Документ'} · `}{formatLocation(source.locator)}
        </option>;
      })}
    </select>
    {workspace.row && <button type="button" aria-label="Следующий источник" disabled={evidenceIndex >= workspace.sources.length - 1}
      onClick={() => workspace.selectEvidence(workspace.sources[evidenceIndex + 1].id)}><PanelIcon name="next" /></button>}
  </div>;

  function preview(active: boolean): ReactNode {
    if (!selectedDocument) return <p className="source-workspace-notice">Документы комплекта отсутствуют.</p>;
    return <>
      {selectedReading && workspace.selected && <p className="source-workspace-notice" aria-live="polite">
        <strong>{selectedReading}:</strong> {workspace.selected.raw_value}
      </p>}
      {selectedDocument.decision.state !== 'include' && <p className="source-workspace-notice" role="status">
        {selectedDocument.decision.message}
      </p>}
      {workspace.storedRunId ? <DocumentSourcePreview
        runId={workspace.storedRunId} document={{ ...selectedDocument, format: selectedDocument.format ?? null }}
        evidenceId={workspace.evidenceId ?? null}
        tone={workspace.tone}
        highlights={workspace.highlights}
        addressInPicker={hasAddresses}
        reportPage={workspace.scopeOnly ? workspace.reportPage : undefined}
        active={active} compact imageView={imageViews.get(selectedDocument.id) ?? { zoom: 100, highlight: true }}
        onImageViewChange={(view) => setImageViews((previous) => new Map(previous).set(selectedDocument.id, view))}
      /> : <div className="source-viewer source-workspace-empty" aria-label="Просмотр источника" role="region">
        <div className="source-viewer-placeholder">
          <p>Оригинал документа недоступен.</p>
          {!hasAddresses && <p>Адрес фрагмента отсутствует.</p>}
        </div>
        {workspace.selected?.raw_value != null && <div className="source-viewer-footer">
          <div><small>Выбранный фрагмент</small><strong>{workspace.selected.raw_value}</strong></div>
        </div>}
      </div>}
    </>;
  }

  const sizeLabel = expanded ? 'Свернуть источник в боковую панель' : 'Развернуть источник на весь экран';
  const launchLabel = open ? 'Скрыть просмотр документов' : 'Открыть просмотр документов';
  return <div ref={returnFocusRoot} className="source-workspace" data-source-open={open}>
    {workspace.defaultDocumentId && <button type="button" className="source-workspace-launch"
      aria-label={launchLabel} title={launchLabel} aria-expanded={open} aria-controls={open ? panelId : undefined}
      onClick={(event) => {
        if (open) close();
        else if (workspace.defaultDocumentId) workspace.openDocument(workspace.defaultDocumentId, event.currentTarget);
      }}><WorkspaceIcon name={open ? 'eyeOff' : 'eye'} /></button>}
    {open && <dialog ref={panel} id={panelId} aria-label="Источник документа"
      role={expanded ? undefined : 'region'} className="source-workspace-panel compact-source" data-fullscreen={expanded}
      onCancel={(event) => { event.preventDefault(); close(); }}>
      <header className="source-workspace-controls">
        <h2 className="sr-only">Источник документа</h2>
        {workspace.documents.length > 0 && <div className="source-document-select">
          <button type="button" aria-label="Предыдущий документ" disabled={documentIndex <= 0}
            onClick={() => workspace.selectDocument(workspace.documents[documentIndex - 1].id)}><PanelIcon name="previous" /></button>
          <select aria-label="Документы комплекта" title={selectedDocument?.name} value={selectedDocument?.id ?? ''}
            onChange={(event) => workspace.selectDocument(event.currentTarget.value)}>
            {workspace.documents.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
          </select>
          <button type="button" aria-label="Следующий документ" disabled={documentIndex >= workspace.documents.length - 1}
            onClick={() => workspace.selectDocument(workspace.documents[documentIndex + 1].id)}><PanelIcon name="next" /></button>
        </div>}
        <button ref={sizeControl} type="button" aria-label={sizeLabel} title={sizeLabel} aria-pressed={expanded}
          onClick={toggleFullscreen}><PanelIcon name={expanded ? 'collapse' : 'expand'} /></button>
        <button ref={closeControl} type="button" aria-label="Закрыть просмотр источника" title="К таблице" onClick={close}><PanelIcon name="close" /></button>
      </header>
      {workspace.row ? <SourceContext row={workspace.row} picker={picker} compact>{preview}</SourceContext> : <>
        {picker}
        {preview(true)}
      </>}
    </dialog>}
  </div>;
}
