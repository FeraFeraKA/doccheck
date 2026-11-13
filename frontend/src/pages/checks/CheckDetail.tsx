import { useLayoutEffect, useRef, useState } from 'react';
import { Link, NavLink, useParams } from 'react-router';
import { loadCheckRun, runStatusLabels } from './checkData';
import type { RunDetails } from './checkData';
import { demoJob } from './demoData';
import { DocumentSourcePreview } from './DocumentSourcePreview';
import { FindingsHttpError, loadFindings } from './loadFindings';
import { formatDecimal, formatLocation, statusLabels } from './reviewResult';
import type { ReviewResult } from './reviewResult';
import { useCheckData } from './useCheckData';
import { isRunId } from './runStatusApi';
import { XlsxDownload } from './XlsxDownload';
import './result-workspace.css';

const tabs = [
  ['', 'Сверка'], ['/documents', 'Документы'], ['/exceptions', 'Исключения'],
  ['/conclusion', 'Заключение'], ['/log', 'Журнал проверки'],
];

const componentEvidenceFields = [
  ['amount_refs', 'Сумма'],
  ['contract_refs', 'Договор'],
  ['period_refs', 'Период'],
  ['article_refs', 'Статья'],
  ['identity_refs', 'Идентификация документа'],
] as const;

type CheckView = 'table' | 'documents' | 'exceptions' | 'conclusion' | 'log';

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
      <nav className="result-breadcrumb" aria-label="Путь к проверке">
        <Link to="/checks">← Все проверки</Link>
      </nav>
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

  return (
    <>
      {id === demoJob.run_id && <p className="checks-demo">Синтетическая сверка · готовый пример</p>}
      <div className="result-header">
        <h1>{run.title}</h1>
        <p role="status" className="result-run-state">Состояние проверки · {runStatusLabels[status]}</p>
      </div>
      {run.progress && (
        <p>Обработано документов: {run.progress.processed} из {run.progress.total}</p>
      )}
      {status === 'processing' && !run.progress && <p>Число обработанных документов пока неизвестно.</p>}
      {status === 'failed' && <p role="alert">{run.error ?? 'Не удалось выполнить проверку.'}</p>}
      {status === 'completed_with_issues' && run.error && <p role="alert">{run.error}</p>}
      {result && <ResultContent id={id} view={view} result={result} synthetic stored={false} />}
      {!result && hasStoredResult && <StoredFindings id={id} view={view} />}
    </>
  );
}

async function loadStoredFindings(id: string, signal: AbortSignal) {
  try {
    return await loadFindings(id, signal);
  } catch (error) {
    if (error instanceof FindingsHttpError && error.status === 409) return null;
    throw error;
  }
}

function StoredFindings({ id, view }: { id: string; view: CheckView }) {
  const { state, retry } = useCheckData(id, loadStoredFindings);

  if (state.phase === 'loading') return <p role="status">Загрузка результата сверки…</p>;
  if (state.phase === 'failed') return <section className="checks-card">
    <p role="alert">Не удалось загрузить результат сверки.</p>
    <button type="button" onClick={retry}>Повторить загрузку результата</button>
  </section>;

  if (state.data === null) return <section className="checks-card">
    <p role="status">Результат проверки недоступен.</p>
    <button type="button" onClick={retry}>Повторить загрузку результата</button>
  </section>;

  const { result, synthetic } = state.data;
  return <>
    {synthetic && <p className="checks-demo">Синтетический результат · сохранённая проверка</p>}
    <ResultContent id={id} view={view} result={result} synthetic={synthetic} stored />
  </>;
}

interface ResultContentProps {
  id: string;
  view: CheckView;
  result: ReviewResult;
  synthetic: boolean;
  stored: boolean;
}

