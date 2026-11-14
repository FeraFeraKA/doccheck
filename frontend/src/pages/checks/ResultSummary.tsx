import { Link } from 'react-router';
import type { ReviewResult } from './reviewResult';
import { formatDecimal, formatLocation, formatMeasure, rowExplanation } from './reviewResult';
import { documentDecisionLabels } from './ResultDocuments';
import { XlsxDownload } from './XlsxDownload';

const indicatorList = new Intl.ListFormat('ru');
const plural = new Intl.PluralRules('ru');

const statuses = [
  ['verified', 'Подтверждено'],
  ['discrepancy', 'Расхождения'],
  ['unverified', 'Не проверено'],
] as const;

export const resultHeadline = {
  verified: 'Достоверен',
  discrepancy: 'Недостоверен',
  unverified: 'Подтвердить полностью нельзя',
  empty: 'Нет показателей',
};

export function resultTone({ verified, discrepancy, unverified }: ReviewResult['summary']['counts']) {
  if (discrepancy > 0) return 'discrepancy';
  if (unverified > 0) return 'unverified';
  return verified === 0 ? 'empty' : 'verified';
}

export function UnverifiedIndicators({ rows, onOpenRow }: {
  rows: ReviewResult['rows'];
  onOpenRow: (id: string) => void;
}) {
  const unverified = rows.filter((row) => row.status === 'unverified');
  if (unverified.length === 0) return null;

  return <section className="result-summary-card mt-5 rounded-lg border p-4" aria-labelledby="unverified-indicators-title">
    <h3 id="unverified-indicators-title" className="mb-2 text-[15px] font-medium">Недостаточно подтверждений</h3>
    <ul className="space-y-2 text-[13px]">
      {unverified.map((row) => <li key={row.id}>
        <button type="button" className="text-left font-medium underline" onClick={() => onOpenRow(row.id)}>{row.label}</button>
        <p className="result-summary-muted">{rowExplanation(row)}</p>
        {row.expected_value !== null &&
          <p className="result-summary-muted">Сумма по документам: {formatDecimal(row.expected_value)} {row.unit}</p>}
        {row.expected_value === null && row.observed_evidence_sum !== null &&
          <p className="result-summary-muted">Частичная сумма: {formatDecimal(row.observed_evidence_sum)} {row.unit}</p>}
      </li>)}
    </ul>
  </section>;
}

