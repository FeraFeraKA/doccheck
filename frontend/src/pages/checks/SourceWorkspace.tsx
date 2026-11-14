import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { DocumentSourcePreview } from './DocumentSourcePreview';
import type { DocumentImageView } from './DocumentSourcePreview';
import { SourceContext } from './SourceContext';
import { preserveSourceViewport } from './SourceDrawer';
import { formatLocation } from './reviewResult';
import type { ReviewResult } from './reviewResult';
import './source-workspace.css';

type Evidence = ReviewResult['evidence'][number];
type Row = ReviewResult['rows'][number];

interface Selection {
  documentId: string;
  evidenceId?: string;
  row?: Row;
  rowEvidenceIds: readonly string[];
}

export function useSourceWorkspace({
  result, storedRunId, initialDocumentId, initialEvidenceId, onClose, onEvidenceChange, onSelectionChange,
}: {
  result: ReviewResult;
  storedRunId?: string;
  initialDocumentId?: string;
  initialEvidenceId?: string;
  onClose?: () => void;
  onEvidenceChange?: (id: string | undefined) => void;
  onSelectionChange?: (documentId: string, evidenceId?: string) => void;
}) {
  const { documents, evidence } = result;
  const report = documents.find(({ role }) => role === 'report');
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
  const [initialSelection] = useState(() => {
    if (initialDocumentId === undefined || !documents.some(({ id }) => id === initialDocumentId)) return;
    const sources = evidenceByDocument.get(initialDocumentId);
    const selectedEvidence = sources?.find(({ id }) => id === initialEvidenceId) ?? sources?.[0];
    return { documentId: initialDocumentId, evidenceId: selectedEvidence?.id, rowEvidenceIds: [] };
  });
  const [open, setOpen] = useState(Boolean(initialSelection));
  const [selection, setSelection] = useState<Selection | undefined>(initialSelection);
  const [focusRequest, setFocusRequest] = useState(initialSelection ? 1 : 0);
  const toggle = useRef<HTMLButtonElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const defaultDocumentId = report?.id ?? documents[0]?.id;

  function show(next: Selection | undefined, from?: HTMLElement) {
    trigger.current = from ?? toggle.current;
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
    const sources = evidenceByDocument.get(documentId);
    const selectedEvidence = sources?.find(({ id }) => id === evidenceId) ?? sources?.[0];
    show({ documentId, evidenceId: selectedEvidence?.id, rowEvidenceIds: [] }, from);
  }

  function close() {
    setOpen(false);
    onClose?.();
    const target = trigger.current?.isConnected ? trigger.current : toggle.current;
    requestAnimationFrame(() => target?.focus({ preventScroll: !window.matchMedia('(max-width: 700px)').matches }));
  }

  const clear = useCallback(() => {
    setOpen(false);
    setSelection(undefined);
    trigger.current = null;
  }, []);

  function selectEvidence(evidenceId: string) {
    const source = evidenceById.get(evidenceId);
    if (!source) return;
    onEvidenceChange?.(evidenceId);
    onSelectionChange?.(source.document_id, evidenceId);
    setSelection({ ...selection, documentId: source.document_id, evidenceId,
      rowEvidenceIds: selection?.rowEvidenceIds ?? [] });
  }

  const rowSources = (selection?.rowEvidenceIds ?? []).flatMap((id) => {
    const item = evidenceById.get(id);
    return item ? [item] : [];
  });
  const documentId = selection?.documentId ?? defaultDocumentId;
  const documentSources = documentId ? evidenceByDocument.get(documentId) ?? [] : [];
  const sources = [...new Map([...rowSources, ...documentSources].map((item) => [item.id, item])).values()];
  const selected = selection?.evidenceId === undefined ? undefined : evidenceById.get(selection.evidenceId);
  const row = selected && rowSources.some(({ id }) => id === selected.id) ? selection?.row : undefined;

  function selectDocument(id: string) {
    const previous = selection?.documentId === id ? selected : undefined;
    const source = previous ?? rowSources.find(({ document_id }) => document_id === id) ?? evidenceByDocument.get(id)?.[0];
    onEvidenceChange?.(source?.id);
    onSelectionChange?.(id, source?.id);
    setSelection({ ...selection, documentId: id, evidenceId: source?.id, rowEvidenceIds: selection?.rowEvidenceIds ?? [] });
  }

  return {
    open, documentId, evidenceId: selected?.id, rowId: open ? row?.id : undefined,
    openEvidence, openDocument, close, clear, toggle, focusRequest, row,
    selectDocument, selectEvidence, selected, documents, sources, storedRunId,
    togglePanel: () => {
      if (open) close();
      else if (!selection && defaultDocumentId) openDocument(defaultDocumentId);
      else show(selection);
    },
  };
}

