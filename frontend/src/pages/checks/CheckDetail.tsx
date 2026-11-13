import { useState } from 'react';
import { Link, NavLink, useParams } from 'react-router';
import { loadCheckRun, runStatusLabels } from './checkData';
import type { RunDetails } from './checkData';
import { demoJob } from './demoData';
import { FindingsHttpError, loadFindings } from './loadFindings';
import { formatDecimal, formatLocation, statusLabels } from './reviewResult';
import type { ReviewResult } from './reviewResult';
import { useCheckData } from './useCheckData';

const tabs = [
  ['', 'Сверка'], ['/documents', 'Документы'], ['/exceptions', 'Исключения'],
  ['/conclusion', 'Заключение'], ['/log', 'Журнал проверки'],
];

type CheckView = 'table' | 'documents' | 'exceptions' | 'conclusion' | 'log';

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
      <Link to="/checks">← Все проверки</Link>
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
      <h1>{run.title}</h1>
      <p role="status">Состояние проверки · {runStatusLabels[status]}</p>
      {run.progress && (
        <p>Обработано документов: {run.progress.processed} из {run.progress.total}</p>
      )}
      {status === 'processing' && !run.progress && <p>Число обработанных документов пока неизвестно.</p>}
      {status === 'failed' && <p role="alert">{run.error ?? 'Не удалось выполнить проверку.'}</p>}
      {status === 'completed_with_issues' && run.error && <p role="alert">{run.error}</p>}
      {result && <ResultContent id={id} view={view} result={result} synthetic />}
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
    <ResultContent id={id} view={view} result={result} synthetic={synthetic} />
  </>;
}

interface ResultContentProps {
  id: string;
  view: CheckView;
  result: ReviewResult;
  synthetic: boolean;
}

function ResultContent({ id, view, result, synthetic }: ResultContentProps) {
  const { summary, documents, scope } = result;
  const runPath = '/checks/' + encodeURIComponent(id);

  return (
    <>
      <p>Договор {scope.contract_number} · {scope.period_start} — {scope.period_end}</p>
      <nav className="checks-tabs" aria-label="Разделы проверки">
        {tabs.map(([suffix, label]) => <NavLink key={suffix} to={runPath + suffix} end>{label}</NavLink>)}
      </nav>
      {view === 'table' && <>
        {result.rows.length > 0
          ? <Reconciliation result={result} />
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
          <button type="button" disabled aria-describedby="checks-export-note">Скачать XLSX</button>
          <p id="checks-export-note" className="checks-caption">
            Скачивание результата станет доступно после подключения экспорта.
          </p>
        </div>
      </section>}
      {view === 'log' && <CheckLog synthetic={synthetic} />}
    </>
  );
}

function Reconciliation({ result }: { result: ReviewResult }) {
  const { rows, evidence, documents, summary } = result;
  const [selectedId, setSelectedId] = useState(rows[0]?.id);
  const [evidenceId, setEvidenceId] = useState<string>();
  const row = rows.find(({ id }) => id === selectedId) ?? rows[0];
  const issue = summary.primary_issues.find(({ id }) => id === row?.root_issue_id);
  const fileErrorIds = new Set(issue?.file_error_refs);
  const affectedFiles = documents.filter((item) => item.errors.some((error) => fileErrorIds.has(error.id)));
  const refs = new Set([
    ...row?.reported_evidence_refs ?? [],
    ...row?.calculation?.components.flatMap((component) => [
      ...component.amount_refs,
      ...component.contract_refs,
      ...component.period_refs,
      ...component.article_refs,
      ...component.identity_refs ?? [],
    ]) ?? [],
    ...row?.reasons.flatMap((reason) => reason.evidence_refs) ?? [],
    ...row?.completeness.evidence_refs ?? [],
    ...issue?.evidence_refs ?? [],
  ]);
  const sources = evidence.filter(({ id }) => refs.has(id));
  const source = sources.find(({ id }) => id === evidenceId) ?? sources[0];
  const document = documents.find(({ id }) => id === source?.document_id);

  return (
    <div className="checks-reconcile">
      <section className="checks-card">
        <h2>Показатели</h2>
        <p className="checks-status" data-status={summary.counts.discrepancy > 0 ? 'discrepancy' : undefined}>
          Расхождения: {summary.counts.discrepancy}
        </p>
        <div className="checks-table-scroll">
          <table>
            <thead><tr><th>Показатель</th><th>КФЗ</th><th>По первичным документам</th><th>Δ</th><th>Статус</th></tr></thead>
            <tbody>{rows.map((item) => (
              <tr key={item.id} data-selected={item.id === row?.id}>
                <td><button type="button" aria-pressed={item.id === row?.id} onClick={() => {
                  setSelectedId(item.id);
                  setEvidenceId(undefined);
                }}>{item.label}</button></td>
                <td>{formatDecimal(item.reported_value)}</td>
                <td>
                  {formatDecimal(item.expected_value)}
                  {item.expected_value === null && item.observed_evidence_sum != null && (
                    <p className="checks-caption">Частичная сумма: {formatDecimal(item.observed_evidence_sum)} {item.unit}</p>
                  )}
                </td>
                <td>{formatDecimal(item.delta)}</td>
                <td><span className="checks-status" data-status={item.status}>{statusLabels[item.status]}</span></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        <p className="checks-caption">— означает, что значение отсутствует.</p>
      </section>
      <section className="checks-card checks-source">
        <h2>Источник</h2>
        {row && <>
          {row.calculation && <p>{row.calculation.formula}</p>}
          <p>Основание полноты: {row.completeness.reason}</p>
          {row.reasons.map((reason) => <p key={reason.code}>{reason.message}</p>)}
          {row.calculation && row.calculation.components.length > 0 && <details>
            <summary>Основания по слагаемым</summary>
            <ul>{row.calculation.components.map((component) => (
              <li key={component.amount_refs.join(' ')}>
                {formatDecimal(component.amount)} {row.unit} · {component.relation_reason}
              </li>
            ))}</ul>
          </details>}
        </>}
        {issue && <p>{issue.message}</p>}
        {affectedFiles.flatMap((item) => item.errors.filter((error) => fileErrorIds.has(error.id)).map((error) => (
          <p key={error.id}>{item.name} · {error.message}</p>
        )))}
        {sources.length > 0 && <label>Доказательство
          <select value={source?.id} onChange={(event) => setEvidenceId(event.target.value)}>
            {sources.map((item) => (
              <option key={item.id} value={item.id}>{documents.find(({ id }) => id === item.document_id)?.name}
                {' · '}{formatLocation(item.locator)}</option>
            ))}
          </select>
        </label>}
        {source && document ? (
          <dl>
            <dt>Документ</dt><dd>{document.name}</dd>
            {document.decision.state !== 'include' && <>
              <dt>Решение по документу</dt><dd>{decisions[document.decision.state]}</dd>
            </>}
            <dt>Адрес</dt><dd>{formatLocation(source.locator)}</dd>
            {'bbox' in source.locator && source.locator.bbox && <>
              <dt>Координаты фрагмента</dt><dd>{source.locator.bbox.join(', ')}</dd>
            </>}
            <dt>Значение источника</dt><dd>{source.raw_value}</dd>
          </dl>
        ) : <p>Адрес источника недоступен.</p>}
        <p className="checks-caption">Просмотр оригиналов подключается отдельно.</p>
      </section>
    </div>
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
