import { useEffect, useRef, useState } from 'react';
import type { MouseEvent, ReactNode } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router';
import { FileTypeIcon } from './FileTypeIcon';
import { SourceWorkspace, useSourceWorkspace } from './SourceWorkspace';
import { XlsxDownload } from './XlsxDownload';
import { WorkspaceIcon } from './WorkspaceIcon';
import type { DocumentParseStatus, ReviewResult } from './reviewResult';
import './result-documents.css';

type Document = ReviewResult['documents'][number];

export const documentDecisionLabels: Record<string, string> = {
  include: 'Включён', exclude: 'Исключён', needs_review: 'Требует проверки', parse_error: 'Ошибка чтения',
};

const exceptionFilters = [
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
  exportRunId?: string;
  exceptions: boolean;
  renderHeader: (filters: ReactNode) => ReactNode;
  archiveAction?: ReactNode;
  synthetic: boolean;
  rowEvidenceIds: (row: ReviewResult['rows'][number], issue: ReviewResult['summary']['primary_issues'][number] | undefined) => string[];
}

export function ResultDocuments({
  result, runPath, storedRunId, exportRunId, exceptions, synthetic, renderHeader, archiveAction, rowEvidenceIds,
}: ResultDocumentsProps) {
  const [readingFilter, setReadingFilter] = useState('all');
  const [exceptionFilter, setExceptionFilter] = useState('all');
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const exceptionSection = useRef<HTMLElement>(null);
  const jumpToExceptions = exceptions || location.hash === '#exceptions';

  function updateSourceQuery(next: URLSearchParams) {
    void navigate({ pathname: location.pathname, search: next.toString(), hash: location.hash }, {
      replace: true, preventScrollReset: true,
    });
  }

  const source = useSourceWorkspace({
    result, storedRunId,
    initialDocumentId: params.get('document') ?? undefined,
    initialEvidenceId: params.get('evidence') ?? undefined,
    initialScopeOnly: params.get('anchor') === 'report-row',
    onSelectionChange(documentId, evidenceId, scopeOnly) {
      const next = new URLSearchParams(params);
      next.set('document', documentId);
      if (evidenceId) next.set('evidence', evidenceId);
      else next.delete('evidence');
      if (scopeOnly) next.set('anchor', 'report-row');
      else next.delete('anchor');
      updateSourceQuery(next);
    },
    onClose() {
      const next = new URLSearchParams(params);
      next.delete('document');
      next.delete('evidence');
      next.delete('anchor');
      updateSourceQuery(next);
    },
  });

  useEffect(() => {
    if (jumpToExceptions) exceptionSection.current?.scrollIntoView({ block: 'start' });
  }, [jumpToExceptions]);

  function focusExceptions(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    const section = exceptionSection.current;
    section?.focus({ preventScroll: true });
    section?.scrollIntoView({ block: 'start' });
  }

  const documents = result.documents;
  const exceptionsList = documents.filter(({ decision }) => decision.state !== 'include');
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
    {renderHeader(<DocumentFilters label="Статус файла" options={readingFilters}
      documents={documents} filter={readingFilter} setFilter={setReadingFilter} matches={matchesReadingFilter} />)}
    <SourceWorkspace workspace={source} />
    <section className="result-documents" aria-label="Документы">
      {exceptionsList.length > 0 && <Link className="result-document-anchor"
        to={{ pathname: location.pathname, search: location.search, hash: '#exceptions' }}
        preventScrollReset onClick={focusExceptions}>К исключениям</Link>}
      <DocumentTable documents={documents.filter((document) => matchesReadingFilter(document, readingFilter))}
        filtered={readingFilter !== 'all'} result={result} runPath={runPath} evidenceByDocument={evidenceByDocument}
        rowsByDocument={rowsByDocument} source={source} />
    </section>
    <section id="exceptions" ref={exceptionSection} className="result-documents result-exceptions"
      tabIndex={-1} aria-labelledby="result-exceptions-heading">
      <div className="result-exceptions-heading">
        <h2 id="result-exceptions-heading">Исключения</h2>
        {exceptionsList.length > 0 && <DocumentFilters label="Статус исключения" options={exceptionFilters}
          documents={exceptionsList} filter={exceptionFilter} setFilter={setExceptionFilter} matches={matchesExceptionFilter} />}
      </div>
      {synthetic && exceptionsList.length > 0 && <p className="checks-caption">
        Действия бухгалтера недоступны в синтетическом режиме.
      </p>}
      <DocumentTable documents={exceptionsList.filter((document) => matchesExceptionFilter(document, exceptionFilter))}
        filtered={exceptionFilter !== 'all'} result={result} runPath={runPath} evidenceByDocument={evidenceByDocument}
        rowsByDocument={rowsByDocument} source={source} exceptions />
    </section>
    {(exportRunId || archiveAction) && <div className="result-document-actions">
      {exportRunId && <XlsxDownload key={exportRunId} runId={exportRunId} />}
      {archiveAction}
    </div>}
  </>;
}

