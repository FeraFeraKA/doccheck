import { Link } from 'react-router';
import type { ReviewResult } from './reviewResult';
import { formatDecimal, rowExplanation } from './reviewResult';
import { documentDecisionLabels } from './ResultDocuments';
import { XlsxDownload } from './XlsxDownload';

const statuses = [
  ['verified', 'Подтверждено'],
  ['discrepancy', 'Расхождения'],
  ['unverified', 'Не проверено'],
] as const;

export const resultHeadline = {
  verified: 'Показатели подтверждены',
  discrepancy: 'Есть расхождения',
  unverified: 'Есть непроверенные показатели',
  empty: 'Нет показателей',
};

export function resultTone({ verified, discrepancy, unverified }: ReviewResult['summary']['counts']) {
  if (discrepancy > 0) return 'discrepancy';
  if (unverified > 0) return 'unverified';
  return verified === 0 ? 'empty' : 'verified';
}

export function ResultSummary({ result }: { result: ReviewResult }) {
  const { counts, rubCoverage } = result.summary;
  return <section className="result-summary-card mt-6 rounded-lg border p-4" aria-label="Результаты проверки">
    <h2 className="text-[15px] font-medium">Результаты проверки</h2>
    {rubCoverage ? <p className="my-2 text-sm">
      Сумма известных денежных показателей КФЗ: <strong>{formatDecimal(rubCoverage.total)} ₽</strong>
    </p> : <p className="my-2 text-sm result-summary-muted">Сводка по сумме недоступна.</p>}
    {rubCoverage?.shares && <div aria-hidden="true" className="result-summary-coverage mb-3 flex h-2 overflow-hidden rounded-full">
      {statuses.map(([status]) => <div key={status} data-tone={status}
        style={{ width: `${rubCoverage.shares?.[status] ?? '0'}%` }} />)}
    </div>}
    <dl className="grid gap-2 text-[13px] sm:grid-cols-3">
      {statuses.map(([status, label]) => {
        const amount = rubCoverage?.[status];
        const share = rubCoverage?.shares?.[status];
        return <div key={status}>
          <dt className="result-summary-count font-medium" data-tone={status}>{label}</dt>
          <dd>{counts[status]} стр.{amount != null && ` · ${formatDecimal(amount)} ₽`}
            {share !== undefined && ` · ${formatDecimal(share)}%`}</dd>
        </div>;
      })}
    </dl>
    {rubCoverage && <p className="result-summary-muted mt-3 text-xs">В распределении показаны суммы строк КФЗ.</p>}
  </section>;
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

export function AdditionalChecks({ result, runPath, onOpenRow }: {
  result: ReviewResult;
  runPath: string;
  onOpenRow: (id: string) => void;
}) {
  const files = result.documents.filter(({ decision, errors }) => decision.state !== 'include' || errors.length > 0);
  const rowIssueIds = new Set(result.rows.map(({ root_issue_id }) => root_issue_id));
  const fileErrorIds = new Set(files.flatMap(({ errors }) => errors.map(({ id }) => id)));
  const issues = result.summary.primary_issues.filter((issue) =>
    !rowIssueIds.has(issue.id) && !issue.file_error_refs?.some((id) => fileErrorIds.has(id)));
  return <section className="mt-6 space-y-2" aria-label="Дополнительные проверки">
    <h2 className="text-[17px] font-medium">Дополнительные проверки</h2>
    {files.length > 0 && <div className="result-document-scroll" role="region" aria-label="Решения по документам" tabIndex={0}>
      <table className="result-document-table">
        <thead><tr><th scope="col">Проверка</th><th scope="col">Документ</th>
          <th scope="col">Решение</th><th scope="col">Причина</th></tr></thead>
        <tbody>{files.map((file) => <tr key={file.id}>
          <td>{decisionTypes[file.decision.reason_code] ?? 'Проверка документа'}</td>
          <td><Link className="underline" to={runPath + '/documents?' + new URLSearchParams({ document: file.id })}>{file.name}</Link></td>
          <td>{documentDecisionLabels[file.decision.state]}</td><td>{file.decision.message}
            {file.errors.filter(({ message }) => message !== file.decision.message)
              .map((error) => <p key={error.id}>{error.message}</p>)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    {issues.length > 0 && <ul className="list-disc pl-5 text-sm">{issues.map((issue) => <li key={issue.id}>{issue.message}</li>)}</ul>}
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
  ambiguous_link: 'Неоднозначная связь',
};

export function ResultConclusion({ result, exportRunId }: { result: ReviewResult; exportRunId?: string }) {
  const { counts, conclusion } = result.summary;
  const tone = resultTone(counts);
  return <section aria-label="Заключение по проверке" className="result-summary mt-6 space-y-2">
    <h2 className="text-[15px] font-medium">Заключение</h2>
    <h3 className="result-summary-title" data-tone={tone}>{resultHeadline[tone]}</h3>
    <p className="max-w-[820px] text-[15px]">{conclusion}</p>
    {exportRunId && <XlsxDownload key={exportRunId} runId={exportRunId} />}
  </section>;
}