function PanelIcon({ name }: { name: 'eye' | 'eye-off' | 'previous' | 'next' | 'expand' | 'collapse' | 'close' }) {
  const paths = {
    eye: 'M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
    'eye-off': 'M10.73 5.08A10.75 10.75 0 0 1 21.94 11.65a1 1 0 0 1 0 .7 10.77 10.77 0 0 1-1.57 2.62M6.61 6.61a10.75 10.75 0 0 0-4.55 5.04 1 1 0 0 0 0 .7 10.75 10.75 0 0 0 13.3 5.99M14.12 14.12a3 3 0 0 1-4.24-4.24M3 3l18 18',
    previous: 'm15 18-6-6 6-6',
    next: 'm9 18 6-6-6-6',
    expand: 'M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3m13-5v3a2 2 0 0 1-2 2h-3',
    collapse: 'M8 3v5H3m13-5v5h5M8 21v-5H3m13 5v-5h5',
    close: 'm6 6 12 12M18 6 6 18',
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

export function SourceWorkspace({ workspace }: { workspace: ReturnType<typeof useSourceWorkspace> }) {
  const { open, close, toggle, focusRequest, togglePanel } = workspace;
  const panelId = useId();
  const panel = useRef<HTMLDialogElement>(null);
  const lastFocus = useRef(0);
  const sizeControl = useRef<HTMLButtonElement>(null);
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
    toggle.current?.focus({ preventScroll: true });
  }, [open, focusRequest, toggle]);

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
  const picker = workspace.sources.length > 0 && <div className="source-document-select source-evidence-select">
    {workspace.row && <button type="button" aria-label="Предыдущий источник" disabled={evidenceIndex <= 0}
      onClick={() => workspace.selectEvidence(workspace.sources[evidenceIndex - 1].id)}><PanelIcon name="previous" /></button>}
    <select aria-label={workspace.row ? 'Доказательство' : 'Адрес доказательства'} value={workspace.evidenceId ?? ''}
      onChange={(event) => workspace.selectEvidence(event.currentTarget.value)}>
      {!workspace.evidenceId && <option value="" disabled>Выберите фрагмент</option>}
      {workspace.sources.map(({ id, document_id: documentId, locator }) => <option key={id} value={id}>
        {workspace.row && `${filenameById.get(documentId) ?? 'Документ'} · `}{formatLocation(locator)}
      </option>)}
    </select>
    {workspace.row && <button type="button" aria-label="Следующий источник" disabled={evidenceIndex >= workspace.sources.length - 1}
      onClick={() => workspace.selectEvidence(workspace.sources[evidenceIndex + 1].id)}><PanelIcon name="next" /></button>}
  </div>;

  function preview(active: boolean): ReactNode {
    if (!selectedDocument) return <p className="source-workspace-notice">Документы комплекта отсутствуют.</p>;
    return <>
      {selectedDocument.decision.state !== 'include' && <p className="source-workspace-notice" role="status">
        {selectedDocument.decision.message}
      </p>}
      {workspace.storedRunId ? <DocumentSourcePreview
        runId={workspace.storedRunId} document={{ ...selectedDocument, format: selectedDocument.format ?? null }}
        evidenceId={workspace.evidenceId ?? null} active={active} compact imageView={imageViews.get(selectedDocument.id) ?? { zoom: 100, highlight: true }}
        onImageViewChange={(view) => setImageViews((previous) => new Map(previous).set(selectedDocument.id, view))}
      /> : <div className="source-viewer source-workspace-empty" aria-label="Просмотр источника" role="region">
        <div className="source-viewer-placeholder">
          <p>Оригинал в готовом примере недоступен.</p>
          <p>{workspace.selected ? formatLocation(workspace.selected.locator) : 'Адрес фрагмента отсутствует.'}</p>
        </div>
        {workspace.selected?.raw_value != null && <div className="source-viewer-footer">
          <div><small>Выбранный фрагмент</small><strong>{workspace.selected.raw_value}</strong></div>
        </div>}
      </div>}
    </>;
  }

  const sizeLabel = expanded ? 'Свернуть источник в боковую панель' : 'Развернуть источник на весь экран';
  return <div className="source-workspace" data-source-open={open}>
    <div role="group" className="source-workspace-rail" aria-label="Управление источником">
      <button ref={toggle} type="button" className={open ? 'nav-item source-workspace-toggle active' : 'nav-item source-workspace-toggle'}
        aria-label={open ? 'Скрыть источник документа' : 'Показать источник документа'}
        title={open ? 'Скрыть источник' : 'Открыть источник'}
        aria-expanded={open} aria-controls={open ? panelId : undefined} onClick={togglePanel}>
        <PanelIcon name={open ? 'eye' : 'eye-off'} />
      </button>
    </div>
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
        <button type="button" aria-label="Закрыть просмотр источника" title="К таблице" onClick={close}><PanelIcon name="close" /></button>
      </header>
      {workspace.row ? <SourceContext row={workspace.row} picker={picker} compact>{preview}</SourceContext> : <>
        {picker}
        {preview(true)}
      </>}
    </dialog>}
  </div>;
}