function matchesReadingFilter(document: Document, filter: string) {
  if (filter === 'all') return true;
  if (filter === 'read') return document.parse_status === 'parsed';
  return document.parse_status === 'partial' || document.parse_status === 'error';
}

function matchesExceptionFilter(document: Document, filter: string) {
  return filter === 'all' || document.decision.state === filter;
}

function DocumentFilters({ label, options, documents, filter, setFilter, matches }: {
  label: string;
  options: readonly (readonly [string, string])[];
  documents: Document[];
  filter: string;
  setFilter: (value: string) => void;
  matches: (document: Document, value: string) => boolean;
}) {
  return <div className="result-document-filters" role="group" aria-label={label}>
    {([['all', 'Все'], ...options] as const).map(([value, text]) => (
      <button type="button" key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>
        {text} ({documents.filter((document) => matches(document, value)).length})
      </button>
    ))}
  </div>;
}

function DocumentTable({ documents, filtered, result, runPath, evidenceByDocument, rowsByDocument, source, exceptions = false }: {
  documents: Document[];
  filtered: boolean;
  result: ReviewResult;
  runPath: string;
  evidenceByDocument: Map<string, ReviewResult['evidence']>;
  rowsByDocument: Map<string, ReviewResult['rows']>;
  source: ReturnType<typeof useSourceWorkspace>;
  exceptions?: boolean;
}) {
  return <div className="result-document-scroll" role="region" aria-label={exceptions ? 'Таблица исключений' : 'Таблица документов'} tabIndex={0}>
    <table className="result-document-table">
      <thead><tr>
        {exceptions
          ? ['Файл', 'Роль', 'Решение', 'Основание', 'Показатели КФЗ'].map((label) => <th key={label} scope="col">{label}</th>)
          : ['Файл', 'Тип', 'Номер', 'Дата', 'Договор', 'Стр.', 'Статус', 'Строки КФЗ'].map((label) => <th key={label} scope="col">{label}</th>)}
      </tr></thead>
      <tbody>{documents.map((document) => {
        const related = rowsByDocument.get(document.id) ?? [];
        const metadata = evidenceByDocument.get(document.id) ?? [];
        const report = document.role === 'report';
        const contract = report ? result.scope.contract_number : oneText(metadata, 'contract');
        const messages = new Set([document.decision.message, ...document.errors.map(({ message }) => message)]);
        const useDecision = exceptions || document.decision.state !== 'include' || document.parse_status !== 'parsed';
        return <tr key={document.id} data-selected={source.open && source.documentId === document.id}
          onClick={(event) => {
            if (event.target instanceof Element && !event.target.closest('button, a, details')) {
              source.openDocument(document.id, event.currentTarget.querySelector('button') ?? event.currentTarget);
            }
          }}>
          <td><div className="result-document-file">
            <FileTypeIcon extension={document.format ?? ''} />
            <button type="button" onClick={(event) => source.openDocument(document.id, event.currentTarget)}>{document.name}</button>
          </div></td>
          <td>{report ? 'КФЗ' : 'Первичный документ'}</td>
          {!exceptions && <>
            <td>{report ? result.reportNumber ?? '—' : '—'}</td>
            <td>—</td>
            <td>{contract ?? '—'}</td>
            <td>{document.format === 'png' && document.parse_status === 'parsed' ? '1' : '—'}</td>
          </>}
          <td>
            {!exceptions && <span className="document-reading-status" data-reading={document.parse_status}>
              {document.parse_status === 'parsed' && <span className="document-read-icon"><WorkspaceIcon name="check" size={12} /></span>}
              {document.parse_status === undefined ? 'Чтение не указано' : readingLabels[document.parse_status]}
            </span>}
            {useDecision && <span className="result-document-state" data-state={document.decision.state}>
              {documentDecisionLabels[document.decision.state]}
            </span>}
            {!exceptions && useDecision && <details className="document-decision-details">
              <summary>Основание</summary>
              <ul className="result-document-messages">
                {[...messages].map((message) => <li key={message}>{message}</li>)}
              </ul>
            </details>}
          </td>
          {exceptions && <td><ul className="result-document-messages">
            {[...messages].map((message) => <li key={message}>{message}</li>)}
          </ul></td>}
          <td>{related.length ? <ul className="result-document-messages">
            {related.map(({ id, label }) => <li key={id}>
              <Link to={{ pathname: runPath, search: '?' + new URLSearchParams({ indicator: id }) }}>{label}</Link>
            </li>)}
          </ul> : '—'}</td>
        </tr>;
      })}
      {documents.length === 0 && <tr><td colSpan={exceptions ? 5 : 8}>
        <p role="status">{filtered ? 'Документов с этим статусом нет.'
          : exceptions ? 'Исключений нет.' : 'Документы отсутствуют.'}</p>
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
