import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router';
import { loadCheckRun, runStatusLabels } from './checkData';
import type { RunDetails } from './checkData';
import { demoJob } from './demoData';
import { DocumentSourcePreview } from './DocumentSourcePreview';
import { SourceDrawer } from './SourceDrawer';
import { SourceContext } from './SourceContext';
import { FindingsHttpError, loadFindings } from './loadFindings';
import { ResultHeader } from './ResultHeader';
import type { CheckView } from './ResultHeader';
import { ResultSummary, resultHeadline, resultTone } from './ResultSummary';
import { documentDecisionLabels, ResultDocuments } from './ResultDocuments';
import { ResultTable } from './ResultTable';
import { formatDecimal, formatLocation, statusLabels } from './reviewResult';
import type { ReviewResult } from './reviewResult';
import { useCheckData } from './useCheckData';
import './result-workspace.css';
import './result-focus.css';

const componentEvidenceFields = [
  ['amount_refs', 'Сумма'],
  ['contract_refs', 'Договор'],
  ['period_refs', 'Период'],
  ['article_refs', 'Статья'],
  ['identity_refs', 'Идентификация документа'],
] as const;

function formatSourceChoice(locator: ReviewResult['evidence'][number]['locator']) {
  const location = formatLocation(locator);
  return 'bbox' in locator && locator.bbox
    ? `${location} · Рамка (${locator.bbox.join(', ')})`
    : location;
}

export function CheckDetail({ view, loadRun = loadCheckRun }: {
  view: CheckView;
  loadRun?: (
    id: string, signal: AbortSignal, onUpdate: (run: RunDetails) => void,
  ) => Promise<RunDetails | null>;
}) {
  const { id = '' } = useParams();
  const { state, retry } = useCheckData(id, loadRun);

  return (
    <>
      {(state.phase !== 'ready' || !state.data) && (
        <nav className="result-breadcrumb" aria-label="Путь к проверке">
          <Link to="/checks">← Все проверки</Link>
        </nav>
      )}
      {state.phase === 'loading' && <p role="status">Загрузка проверки…</p>}
      {state.phase === 'failed' && <section className="checks-card">
        <p role="alert">Не удалось получить состояние проверки.</p>
        <button type="button" onClick={retry}>Повторить</button>
      </section>}
      {state.phase === 'ready' && (state.data
        ? <RunContent key={id} id={id} view={view} run={state.data} />
        : <CheckNotFound />)}
    </>
  );
}

function RunContent({ id, view, run }: { id: string; view: CheckView; run: RunDetails }) {
  const { result, status } = run;
  const hasStoredResult = status === 'completed' || status === 'completed_with_issues';
  if (result) return <ResultContent id={id} view={view} result={result} run={run} synthetic stored={false} />;
  if (hasStoredResult) return <StoredFindings id={id} view={view} run={run} />;
  return <PendingRun run={run} />;
}

function RunState({ run }: { run: RunDetails }) {
  const { status } = run;
  return <>
      <p role="status" className="result-run-state">Состояние проверки · {runStatusLabels[status]}</p>
      {run.progress && (
        <p>Обработано документов: {run.progress.processed} из {run.progress.total}</p>
      )}
      {status === 'processing' && !run.progress && <p>Число обработанных документов пока неизвестно.</p>}
      {status === 'failed' && <p role="alert">{run.error ?? 'Не удалось выполнить проверку.'}</p>}
      {status === 'completed_with_issues' && run.error && <p role="alert">{run.error}</p>}
  </>;
}

function PendingRun({ run }: { run: RunDetails }) {
  return <>
    <nav className="result-breadcrumb" aria-label="Путь к проверке">
      <Link to="/checks">← Все проверки</Link>
    </nav>
    <div className="result-header"><h1>{run.title}</h1></div>
    <RunState run={run} />
  </>;
}

async function loadStoredFindings(id: string, signal: AbortSignal) {
  try {
    return await loadFindings(id, signal);
  } catch (error) {
    if (error instanceof FindingsHttpError && error.status === 409) return null;
    throw error;
  }
}