export function AdditionalChecks({ result, runPath, onOpenRow, onOpenDocument, onOpenEvidence }: {
  result: ReviewResult;
  runPath: string;
  onOpenRow: (id: string) => void;
  onOpenDocument?: (id: string, trigger: HTMLElement) => void;
  onOpenEvidence?: (id: string, trigger: HTMLElement) => void;
}) {
  const files = result.documents.filter(({ decision, errors }) => decision.state !== 'include' || errors.length > 0);
  const rowIssueIds = new Set(result.rows.map(({ root_issue_id }) => root_issue_id));
  const issues = result.summary.primary_issues.filter(({ id }) => !rowIssueIds.has(id));
  const evidenceById = new Map(result.evidence.map((item) => [item.id, item]));
  const documentsById = new Map(result.documents.map((item) => [item.id, item.name]));
  function sourceLinks(refs: string[]) {
    return refs.map((id) => {
      const source = evidenceById.get(id);
      if (!source) return null;
      const search = new URLSearchParams({ document: source.document_id, evidence: id });
      const text = `${documentsById.get(source.document_id)} · ${formatLocation(source.locator)}`;
      return onOpenEvidence ? <button key={id} type="button" className="block text-left underline"
        onClick={(event) => onOpenEvidence(id, event.currentTarget)}>{text}</button>
        : <Link key={id} className="block underline" to={runPath + '/documents?' + search}>
        {text}
      </Link>;
    });
  }

  return <section className="mt-6 space-y-2" aria-label="Дополнительные проверки">
    <h2 className="text-[17px] font-medium">Дополнительные проверки</h2>
    {files.length > 0 && <div className="result-document-scroll" role="region" aria-label="Решения по документам" tabIndex={0}>
      <table className="result-document-table">
        <thead><tr><th scope="col">Проверка</th><th scope="col">Документ</th>
          <th scope="col">Решение</th><th scope="col">Причина</th></tr></thead>
        <tbody>{files.map((file) => <tr key={file.id}>
          <td>{decisionTypes[file.decision.reason_code] ?? 'Проверка документа'}</td>
          <td>{onOpenDocument ? <button type="button" className="text-left underline"
            onClick={(event) => onOpenDocument(file.id, event.currentTarget)}>{file.name}</button>
            : <Link className="underline" to={runPath + '/documents?' + new URLSearchParams({ document: file.id })}>{file.name}</Link>}</td>
          <td>{documentDecisionLabels[file.decision.state]}</td><td>{file.decision.message}
            {file.errors.filter(({ message }) => message !== file.decision.message)
              .map((error) => <p key={error.id}>{error.message}</p>)}
            {sourceLinks(file.decision.evidence_refs)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    {issues.length > 0 && <ul className="list-disc pl-5 text-sm">{issues.map((issue) => <li key={issue.id}>{issue.message}{sourceLinks(issue.evidence_refs)}</li>)}</ul>}
    <UnverifiedIndicators rows={result.rows} onOpenRow={onOpenRow} />
    {files.length > 0 && <Link to={runPath + '/exceptions'} className="inline-block text-[13px] underline">Исключения</Link>}
    {files.length === 0 && issues.length === 0 && result.summary.counts.unverified === 0
      && <p className="result-summary-muted text-sm">Дополнительные замечания отсутствуют.</p>}
  </section>;
}

const decisionTypes: Record<string, string> = {
  byte_duplicate: 'Дублирование',
  out_of_period: 'Документ вне периода',
  other_contract: 'Документ другого договора',
  ambiguous_relation: 'Неоднозначная связь',
  ambiguous_link: 'Неоднозначная связь',
};

export function ResultConclusion({ result, exportRunId }: { result: ReviewResult; exportRunId?: string }) {
  const { counts, conclusion, rubCoverage } = result.summary;
  const tone = resultTone(counts);
  const discrepancies = result.rows.filter((row) => row.status === 'discrepancy');
  const unverified = result.rows.filter((row) => row.status === 'unverified');
  const discrepancyForm = plural.select(discrepancies.length);
  const unverifiedForm = plural.select(unverified.length);
  const summaryCoverage = rubCoverage?.total;
  return <section aria-label="Заключение по проверке" className="result-summary mt-4">
    <p className="result-summary-muted mb-1 text-[13px]">Вывод по проверке</p>
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
      <h2 className="result-summary-title" data-tone={tone}>{resultHeadline[tone]}</h2>
      <ul aria-label="Счётчики показателей" className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] tabular-nums">
        {statuses.map(([status, label]) => <li key={status} className="flex items-center gap-1.5">
          <span aria-hidden="true" className="result-summary-marker" data-tone={status} />
          <span>{label} — <strong className="font-semibold">{counts[status]}</strong></span>
        </li>)}
      </ul>
    </div>
    <div className="mt-2 max-w-[930px] space-y-1 text-sm leading-relaxed tabular-nums">
      <p>{conclusion}</p>
      {discrepancies.length > 0 && <>
        <p>{discrepancyForm === 'one' ? 'Обнаружено' : 'Обнаружены'} {discrepancies.length}
          {' '}{discrepancyForm === 'one' ? 'расхождение' : discrepancyForm === 'few' ? 'расхождения' : 'расхождений'}.</p>
        <ul className="list-disc space-y-1 pl-5">
        {discrepancies.map((row) => <li key={row.id}>{row.label}: в КФЗ {formatMeasure(row.reported_value, row.unit)},
          по документам {formatMeasure(row.expected_value, row.unit)}. Разница {row.delta !== null && !row.delta.startsWith('-') ? '+' : ''}{formatMeasure(row.delta, row.unit)}.</li>)}
        </ul>
      </>}
      {unverified.length > 0 && <p>Не удалось проверить {unverified.length}
        {' '}{unverifiedForm === 'one' ? 'показатель' : unverifiedForm === 'few' ? 'показателя' : 'показателей'}:
        {' '}{indicatorList.format(unverified.map(({ label }) => label))}.</p>}
      {summaryCoverage && <p>Известные денежные статьи КФЗ: <strong className="font-medium">{formatMeasure(summaryCoverage, 'RUB')}</strong>.</p>}
      {unverified.filter((row) => row.observed_evidence_sum !== null).map((row) => <p key={row.id}>
        {row.label}: подтверждена часть суммы {formatMeasure(row.observed_evidence_sum, row.unit)}.
      </p>)}
      {rubCoverage && <details className="text-[13px]">
        <summary className="cursor-pointer">Покрытие по сумме</summary>
        <ul className="mt-1 flex flex-wrap gap-x-5 gap-y-1">
          {statuses.map(([status, label]) => <li key={status}>
            {label}: {formatMeasure(rubCoverage[status], 'RUB')}
            {rubCoverage.shares?.[status] !== undefined && ` · ${formatDecimal(rubCoverage.shares[status])}%`}
          </li>)}
        </ul>
      </details>}
    </div>
    {exportRunId && <div className="mt-3"><XlsxDownload key={exportRunId} runId={exportRunId} /></div>}
  </section>;
}