function ResultContent({ id, view, result, synthetic, stored }: ResultContentProps) {
  const { summary, documents, scope } = result;
  const runPath = '/checks/' + encodeURIComponent(id);

  return (
    <>
      <p className="result-scope">Договор {scope.contract_number} · {scope.period_start} — {scope.period_end}</p>
      <nav className="result-tabs" aria-label="Разделы проверки">
        {tabs.map(([suffix, label]) => <NavLink key={suffix} to={runPath + suffix} end>{label}</NavLink>)}
      </nav>
      {view === 'table' && <>
        <div className="result-overview">
          <span><i aria-hidden="true" /> Подтверждено <strong>{summary.counts.verified}</strong></span>
          <span>Не проверено <strong>{summary.counts.unverified}</strong></span>
          <span>Документов <strong>{documents.length}</strong></span>
        </div>
        {result.rows.length > 0
          ? <Reconciliation result={result} storedRunId={stored ? id : undefined} />
          : <section className="checks-card"><h2>Показатели</h2><p>Показатели отсутствуют.</p></section>}
        {synthetic && summary.counts.discrepancy > 0 && <section className="checks-card">
          <h2>Возможные причины расхождений</h2>
          <p>Правила сверки могут предложить объяснение для проверки бухгалтером. В этом примере таких гипотез нет.</p>
        </section>}
      </>}
      {view === 'documents' && <Documents documents={documents} />}
      {view === 'exceptions' && (
        <Documents title="Исключения" documents={documents.filter((doc) => doc.decision.state !== 'include')}
          empty="Исключений нет."
          notice={synthetic ? 'Действия бухгалтера недоступны в синтетическом режиме.' : undefined} />
      )}
      {view === 'conclusion' && <section className="checks-card">
        <h2>Заключение</h2><p>{summary.conclusion}</p>
        <ul>{summary.primary_issues.map((issue) => <li key={issue.id}>{issue.message}</li>)}</ul>
        <div className="checks-export">
          {stored && isRunId(id) ? <XlsxDownload key={id} runId={id} /> : <>
            <button type="button" disabled aria-describedby="checks-export-note">Скачать XLSX</button>
            <p id="checks-export-note" className="checks-caption">
              Скачивание XLSX доступно для сохранённой проверки.
            </p>
          </>}
        </div>
      </section>}
      {view === 'log' && <CheckLog synthetic={synthetic} />}
    </>
  );
}

