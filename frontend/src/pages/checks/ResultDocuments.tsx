import { useState } from 'react';
import { Link } from 'react-router';
import { DocumentSourcePreview } from './DocumentSourcePreview';
import { FileTypeIcon } from './FileTypeIcon';
import { SourceDrawer } from './SourceDrawer';
import type { DocumentParseStatus, ReviewResult } from './reviewResult';
import './result-documents.css';

type Document = ReviewResult['documents'][number];
type Evidence = ReviewResult['evidence'][number];

export const documentDecisionLabels: Record<string, string> = {
  include: 'Включён', exclude: 'Исключён', needs_review: 'Требует проверки', parse_error: 'Ошибка чтения',
};

const decisions = [
  ['include', documentDecisionLabels.include],
  ['exclude', documentDecisionLabels.exclude],
  ['needs_review', documentDecisionLabels.needs_review],
  ['parse_error', documentDecisionLabels.parse_error],
] as const;

const readingFilters = [['read', 'Прочитано'], ['error', 'Ошибочные']] as const;
const readingLabels: Record<DocumentParseStatus, string> = {
  pending: 'Ожидает чтения',
  parsed: 'Прочитано',
  partial: 'Прочитано частично',
  error: 'Не удалось прочитать',
};

interface ResultDocumentsProps {
  result: ReviewResult;
  runPath: string;
  storedRunId?: string;
  exceptions: boolean;
  synthetic: boolean;
  rowEvidenceIds: (row: ReviewResult['rows'][number], issue: ReviewResult['summary']['primary_issues'][number] | undefined) => string[];
  formatAddress: (locator: Evidence['locator']) => string;
}

