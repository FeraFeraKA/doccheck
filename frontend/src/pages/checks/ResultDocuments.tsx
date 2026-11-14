import { useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useLocation, useNavigate, useNavigationType, useSearchParams } from 'react-router';
import { FileTypeIcon } from './FileTypeIcon';
import { SourceWorkspace, useSourceWorkspace } from './SourceWorkspace';
import { WorkspaceIcon } from './WorkspaceIcon';
import type { DocumentParseStatus, ReviewResult } from './reviewResult';
import './result-documents.css';

type Document = ReviewResult['documents'][number];

export const documentDecisionLabels: Record<string, string> = {
  include: 'Включён', exclude: 'Исключён', needs_review: 'Требует проверки', parse_error: 'Ошибка чтения',
};

const documentFilters = [
  ['all', 'Все'],
  ['read', 'Прочитано'],
  ['excluded', 'Исключены'],
] as const;

type DocumentFilter = typeof documentFilters[number][0];
const columns = ['Файл', 'Тип', 'Номер', 'Дата', 'Договор', 'Стр.', 'Статус', 'Строки КФЗ'];

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
  exportRunId?: string;
  exceptions: boolean;
  renderHeader: (filters: ReactNode) => ReactNode;
  archiveAction?: ReactNode;
  synthetic: boolean;
  rowEvidenceIds: (row: ReviewResult['rows'][number], issue: ReviewResult['summary']['primary_issues'][number] | undefined) => string[];
}

export function ResultDocuments(props: ResultDocumentsProps) {
  const [params] = useSearchParams();
  const navigationType = useNavigationType();
  const sourceQuery = JSON.stringify([params.get('document'), params.get('evidence'), params.get('anchor')]);
  const [sourceHistory, setSourceHistory] = useState({ query: sourceQuery, revision: 0 });
  if (sourceQuery !== sourceHistory.query) {
    // Browser history can restore an address from a different selection. Query writes by the
    // viewer itself keep its state and the button that currently owns return focus.
    const revision = sourceHistory.revision + (navigationType === 'POP' ? 1 : 0);
    setSourceHistory({ query: sourceQuery, revision });
  }
  return <DocumentLibrary {...props} params={params} key={sourceHistory.revision} />;
}

function DocumentLibrary({ result, runPath, storedRunId, exceptions, renderHeader, rowEvidenceIds, params }:
  ResultDocumentsProps & { params: URLSearchParams }) {
  const location = useLocation();
  const navigate = useNavigate();
  const queryRef = useRef(params);
  useLayoutEffect(() => { queryRef.current = params; }, [params]);
  const defaultFilter = exceptions || location.hash === '#exceptions' ? 'excluded' : 'all';
  const requestedFilter = params.get('filter');
  const filter = documentFilters.find(([value]) => value === requestedFilter)?.[0] ?? defaultFilter;

  function updateQuery(next: URLSearchParams, replace: boolean) {
    const search = next.toString();
    if (search === queryRef.current.toString()) return;
    queryRef.current = next;
    void navigate({ search, hash: location.hash }, { replace, preventScrollReset: true });
  }

  function setFilter(value: DocumentFilter) {
    if (filter === value) return;
    const next = new URLSearchParams(queryRef.current);
    if (value === defaultFilter) next.delete('filter');
    else next.set('filter', value);
    updateQuery(next, false);
  }

  const source = useSourceWorkspace({
    result, storedRunId,
    initialDocumentId: params.get('document') ?? undefined,
    initialEvidenceId: params.get('evidence') ?? undefined,
    initialScopeOnly: params.get('anchor') === 'report-row',
    onSelectionChange(documentId, evidenceId) {
      const next = new URLSearchParams(queryRef.current);
      next.set('document', documentId);
      if (evidenceId) next.set('evidence', evidenceId);
      else next.delete('evidence');
      next.delete('anchor');
      updateQuery(next, true);
    },
    onClose() {
      const next = new URLSearchParams(queryRef.current);
      next.delete('document');
      next.delete('evidence');
      next.delete('anchor');
      updateQuery(next, true);
    },
  });

  const documents = result.documents;
  const byFilter = {
    all: documents,
    read: documents.filter((document) => document.parse_status === 'parsed' && !isExceptionDocument(document)),
    excluded: documents.filter(isExceptionDocument),
  };
  const evidenceByDocument = new Map<string, ReviewResult['evidence']>();
  for (const source of result.evidence) {
    const group = evidenceByDocument.get(source.document_id);
    if (group) group.push(source);
    else evidenceByDocument.set(source.document_id, [source]);
  }
  const documentByEvidence = new Map(result.evidence.map(({ id, document_id }) => [id, document_id]));
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

  return <>
    {renderHeader(<div className="result-document-filters" role="group" aria-label="Статус файла">
      {documentFilters.map(([value, text]) => (
        <button type="button" key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>
          {text} ({byFilter[value].length})
        </button>
      ))}
    </div>)}
    <SourceWorkspace workspace={source} />
    <section className="result-documents" aria-label="Документы">
      <DocumentTable documents={byFilter[filter]} filtered={filter !== 'all'}
        result={result} runPath={runPath} evidenceByDocument={evidenceByDocument}
        rowsByDocument={rowsByDocument} source={source} />
    </section>
  </>;
}