function Reconciliation({ result, storedRunId }: { result: ReviewResult; storedRunId?: string }) {
  const { rows, evidence, documents, summary } = result;
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState(() => rows.find(({ status }) => status === 'discrepancy')?.id);
  const [evidenceId, setEvidenceId] = useState<string>();
  const [openSourceId, setOpenSourceId] = useState<string>();
  const tableScroll = useRef<HTMLDivElement>(null);
  const selectedRow = useRef<HTMLTableRowElement>(null);
  const pendingIssueScroll = useRef<string>(undefined);
  const discrepancies = rows.filter(({ status }) => status === 'discrepancy');
  const search = query.trim().toLocaleLowerCase('ru');
  const visible = rows.filter(({ label, status }) =>
    (filter === 'all' || status === filter) && label.toLocaleLowerCase('ru').includes(search),
  );
  const row = visible.find(({ id }) => id === selectedId) ?? visible[0];
  const issueIndex = discrepancies.findIndex(({ id }) => id === row?.id);

  useLayoutEffect(() => {
    if (pendingIssueScroll.current === undefined || pendingIssueScroll.current !== selectedId) return;
    pendingIssueScroll.current = undefined;
    const container = tableScroll.current;
    const selected = selectedRow.current;
    if (!container || !selected) return;

    const rowBounds = selected.getBoundingClientRect();
    const containerBounds = container.getBoundingClientRect();
    const headerHeight = selected.closest('table')?.tHead?.offsetHeight ?? 0;
    const top = rowBounds.top - containerBounds.top - headerHeight;
    const bottom = rowBounds.bottom - containerBounds.top - container.clientHeight;
    if (top < 0) container.scrollTop += top;
    else if (bottom > 0) container.scrollTop += bottom;

    // On a narrow screen the table itself can sit below the viewport.
    const visibleBounds = selected.getBoundingClientRect();
    const viewportHeight = window.document.documentElement.clientHeight;
    if (visibleBounds.top < 0) window.scrollBy(0, visibleBounds.top);
    else if (visibleBounds.bottom > viewportHeight) window.scrollBy(0, visibleBounds.bottom - viewportHeight);
  }, [filter, query, selectedId]);

  function selectRow(id?: string) {
    setSelectedId(id);
    setEvidenceId(undefined);
    setOpenSourceId(undefined);
  }

  function moveIssue(direction: -1 | 1) {
    const next = issueIndex < 0 ? (direction === 1 ? 0 : discrepancies.length - 1) : issueIndex + direction;
    const issue = discrepancies[next];
    if (!issue) return;
    pendingIssueScroll.current = issue.id;
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
  const refs = new Set([
    ...row?.reported_evidence_refs ?? [],
    ...row?.calculation?.components.flatMap((component) =>
      componentEvidenceFields.flatMap(([field]) => component[field] ?? []),
    ) ?? [],
    ...row?.reasons.flatMap((reason) => reason.evidence_refs) ?? [],
    ...row?.completeness.evidence_refs ?? [],
    ...issue?.evidence_refs ?? [],
  ]);
  const sources = evidence.filter(({ id }) => refs.has(id));
  const sourcesById = new Map(sources.map((item) => [item.id, item]));
  const documentsById = new Map(documents.map((item) => [item.id, item]));
  const source = sources.find(({ id }) => id === evidenceId) ?? sources[0];
  const sourceIndex = sources.findIndex(({ id }) => id === source?.id);
  const document = source && documentsById.get(source.document_id);

  function selectSource(id: string) {
    setEvidenceId(id);
    setOpenSourceId(undefined);
  }

  return (
    <section className="result-reconciliation" aria-label="Рабочее место сверки">
      <div className="reconcile-commandbar">
        <div className="reconcile-command-title"><span className="reconcile-icon" aria-hidden="true">▤</span>
          <strong>Сверка с документами</strong>
        </div>
        <div className="issue-navigation">
          <p className="issue-counter">Расхождения: {summary.counts.discrepancy}</p>
          {discrepancies.length > 0 && <p aria-live="polite">
            Расхождение {issueIndex < 0 ? '—' : issueIndex + 1} из {discrepancies.length}
          </p>}
          <button type="button" aria-label="Предыдущее расхождение" disabled={discrepancies.length === 0 || issueIndex === 0}
            onClick={() => moveIssue(-1)}>↑</button>
          <button type="button" aria-label="Следующее расхождение" disabled={discrepancies.length === 0 || issueIndex === discrepancies.length - 1}
            onClick={() => moveIssue(1)}>↓</button>
        </div>
      </div>
      <div className="reconcile-panes">
        <section className="reconcile-left">
          <div className="reconcile-left-header"><div><h2>Показатели</h2>
            <p>Выберите показатель, чтобы открыть источник</p></div>
            <span className="record-count" aria-hidden="true">{visible.length}</span>
          </div>
          <div className="reconcile-filters" aria-label="Статус показателя">
            {filters.map(([value, label, count]) => <button type="button" key={value}
              aria-pressed={filter === value} onClick={() => { setFilter(value); selectRow(); }}>
              {label} <span>{count}</span>
            </button>)}
          </div>
          <div className="reconcile-search">
            <span aria-hidden="true">⌕</span>
            <input type="search" aria-label="Поиск показателя" placeholder="Поиск показателя…" value={query}
              onChange={(event) => { setQuery(event.target.value); selectRow(); }} />
          </div>
          <div ref={tableScroll} className="reconcile-table-scroll" role="region" aria-label="Таблица показателей" tabIndex={0}>
            <table className="reconcile-table">
              <thead><tr><th scope="col">Показатель</th><th scope="col">Ед. изм.</th><th scope="col">КФЗ</th><th scope="col">По первичным документам</th><th scope="col">Δ</th><th scope="col">Статус</th></tr></thead>
              <tbody>{visible.map((item) => (
                <tr key={item.id} ref={item.id === row?.id ? selectedRow : undefined} data-selected={item.id === row?.id} data-status={item.status}>
                  <td><button className="row-name-button" type="button" aria-pressed={item.id === row?.id} onClick={() => selectRow(item.id)}>
                    <span className="row-status" data-status={item.status} aria-hidden="true">{item.status === 'verified' ? '✓' : item.status === 'discrepancy' ? '!' : '–'}</span>
                    {item.label}
                  </button></td>
                  <td>{item.unit}</td>
                  <td>{formatDecimal(item.reported_value)}</td>
                  <td className="expected-cell">
                    {formatDecimal(item.expected_value)}
                    {item.expected_value === null && item.observed_evidence_sum != null && (
                      <p className="checks-caption">Частичная сумма: {formatDecimal(item.observed_evidence_sum)} {item.unit}</p>
                    )}
                  </td>
                  <td className="difference-cell">{formatDecimal(item.delta)}</td>
                  <td><span className="checks-status" data-status={item.status}>{statusLabels[item.status]}</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {visible.length === 0 && <p className="reconcile-left-footer">Показатели не найдены.</p>}
          <p className="reconcile-left-footer">— означает, что значение отсутствует.</p>
        </section>
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
            {sources.length > 0 && <div className="document-picker">
                <button type="button" aria-label="Предыдущий источник" disabled={sourceIndex <= 0}
                onClick={() => selectSource(sources[sourceIndex - 1].id)}>‹</button>
              <label>Доказательство
              <select value={source?.id} onChange={(event) => selectSource(event.target.value)}>
                {sources.map((item) => (
                  <option key={item.id} value={item.id}>{documentsById.get(item.document_id)?.name}
                    {' · '}{formatSourceChoice(item.locator)}</option>
                ))}
              </select>
              </label>
                <button type="button" aria-label="Следующий источник" disabled={sourceIndex >= sources.length - 1}
                onClick={() => selectSource(sources[sourceIndex + 1].id)}>›</button>
            </div>}
            {source && document ? (
              <dl className="source-address-card">
                <dt>Документ</dt><dd>{document.name}</dd>
                {document.decision.state !== 'include' && <>
                  <dt>Решение по документу</dt><dd>{decisions[document.decision.state]}</dd>
                </>}
                <dt>Адрес в результате</dt><dd>{formatLocation(source.locator)}</dd>
                {'bbox' in source.locator && source.locator.bbox && <>
                  <dt>Координаты фрагмента</dt><dd>{source.locator.bbox.join(', ')}</dd>
                </>}
                <dt>Значение источника</dt><dd>{source.raw_value}</dd>
              </dl>
            ) : <p>Адрес источника недоступен.</p>}
            {storedRunId && source && document && <>
              <button type="button" aria-expanded={openSourceId === source.id}
                onClick={() => setOpenSourceId(openSourceId === source.id ? undefined : source.id)}>
                {openSourceId === source.id ? 'Закрыть просмотр источника' : 'Просмотреть источник'}
              </button>
              {openSourceId === source.id && (
                <DocumentSourcePreview
                  runId={storedRunId}
                  document={{ id: document.id, name: document.name, format: document.format ?? null }}
                  evidenceId={source.id}
                />
              )}
            </>}
            {!storedRunId && <p className="checks-caption">В готовом примере доступны адреса источников.</p>}
            </div>
          </div>}
        </section>
      </div>
    </section>
  );
}

const decisions: Record<string, string> = {
  include: 'Включён', exclude: 'Исключён', needs_review: 'Требует проверки', parse_error: 'Ошибка чтения',
};

function Documents({ documents, title = 'Документы', empty = 'Документы отсутствуют.', notice }: {
  documents: ReviewResult['documents'];
  title?: string;
  empty?: string;
  notice?: string;
}) {
  return <section className="checks-card">
    <h2>{title}</h2>
    {notice && <p role="status" className="checks-caption">{notice}</p>}
    {documents.length === 0 ? <p>{empty}</p> : <div className="checks-table-scroll">
      <table>
        <thead><tr><th>Файл</th><th>Роль</th><th>Решение</th><th>Основание</th></tr></thead>
        <tbody>{documents.map((document) => (
          <tr key={document.id}>
            <td>{document.name}</td><td>{document.role === 'report' ? 'Отчёт' : 'Первичный документ'}</td>
            <td>{decisions[document.decision.state]}</td>
            <td>{document.decision.message}{document.errors.map((error) => <p key={error.id}>{error.message}</p>)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>}
  </section>;
}

export function CheckLog({ synthetic = true }: { synthetic?: boolean }) {
  const message = synthetic ? 'Записи журнала недоступны в синтетическом режиме.' : 'Журнал проверки пока недоступен.';
  return <section className="checks-card"><h2>Журнал действий</h2><p>{message}</p></section>;
}

export function CheckNotFound() {
  return <section className="checks-card"><h1>Проверка не найдена</h1></section>;
}
