import type { ReactNode } from 'react';
import { Link } from 'react-router';
import type { ReviewResult } from './reviewResult';
import './result-header.css';

const tabs = [
  { suffix: '', label: 'Результат' },
  { suffix: '/documents', label: 'Документы' },
] as const;

export type CheckView = 'table' | 'documents' | 'exceptions' | 'conclusion' | 'log';

export function ResultHeader({ title, runPath, view, scope, syntheticLabel, documentFilters, documentActions }: {
  title: string;
  runPath: string;
  view: CheckView;
  scope: ReviewResult['scope'];
  syntheticLabel?: string;
  documentFilters?: ReactNode;
  documentActions?: ReactNode;
}) {
  return (
    <header className="check-result-header">
      <nav className="mb-2 text-[13px]" aria-label="Путь к проверке">
        <Link to="/checks">Все проверки</Link>
      </nav>
      <div>
        <h1>{title}</h1>
        <div className="result-header-meta mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
          <span className="tabular-nums">Договор {scope.contract_number} · Период {scope.period_start} — {scope.period_end}</span>
          {syntheticLabel && <span className="result-synthetic-label">{syntheticLabel}</span>}
        </div>
      </div>
      <div className="check-header-controls mt-6 flex flex-wrap items-end justify-between gap-x-4 gap-y-2 border-b">
        <div className="flex min-w-0 flex-wrap items-end gap-x-4 gap-y-2">
          <nav aria-label="Разделы проверки" className="check-result-tabs flex gap-6">
            {tabs.map(({ suffix, label }) => {
              const selected = suffix === '' ? view === 'table' || view === 'conclusion' : view === 'documents' || view === 'exceptions';
              return <Link key={suffix} to={runPath + suffix} aria-current={selected ? 'page' : undefined}>{label}</Link>;
            })}
          </nav>
          {documentFilters}
        </div>
        {documentActions}
      </div>
    </header>
  );
}
