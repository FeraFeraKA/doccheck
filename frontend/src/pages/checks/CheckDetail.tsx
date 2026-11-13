import { useState } from 'react';
import { Link, NavLink, useParams } from 'react-router';
import { demoResult, demoRunPath, formatLocation, formatMoney, statusLabels } from './demoData';

const tabs = [
  ['', 'Сверка'], ['/documents', 'Документы'], ['/exceptions', 'Исключения'],
  ['/conclusion', 'Заключение'], ['/log', 'Журнал проверки'],
];

export function CheckDetail({ view }: { view: string }) {
  const { id } = useParams();
  const { scope, summary, documents } = demoResult;

  if (id !== demoResult.run_id) return <CheckNotFound />;

  return (
    <>
      <Link to="/checks">← Все проверки</Link>
      <h1>Синтетическая сверка</h1>
      <p>Договор {scope.contract_number} · {scope.period_start} — {scope.period_end}</p>
      <nav className="checks-tabs" aria-label="Разделы проверки">
        {tabs.map(([suffix, label]) => <NavLink key={suffix} to={demoRunPath + suffix} end>{label}</NavLink>)}
      </nav>
      {view === 'table' && <>
        <Reconciliation />
        {summary.counts.discrepancy > 0 && <section className="checks-card">
          <h2>Возможные причины расхождений</h2>
          <p>Правила сверки могут предложить объяснение для проверки бухгалтером. В этом примере таких гипотез нет.</p>
        </section>}
      </>}
      {view === 'documents' && <Documents documents={documents} />}
      {view === 'exceptions' && (
        <Documents title="Исключения" documents={documents.filter((doc) => doc.decision.state !== 'include')}
          notice="Действия бухгалтера недоступны в синтетическом режиме." />
      )}
      {view === 'conclusion' && <section className="checks-card">
        <h2>Заключение</h2><p>{summary.conclusion}</p>
        <ul>{summary.primary_issues.map((issue) => <li key={issue.id}>{issue.message}</li>)}</ul>
      </section>}
      {view === 'log' && <CheckLog />}
    </>
  );
}

function Reconciliation() {
  const { rows, evidence, documents } = demoResult;
  const [selectedId, setSelectedId] = useState(rows[0]?.id);
  const [evidenceId, setEvidenceId] = useState<string>();
  const row = rows.find(({ id }) => id === selectedId);
  const refs = new Set([
    ...row?.reported_evidence_refs ?? [],
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
        <div className="checks-table-scroll">
          <table>
            <thead><tr><th>Показатель</th><th>КФЗ</th><th>По первичным документам</th><th>Δ</th><th>Статус</th></tr></thead>
            <tbody>{rows.map((item) => (
              <tr key={item.id} data-selected={item.id === selectedId}>
                <td><button type="button" aria-pressed={item.id === selectedId} onClick={() => {
                  setSelectedId(item.id);
                  setEvidenceId(undefined);
                }}>{item.label}</button></td>
                <td>{formatMoney(item.reported_value)}</td>
                <td>{formatMoney(item.expected_value)}</td>
                <td>{formatMoney(item.delta)}</td>
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

function Documents({ documents, title = 'Документы', notice }: {
  documents: typeof demoResult.documents;
  title?: string;
  notice?: string;
}) {
  return <section className="checks-card">
    <h2>{title}</h2>
    {notice && <p role="status" className="checks-caption">{notice}</p>}
    <div className="checks-table-scroll">
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
    </div>
  </section>;
}

export function CheckLog() {
  return <section className="checks-card"><h2>Журнал действий</h2><p>Записи журнала недоступны в синтетическом режиме.</p></section>;
}

export function CheckNotFound() {
  return <section className="checks-card"><h1>Проверка не найдена</h1><Link to="/checks">К обзору проверок</Link></section>;
}