export function isExceptionDocument({ decision, parse_status, errors }: Document) {
  return decision.state !== 'include' || parse_status === 'partial' || parse_status === 'error' || errors.length > 0;
}

function DocumentTable({ documents, filtered, result, runPath, evidenceByDocument, rowsByDocument, source }: {
  documents: Document[];
  filtered: boolean;
  result: ReviewResult;
  runPath: string;
  evidenceByDocument: Map<string, ReviewResult['evidence']>;
  rowsByDocument: Map<string, ReviewResult['rows']>;
  source: ReturnType<typeof useSourceWorkspace>;
}) {
  return <div className="result-document-scroll" role="region" aria-label="Таблица документов" tabIndex={0}>
    <table className="result-document-table">
      <thead><tr>
        {columns.map((label) => <th key={label} scope="col">{label}</th>)}
      </tr></thead>
      <tbody>{documents.map((document) => {
        const related = rowsByDocument.get(document.id) ?? [];
        const metadata = evidenceByDocument.get(document.id) ?? [];
        const report = document.role === 'report';
        const contract = report ? result.scope.contract_number : oneText(metadata, 'contract');
        const { decision, parse_status: parseStatus, errors } = document;
        const exception = isExceptionDocument(document);
        const messages = new Set(errors.map(({ message }) => message));
        if (decision.state !== 'include') messages.add(decision.message);
        const readingStatus = parseStatus === undefined ? 'Чтение не указано' : readingLabels[parseStatus];
        return <tr key={document.id} data-selected={source.open && source.documentId === document.id}
          onClick={(event) => {
            if (event.target instanceof Element && !event.target.closest('button, a')) {
              source.openDocument(document.id, event.currentTarget.querySelector('button') ?? event.currentTarget);
            }
          }}>
          <td><div className="result-document-file">
            <FileTypeIcon extension={document.format ?? ''} />
            <button type="button" onClick={(event) => source.openDocument(document.id, event.currentTarget)}>{document.name}</button>
          </div></td>
          <td>{report ? 'КФЗ' : 'Первичный документ'}</td>
          <td>{report ? result.reportNumber ?? '—' : '—'}</td>
          <td>—</td>
          <td>{contract ?? '—'}</td>
          <td>{document.format === 'png' && parseStatus === 'parsed' ? '1' : '—'}</td>
          <td className="document-status-cell">
            {decision.state !== 'include' ? <>
              <span className="result-document-state" data-state={decision.state}>{documentDecisionLabels[decision.state]}</span>
              {parseStatus === 'error' && decision.state !== 'parse_error' && <span className="document-status-message">{readingStatus}</span>}
            </> : <span className="document-reading-status">
              {!exception && parseStatus === 'parsed' &&
                <span className="document-read-icon"><WorkspaceIcon name="check" size={12} /></span>}
              {exception && (parseStatus === undefined || parseStatus === 'parsed')
                ? documentDecisionLabels.needs_review : readingStatus}
            </span>}
            {messages.size > 0 && <ul className="result-document-messages document-status-message">
              {[...messages].map((message) => <li key={message}>{message}</li>)}
            </ul>}
          </td>
          <td>{related.length ? <ul className="result-document-messages">
            {related.map(({ id, label }) => <li key={id}>
              <Link to={{ pathname: runPath, search: '?' + new URLSearchParams({ indicator: id }) }}>{label}</Link>
            </li>)}
          </ul> : '—'}</td>
        </tr>;
      })}
      {documents.length === 0 && <tr><td colSpan={columns.length}>
        <p role="status">{filtered ? 'Документов с этим статусом нет.' : 'Документы отсутствуют.'}</p>
      </td></tr>}
      </tbody>
    </table>
  </div>;
}

function oneText(evidence: ReviewResult['evidence'], kind: string) {
  const values = new Set(evidence.filter((item) => item.kind === kind).map(({ normalized_value }) => normalized_value));
  const value = values.values().next().value;
  return values.size === 1 && typeof value === 'string' ? value : undefined;
}