function StoredFindings({ id, view, run }: { id: string; view: CheckView; run: RunDetails }) {
  const { state, retry } = useCheckData(id, loadStoredFindings);

  if (state.phase === 'loading') return <><PendingRun run={run} /><p role="status">Загрузка результата сверки…</p></>;
  if (state.phase === 'failed') return <><PendingRun run={run} /><section className="checks-card">
    <p role="alert">Не удалось загрузить результат сверки.</p>
    <button type="button" onClick={retry}>Повторить загрузку результата</button>
  </section></>;

  if (state.data === null) return <><PendingRun run={run} /><section className="checks-card">
    <p role="status">Результат проверки недоступен.</p>
    <button type="button" onClick={retry}>Повторить загрузку результата</button>
  </section></>;

  const { result, synthetic } = state.data;
  return <ResultContent id={id} view={view} result={result} run={run} synthetic={synthetic} stored />;
}

interface ResultContentProps {
  id: string;
  view: CheckView;
  result: ReviewResult;
  run: RunDetails;
  synthetic: boolean;
  stored: boolean;
}

function ResultContent({ id, view, result, run, synthetic, stored }: ResultContentProps) {
  const location = useLocation();
  const [rowJump, setRowJump] = useState<{ id: string; locationKey: string }>();
  const linkedRowJump = useMemo(() => {
    const id = new URLSearchParams(location.search).get('indicator');
    return id !== null && result.rows.some((row) => row.id === id) ? { id, locationKey: location.key } : undefined;
  }, [location.search, location.key, result.rows]);
  const { summary, scope } = result;
  const runPath = '/checks/' + encodeURIComponent(id);
  const tone = resultTone(summary.counts);
  const syntheticLabel = id === demoJob.run_id ? 'Синтетическая сверка · готовый пример'
    : synthetic ? 'Синтетический результат · сохранённая проверка' : undefined;

  return (
    <>
      <ResultHeader title={run.title} runPath={runPath} view={view} scope={scope}
        conclusion={resultHeadline[tone]} tone={tone} syntheticLabel={syntheticLabel} />
      {stored && <div className="stored-run-status mt-3 text-[13px]"><RunState run={run} /></div>}
      {(view === 'table' || view === 'conclusion') && <ResultSummary id={id} runPath={runPath} result={result} stored={stored}
        onOpenRow={view === 'table' ? (rowId) => setRowJump({ id: rowId, locationKey: location.key }) : undefined} />}
      {view === 'table' && <>
        <div className="mt-6">
          {result.rows.length > 0
            ? <Reconciliation result={result} storedRunId={stored ? id : undefined} rowJump={rowJump?.locationKey === location.key ? rowJump : linkedRowJump} />
            : <section className="checks-card"><h2>Показатели</h2><p>Показатели отсутствуют.</p></section>}
        </div>
        {synthetic && summary.counts.discrepancy > 0 && <section className="checks-card">
          <h2>Возможные причины расхождений</h2>
          <p>Правила сверки могут предложить объяснение для проверки бухгалтером. В этом примере таких гипотез нет.</p>
        </section>}
      </>}
      {(view === 'documents' || view === 'exceptions') && <ResultDocuments
        key={view} result={result} runPath={runPath} storedRunId={stored ? id : undefined}
        exceptions={view === 'exceptions'} synthetic={synthetic}
        rowEvidenceIds={resultRowEvidenceIds} formatAddress={formatSourceChoice}
      />}
      {view === 'log' && <CheckLog synthetic={synthetic} />}
    </>
  );
}

function resultRowEvidenceIds(
  row: ReviewResult['rows'][number] | undefined,
  issue: ReviewResult['summary']['primary_issues'][number] | undefined,
): string[] {
  if (!row) return [];
  return [
    ...row.reported_evidence_refs,
    ...row.calculation?.components.flatMap((component) =>
      componentEvidenceFields.flatMap(([field]) => component[field] ?? []),
    ) ?? [],
    ...row.reasons.flatMap((reason) => reason.evidence_refs),
    ...row.completeness.evidence_refs,
    ...issue?.evidence_refs ?? [],
  ];
}

