import { useState } from 'react';
import { Link, NavLink, useParams } from 'react-router';
import { loadDemoRun, runStatusLabels } from './checkData';
import type { RunDetails } from './checkData';
import { formatDecimal, formatLocation, statusLabels } from './reviewResult';
import type { ReviewResult } from './reviewResult';
import { useCheckData } from './useCheckData';

const tabs = [
  ['', 'Сверка'], ['/documents', 'Документы'], ['/exceptions', 'Исключения'],
  ['/conclusion', 'Заключение'], ['/log', 'Журнал проверки'],
];

type CheckView = 'table' | 'documents' | 'exceptions' | 'conclusion' | 'log';

export function CheckDetail({ view, loadRun = loadDemoRun }: {
  view: CheckView;
  loadRun?: (id: string, signal: AbortSignal) => Promise<RunDetails | null>;
}) {
  const { id = '' } = useParams();
  const { state, retry } = useCheckData(id, loadRun);

  return (
    <>
      <Link to="/checks">← Все проверки</Link>
      {state.phase === 'loading' && <p role="status">Загрузка проверки…</p>}
      {state.phase === 'failed' && <section className="checks-card">
        <p role="alert">Не удалось загрузить проверку.</p>
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
  const scope = result?.scope;
  const isPending = status === 'queued' || status === 'processing';

  return (
    <>
      <h1>{run.title}</h1>
      {scope && <p>Договор {scope.contract_number} · {scope.period_start} — {scope.period_end}</p>}
      <p role="status">Состояние проверки · {runStatusLabels[status]}</p>
      {isPending && run.progress && (
        <p>Обработано документов: {run.progress.processed} из {run.progress.total}</p>
      )}
      {status === 'failed' && <p role="alert">{run.error ?? 'Не удалось выполнить проверку.'}</p>}
      {result && <ResultContent id={id} view={view} result={result} />}
      {!result && !isPending && status !== 'failed' && (
        <section className="checks-card"><p>Результат проверки недоступен.</p></section>
      )}
    </>
  );
}

function ResultContent({ id, view, result }: { id: string; view: CheckView; result: ReviewResult }) {
  const { summary, documents } = result;
  const runPath = '/checks/' + encodeURIComponent(id);

  return (
    <>
      <nav className="checks-tabs" aria-label="Разделы проверки">
        {tabs.map(([suffix, label]) => <NavLink key={suffix} to={runPath + suffix} end>{label}</NavLink>)}
      </nav>
      {view === 'table' && <>
        {result.rows.length > 0
          ? <Reconciliation result={result} />
          : <section className="checks-card"><h2>Показатели</h2><p>Показатели отсутствуют.</p></section>}
        {summary.counts.discrepancy > 0 && <section className="checks-card">
          <h2>Возможные причины расхождений</h2>
          <p>Правила сверки могут предложить объяснение для проверки бухгалтером. В этом примере таких гипотез нет.</p>
        </section>}
      </>}
      {view === 'documents' && <Documents documents={documents} />}
      {view === 'exceptions' && (
        <Documents title="Исключения" documents={documents.filter((doc) => doc.decision.state !== 'include')}
          empty="Исключений нет." notice="Действия бухгалтера недоступны в синтетическом режиме." />
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
      {view === 'log' && <CheckLog />}
    </>
  );
}

function Reconciliation({ result }: { result: ReviewResult }) {
  const { rows, evidence, documents, summary } = result;
  const [selectedId, setSelectedId] = useState(rows[0]?.id);
  const [evidenceId, setEvidenceId] = useState<string>();
  const row = rows.find(({ id }) => id === selectedId);
  const refs = new Set([
    ...row?.reported_evidence_refs ?? [],
    ...row?.calculation?.components.flatMap((component) => component.amount_refs) ?? [],
    ...row?.reasons.flatMap((reason) => reason.evidence_refs) ?? [],
    ...row?.completeness.evidence_refs ?? [],
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
              <tr key={item.id} data-selected={item.id === selectedId}>
                <td><button type="button" aria-pressed={item.id === selectedId} onClick={() => {
                  setSelectedId(item.id);
                  setEvidenceId(undefined);
                }}>{item.label}</button></td>
                <td>{formatDecimal(item.reported_value)}</td>
                <td>{formatDecimal(item.expected_value)}</td>
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
        {row?.calculation && <p>{row.calculation.formula}</p>}
        {row?.reasons.map((reason) => <p key={reason.code}>{reason.message}</p>)}
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
            <dt>Адрес</dt><dd>{formatLocation(source.locator)}</dd>
            {'bbox' in source.locator && source.locator.bbox && <>
              <dt>Координаты фрагмента</dt><dd>{source.locator.bbox.join(', ')}</dd>
            </>}
            <dt>Значение источника</dt><dd>{source.raw_value}</dd>
          </dl>
        ) : <p>Адрес источника недоступен.</p>}
        <p className="checks-caption">В примере доступны адреса. Просмотр оригиналов подключается отдельно.</p>
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

export function CheckLog() {
  return <section className="checks-card"><h2>Журнал действий</h2><p>Записи журнала недоступны в синтетическом режиме.</p></section>;
}

export function CheckNotFound() {
  return <section className="checks-card"><h1>Проверка не найдена</h1></section>;
}
