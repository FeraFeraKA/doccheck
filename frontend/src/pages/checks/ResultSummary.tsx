import type { ReactNode } from 'react';
import { Link } from 'react-router';
import type { ReviewResult } from './reviewResult';
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

function Card({ title, children }: { title: string; children: ReactNode }) {
  return <section className="result-summary-card rounded-lg border p-5">
    <h3 className="mb-3 text-[15px] font-medium">{title}</h3>
    {children}
  </section>;
}

export function ResultSummary({ runPath, result, exportRunId, onOpenRow }: {
  runPath: string;
  result: ReviewResult;
  exportRunId?: string;
  onOpenRow?: (rowId: string) => void;
}) {
  const { counts, conclusion, primary_issues: issues } = result.summary;
  const total = counts.verified + counts.discrepancy + counts.unverified;
  const tone = resultTone(counts);

  return (
    <section aria-label="Заключение по проверке" className="result-summary mt-6 space-y-5">
      <div>
        <p className="result-summary-muted text-[13px]">Вывод по проверке</p>
        <h2 className="result-summary-title" data-tone={tone}>{resultHeadline[tone]}</h2>
        <p className="mt-2 max-w-[820px] text-[15px]">{conclusion}</p>
        {exportRunId && <div className="result-summary-actions mt-4 flex flex-wrap items-center gap-3">
          <XlsxDownload key={exportRunId} runId={exportRunId} />
        </div>}
      </div>

      <dl aria-label="Счётчики показателей" className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {statuses.map(([status, label]) => (
          <div key={status} className="result-summary-card rounded-lg border px-4 py-2 sm:p-4">
            <dt className="result-summary-muted text-sm">{label}</dt>
            <dd className="result-summary-count mt-1 text-2xl font-medium tabular-nums" data-tone={status}>
              <span className="sr-only">{label}: </span>{counts[status]}
            </dd>
          </div>
        ))}
      </dl>
      <div className="result-summary-grid grid grid-cols-1 gap-4">
        <Card title="Покрытие">
          <div className="mb-1.5 flex flex-wrap justify-between gap-x-3 text-[13px]">
            <span className="result-summary-muted">По строкам</span>
            <span className="tabular-nums">{total > 0 ? `${counts.verified} из ${total} подтверждено` : 'Показатели отсутствуют'}</span>
          </div>
          {total > 0 && <div aria-hidden="true" className="result-summary-coverage flex h-2 overflow-hidden rounded-full">
            {statuses.map(([status]) => <div key={status} data-tone={status} style={{ width: `${counts[status] / total * 100}%` }} />)}
          </div>}
        </Card>
        <Card title="Найденные проблемы">
          {issues.length > 0 ? (
            <ul className="space-y-2 text-[13px]">
              {issues.map((issue) => {
                const row = result.rows.find((item) => item.root_issue_id === issue.id);
                return <li key={issue.id}>
                  <span>{issue.message}</span>
                  {row && onOpenRow && <button type="button"
                    className="mt-1 block text-left underline"
                    onClick={() => onOpenRow(row.id)}>
                    К показателю «{row.label}»
                  </button>}
                </li>;
              })}
            </ul>
          ) : <p className="result-summary-muted text-sm">Первичные замечания отсутствуют.</p>}
          <Link to={runPath + '/exceptions'} className="mt-2 inline-block text-[13px]">Исключения</Link>
        </Card>
      </div>
    </section>
  );
}