function Reconciliation({ result, storedRunId, rowJump }: {
  result: ReviewResult;
  storedRunId?: string;
  rowJump?: { id: string };
}) {
  const { rows, evidence, documents, summary } = result;
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState(() => rows.find(({ status }) => status === 'discrepancy')?.id);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [evidenceId, setEvidenceId] = useState<string>();
  const [openSourceId, setOpenSourceId] = useState<string>();
  const [focused, setFocused] = useState(false);
  const workspace = useRef<HTMLDialogElement>(null);
  const focusToggle = useRef<HTMLButtonElement>(null);
  const restoreScroll = useRef<(() => void) | undefined>(undefined);
  const tableScroll = useRef<HTMLDivElement>(null);
  const selectedRow = useRef<HTMLTableRowElement>(null);
  const pendingIssueScroll = useRef<{ id: string; focus: boolean }>(undefined);
  const lastRowJump = useRef<typeof rowJump>(undefined);
  const discrepancies = rows.filter(({ status }) => status === 'discrepancy');
  const documentsById = new Map(documents.map((item) => [item.id, item]));
  const allEvidenceById = new Map(evidence.map((item) => [item.id, item]));
  const issuesById = new Map(summary.primary_issues.map((issue) => [issue.id, issue]));
  const search = query.trim().toLocaleLowerCase('ru');
  const visible = rows.filter((item) => {
    if (filter !== 'all' && item.status !== filter) return false;
    if (!search || item.label.toLocaleLowerCase('ru').includes(search)) return true;
    const issue = item.root_issue_id === null ? undefined : issuesById.get(item.root_issue_id);
    const fileErrors = new Set(issue?.file_error_refs);
    if (fileErrors.size > 0 && documents.some((file) =>
      file.name.toLocaleLowerCase('ru').includes(search) &&
      file.errors.some((error) => fileErrors.has(error.id)),
    )) return true;
    return resultRowEvidenceIds(item, issue).some((id) => {
      const evidenceItem = allEvidenceById.get(id);
      const name = evidenceItem && documentsById.get(evidenceItem.document_id)?.name;
      return name?.toLocaleLowerCase('ru').includes(search);
    });
  });
  const row = visible.find(({ id }) => id === selectedId) ?? visible[0];
  const issueIndex = discrepancies.findIndex(({ id }) => id === row?.id);

  useLayoutEffect(() => () => restoreScroll.current?.(), []);

  function closeFocus(restoreFocus = true) {
    const panel = workspace.current;
    if (!panel || !restoreScroll.current) return;
    const activeElement = window.document.activeElement;
    panel.close();
    panel.show();
    restoreScroll.current();
    restoreScroll.current = undefined;
    setFocused(false);
    const target = restoreFocus ? focusToggle.current : activeElement;
    if (target instanceof HTMLElement && panel.contains(target)) target.focus({ preventScroll: true });
  }

  function enterFocus() {
    const panel = workspace.current;
    if (!panel || restoreScroll.current) return;
    const previousOverflow = window.document.body.style.overflow;
    panel.close();
    panel.showModal();
    window.document.body.style.overflow = 'hidden';
    restoreScroll.current = () => { window.document.body.style.overflow = previousOverflow; };
    setFocused(true);
    focusToggle.current?.focus({ preventScroll: true });
  }

  function openSource(id: string) {
    closeFocus(false);
    setOpenSourceId(id);
  }

  useLayoutEffect(() => {
    if (!rowJump || rowJump === lastRowJump.current) return;
    lastRowJump.current = rowJump;
    const { id } = rowJump;
    pendingIssueScroll.current = { id, focus: true };
    setFilter('all');
    setQuery('');
    setSelectedId(id);
    setEvidenceId(undefined);
    setOpenSourceId(undefined);
    setExpanded((previous) => new Set(previous).add(id));
  }, [rowJump]);

  useLayoutEffect(() => {
    const target = pendingIssueScroll.current;
    if (!target || target.id !== selectedId || row?.id !== target.id) return;
    const container = tableScroll.current;
    const selected = selectedRow.current;
    if (!container || !selected) return;
    pendingIssueScroll.current = undefined;

    if (target.focus) selected.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
    const rowBounds = selected.getBoundingClientRect();
    const containerBounds = container.getBoundingClientRect();
    const headerHeight = selected.closest('table')?.tHead?.offsetHeight ?? 0;
    const top = rowBounds.top - containerBounds.top - headerHeight;
    const bottom = rowBounds.bottom - containerBounds.top - container.clientHeight;
    if (top < 0) container.scrollTop += top;
    else if (bottom > 0) container.scrollTop += bottom;

    // On a narrow screen the table itself can sit below the viewport.
    const visibleBounds = selected.getBoundingClientRect();
    const focusedPanel = focused ? workspace.current : null;
    if (focusedPanel) {
      const focusBounds = focusedPanel.getBoundingClientRect();
      const topOffset = visibleBounds.top - focusBounds.top;
      const bottomOffset = visibleBounds.bottom - focusBounds.bottom;
      if (topOffset < 0) focusedPanel.scrollTop += topOffset;
      else if (bottomOffset > 0) focusedPanel.scrollTop += bottomOffset;
      return;
    }
    const viewportHeight = window.document.documentElement.clientHeight;
    if (visibleBounds.top < 0) window.scrollBy(0, visibleBounds.top);
    else if (visibleBounds.bottom > viewportHeight) window.scrollBy(0, visibleBounds.bottom - viewportHeight);
  }, [expanded, filter, focused, query, row?.id, selectedId]);

  function selectRow(id?: string) {
    setSelectedId(id);
    setEvidenceId(undefined);
    setOpenSourceId(undefined);
  }

  function toggleRow(id: string) {
    selectRow(id);
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function moveIssue(direction: -1 | 1, focus = false) {
    const next = issueIndex < 0 ? (direction === 1 ? 0 : discrepancies.length - 1) : issueIndex + direction;
    const issue = discrepancies[next];
    if (!issue) return;
    pendingIssueScroll.current = { id: issue.id, focus };
    setExpanded((previous) => new Set(previous).add(issue.id));
    setQuery('');
    setFilter('discrepancy');
    selectRow(issue.id);
  }

  const filters = [
    ['all', 'Все', rows.length],
    ['discrepancy', 'Расхождения', summary.counts.discrepancy],
    ['unverified', 'Не проверено', summary.counts.unverified],
    ['verified', 'Подтверждено', summary.counts.verified],
  ] as const;
  const issue = summary.primary_issues.find(({ id }) => id === row?.root_issue_id);
  const fileErrorIds = new Set(issue?.file_error_refs);
  const affectedFiles = documents.filter((item) => item.errors.some((error) => fileErrorIds.has(error.id)));
  const refs = new Set(resultRowEvidenceIds(row, issue));
  const sources = evidence.filter(({ id }) => refs.has(id));
  const sourcesById = new Map(sources.map((item) => [item.id, item]));
  const source = sources.find(({ id }) => id === evidenceId) ?? sources[0];
  const sourceIndex = sources.findIndex(({ id }) => id === source?.id);
  const document = source && documentsById.get(source.document_id);

  function selectSource(id: string) {
    setEvidenceId(id);
    if (openSourceId) setOpenSourceId(id);
  }

  const sourcePicker = sources.length > 0 && <div className="document-picker">
    <button type="button" aria-label="Предыдущий источник" disabled={sourceIndex <= 0}
      onClick={() => selectSource(sources[sourceIndex - 1].id)}>‹</button>
    <label><span className="source-picker-caption">Доказательство</span>
      <select value={source?.id} onChange={(event) => selectSource(event.target.value)}>
        {sources.map((item) => (
          <option key={item.id} value={item.id}>{documentsById.get(item.document_id)?.name}
            {' · '}{formatSourceChoice(item.locator)}</option>
        ))}
      </select>
    </label>
    <button type="button" aria-label="Следующий источник" disabled={sourceIndex >= sources.length - 1}
      onClick={() => selectSource(sources[sourceIndex + 1].id)}>›</button>
  </div>;

  return (
    <dialog open ref={workspace} className="result-focus-dialog"
      aria-label={focused ? 'Полноэкранная сверка' : undefined}
      role={focused ? undefined : 'none'}
      onCancel={(event) => { event.preventDefault(); closeFocus(); }}>
    <section className="result-reconciliation" aria-label="Рабочее место сверки" onKeyDown={(event) => {
      if (openSourceId) return;
      if (focused && event.key === 'Escape') {
        event.preventDefault();
        closeFocus();
        return;
      }
      if (!event.altKey || (event.key !== 'ArrowDown' && event.key !== 'ArrowUp')) return;
      if (event.target instanceof HTMLElement && event.target.closest('input, select, textarea, [contenteditable="true"]')) return;
      event.preventDefault();
      moveIssue(event.key === 'ArrowDown' ? 1 : -1, true);
    }}>
      <div className="reconcile-commandbar">
        <h2 className="reconcile-title">Показатели отчёта</h2>
        <div className="issue-navigation">
          <p className="issue-counter">Расхождения: {summary.counts.discrepancy}</p>
          {discrepancies.length > 0 && <p aria-live="polite">
            Расхождение {issueIndex < 0 ? '—' : issueIndex + 1} из {discrepancies.length}
          </p>}
          <button type="button" aria-label="Предыдущее расхождение" title="Предыдущее расхождение · Alt + ↑" aria-keyshortcuts="Alt+ArrowUp" disabled={discrepancies.length === 0 || issueIndex === 0}
            onClick={() => moveIssue(-1)}>↑</button>
          <button type="button" aria-label="Следующее расхождение" title="Следующее расхождение · Alt + ↓" aria-keyshortcuts="Alt+ArrowDown" disabled={discrepancies.length === 0 || issueIndex === discrepancies.length - 1}
            onClick={() => moveIssue(1)}>↓</button>
          <button ref={focusToggle} type="button" aria-pressed={focused}
            aria-label={focused ? 'Выйти из полноэкранного режима' : 'На весь экран'}
            title={focused ? 'Выйти из полноэкранного режима' : 'На весь экран'}
            onClick={() => { if (focused) closeFocus(); else enterFocus(); }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d={focused ? 'M8 3v5H3m13-5v5h5M8 21v-5H3m13 5v-5h5' : 'M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3m13-5v3a2 2 0 0 1-2 2h-3'} />
            </svg>
          </button>
        </div>
      </div>
      <div className="reconcile-panes reconcile-panes-stacked">
        <ResultTable
          rows={visible} total={rows.length} filters={filters} filter={filter} query={query}
          selectedId={row?.id} selectedEvidenceId={source?.id} expanded={expanded}
          tableScroll={tableScroll} selectedRow={selectedRow} evidenceFields={componentEvidenceFields}
          evidenceById={allEvidenceById} documentsById={documentsById}
          formatAddress={formatSourceChoice}
          onFilterChange={(value) => { setFilter(value); selectRow(); }}
          onQueryChange={(value) => { setQuery(value); selectRow(); }}
          onReset={() => { setFilter('all'); setQuery(''); selectRow(); }}
          onToggle={toggleRow}
          onSelectSource={(rowId, id) => {
            setSelectedId(rowId);
            selectSource(id);
            if (storedRunId) openSource(id);
          }}
        />
        <section className="evidence-panel">
          {row ? <div className="evidence-header">
            <div className="evidence-heading"><h2>{row.label}</h2><span className="checks-status" data-status={row.status}>{statusLabels[row.status]}</span></div>
            <div className="evidence-amounts">
              <div><small>В КФЗ · {row.unit}</small><strong>{formatDecimal(row.reported_value)}</strong></div>
              <div className="expected-readout"><small>По документам · {row.unit}</small><strong>{formatDecimal(row.expected_value)}</strong></div>
              <div data-alert={row.status === 'discrepancy'}><small>Разница · {row.unit}</small><strong>{formatDecimal(row.delta)}</strong></div>
            </div>
          </div> : <p className="source-empty-state">Выберите показатель, чтобы увидеть источник.</p>}
          {row && <div className="evidence-source-content">
            <h3 className="evidence-tab-label">Источник</h3>
            <div className="source-document-content">
            <div className="evidence-rules">
              {row.calculation && <p>{row.calculation.formula}</p>}
              <p>Основание полноты: {row.completeness.reason}</p>
              {row.reasons.map((reason) => <p key={reason.code}>{reason.message}</p>)}
              {row.calculation && row.calculation.components.length > 0 && <details>
                <summary>Основания по слагаемым</summary>
                <ol aria-label="Слагаемые" className="component-evidence-list">{row.calculation.components.map((component) => (
                  <li key={component.amount_refs[0]}>
                    <p>{formatDecimal(component.amount)} {row.unit} · {component.relation_reason}</p>
                    <ul>{componentEvidenceFields.flatMap(([field, label]) =>
                      (component[field] ?? []).map((id) => {
                        const item = sourcesById.get(id);
                        const file = item && documentsById.get(item.document_id);
                        return <li key={field + ':' + id}>
                          {item && file ? (
                            <button type="button" aria-pressed={source?.id === id} onClick={() => selectSource(id)}>
                              {label} · {file.name} · {formatSourceChoice(item.locator)}
                            </button>
                          ) : <span>{label} · Адрес источника недоступен.</span>}
                        </li>;
                      }),
                    )}</ul>
                  </li>
                ))}</ol>
              </details>}
            </div>
            {issue && <p>{issue.message}</p>}
            {affectedFiles.flatMap((item) => item.errors.filter((error) => fileErrorIds.has(error.id)).map((error) => (
              <p key={error.id}>{item.name} · {error.message}</p>
            )))}
            {!openSourceId && sourcePicker}
            {source && document ? (
              <dl className="source-address-card">
                <dt>Документ</dt><dd>{document.name}</dd>
                {document.decision.state !== 'include' && <>
                  <dt>Решение по документу</dt><dd>{documentDecisionLabels[document.decision.state]}</dd>
                </>}
                <dt>Адрес в результате</dt><dd>{formatLocation(source.locator)}</dd>
                {'bbox' in source.locator && source.locator.bbox && <>
                  <dt>Координаты фрагмента</dt><dd>{source.locator.bbox.join(', ')}</dd>
                </>}
                <dt>Значение источника</dt><dd>{source.raw_value}</dd>
              </dl>
            ) : <p>Адрес источника недоступен.</p>}
            {storedRunId && source && document && <>
              <button type="button" aria-haspopup="dialog" aria-expanded={openSourceId === source.id}
                onClick={() => openSource(source.id)}>
                Просмотреть источник
              </button>
              {openSourceId === source.id && (
                <SourceDrawer onClose={() => setOpenSourceId(undefined)}>
                  <SourceContext row={row} picker={sourcePicker}>
                    {(active) => <DocumentSourcePreview
                      runId={storedRunId}
                      document={{ id: document.id, name: document.name, format: document.format ?? null }}
                      evidenceId={source.id}
                      active={active}
                    />}
                  </SourceContext>
                </SourceDrawer>
              )}
            </>}
            {!storedRunId && <p className="checks-caption">В готовом примере доступны адреса источников.</p>}
            </div>
          </div>}
        </section>
      </div>
    </section>
    </dialog>
  );
}

export function CheckLog({ synthetic = true }: { synthetic?: boolean }) {
  const message = synthetic ? 'Записи журнала недоступны в синтетическом режиме.' : 'Журнал проверки пока недоступен.';
  return <section className="checks-card"><h2>Журнал действий</h2><p>{message}</p></section>;
}

export function CheckNotFound() {
  return <section className="checks-card"><h1>Проверка не найдена</h1></section>;
}