export function ResultDocuments({
  result, runPath, storedRunId, exceptions, synthetic, rowEvidenceIds, formatAddress,
}: ResultDocumentsProps) {
  const [filter, setFilter] = useState('all');
  const [openId, setOpenId] = useState<string>();
  const documents = exceptions
    ? result.documents.filter(({ decision }) => decision.state !== 'include')
    : result.documents;
  const filters = exceptions ? decisions.filter(([value]) => value !== 'include') : readingFilters;
  function matchesFilter(document: Document, value: string) {
    if (value === 'all') return true;
    if (exceptions) return document.decision.state === value;
    return value === 'read' ? document.parse_status === 'parsed'
      : document.parse_status === 'partial' || document.parse_status === 'error';
  }
  const visible = documents.filter((document) => matchesFilter(document, filter));
  const evidenceByDocument = new Map<string, Evidence[]>();
  const documentByEvidence = new Map<string, string>();
  for (const item of result.evidence) {
    const existing = evidenceByDocument.get(item.document_id);
    if (existing) existing.push(item);
    else evidenceByDocument.set(item.document_id, [item]);
    documentByEvidence.set(item.id, item.document_id);
  }
  const documentsByError = new Map<string, string[]>();
  for (const document of documents) {
    for (const { id } of document.errors) {
      const affected = documentsByError.get(id);
      if (affected) affected.push(document.id);
      else documentsByError.set(id, [document.id]);
    }
  }
  const issues = new Map(result.summary.primary_issues.map((issue) => [issue.id, issue]));
  const rowsByDocument = new Map<string, ReviewResult['rows']>();
  for (const row of result.rows) {
    const issue = row.root_issue_id === null ? undefined : issues.get(row.root_issue_id);
    const linked = new Set(rowEvidenceIds(row, issue).map((id) => documentByEvidence.get(id)));
    for (const id of issue?.file_error_refs ?? []) {
      for (const documentId of documentsByError.get(id) ?? []) linked.add(documentId);
    }
    for (const id of linked) {
      if (id === undefined) continue;
      const associated = rowsByDocument.get(id);
      if (associated) associated.push(row);
      else rowsByDocument.set(id, [row]);
    }
  }
  const openDocument = documents.find(({ id }) => id === openId);

  return <section className="result-documents" aria-label={exceptions ? 'Исключения' : 'Документы'}>
    <header className="result-documents-heading">
      <h2>{exceptions ? 'Исключения' : 'Документы'}</h2>
      <Link to={runPath + (exceptions ? '/documents' : '/exceptions')}>
        {exceptions ? 'К документам' : 'К исключениям'}
      </Link>
    </header>
    {exceptions && synthetic && <p role="status" className="checks-caption">
      Действия бухгалтера недоступны в синтетическом режиме.
    </p>}
    <div className="result-document-filters" role="group" aria-label="Состояние файла">
      {([['all', 'Все'], ...filters] as const).map(([value, label]) => (
        <button type="button" key={value} aria-pressed={filter === value}
          onClick={() => setFilter(value)}>
          {label} ({documents.filter((document) => matchesFilter(document, value)).length})
        </button>
      ))}
    </div>
    <div className="result-document-scroll" role="region" aria-label="Таблица документов" tabIndex={0}>
      <table className="result-document-table">
        <thead><tr>
          <th scope="col">Файл</th><th scope="col">Роль</th>
          {!exceptions && <th scope="col">Чтение</th>}<th scope="col">Решение</th>
          <th scope="col">Основание</th><th scope="col">Показатели КФЗ</th>
        </tr></thead>
        <tbody>{visible.map((document) => {
          const related = rowsByDocument.get(document.id) ?? [];
          const messages = new Set([
            document.decision.message, ...document.errors.map(({ message }) => message),
          ]);
          return <tr key={document.id}>
            <td><div className="result-document-file">
              <FileTypeIcon extension={document.format ?? ''} />
              <button type="button" onClick={() => setOpenId(document.id)}>{document.name}</button>
            </div></td>
            <td>{document.role === 'report' ? 'Отчёт' : 'Первичный документ'}</td>
            {!exceptions && <td>
              {document.parse_status === undefined ? 'Чтение не указано' : readingLabels[document.parse_status]}
            </td>}
            <td><span className="result-document-state" data-state={document.decision.state}>
              {documentDecisionLabels[document.decision.state]}
            </span></td>
            <td><ul className="result-document-messages">
              {[...messages].map((message) => <li key={message}>{message}</li>)}
            </ul></td>
            <td>{related.length ? <ul className="result-document-messages">
              {related.map(({ id, label }) => <li key={id}>
                <Link to={{ pathname: runPath, search: '?' + new URLSearchParams({ indicator: id }) }}>{label}</Link>
              </li>)}
            </ul> : '—'}</td>
          </tr>;
        })}
        {visible.length === 0 && <tr><td colSpan={exceptions ? 5 : 6}>
          <p role="status">{filter !== 'all' ? 'Документов в этом состоянии нет.'
            : exceptions ? 'Исключений нет.' : 'Документы отсутствуют.'}</p>
        </td></tr>}
        </tbody>
      </table>
    </div>
    {openDocument && <SourceDrawer onClose={() => setOpenId(undefined)}>
      <DocumentDetails
        key={openDocument.id} document={openDocument} storedRunId={storedRunId}
        evidence={evidenceByDocument.get(openDocument.id) ?? []} formatAddress={formatAddress}
      />
    </SourceDrawer>}
  </section>;
}

function DocumentDetails({ document, storedRunId, evidence, formatAddress }: {
  document: Document;
  storedRunId?: string;
  evidence: Evidence[];
  formatAddress: ResultDocumentsProps['formatAddress'];
}) {
  const [selected, setSelected] = useState(evidence[0]?.id ?? '');
  const source = evidence.find(({ id }) => id === selected);
  return <div className="result-document-details">
    <h3>{document.name}</h3>
    {evidence.length > 0 && <label className="result-document-picker">
      Адрес доказательства
      <select value={selected} onChange={(event) => setSelected(event.target.value)}>
        {evidence.map((item) => <option key={item.id} value={item.id}>{formatAddress(item.locator)}</option>)}
      </select>
    </label>}
    {storedRunId ? <DocumentSourcePreview
      runId={storedRunId} document={{ id: document.id, name: document.name, format: document.format ?? null }}
      evidenceId={source?.id ?? null}
    /> : <>
      <p>Оригинал в готовом примере недоступен.</p>
      {source ? <p>{formatAddress(source.locator)}</p> : <p>Адрес фрагмента отсутствует.</p>}
    </>}
  </div>;
}
