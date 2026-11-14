import { Link } from 'react-router';
import type { ReviewResult } from './reviewResult';
import './result-header.css';

const tabs = [
  { suffix: '', label: 'Результат' },
  { suffix: '/documents', label: 'Документы' },
] as const;

export type CheckView = 'table' | 'documents' | 'exceptions' | 'conclusion' | 'log';

export function ResultHeader({ title, runPath, view, scope, conclusion, tone, syntheticLabel }: {
  title: string;
  runPath: string;
  view: CheckView;
  scope: ReviewResult['scope'];
  conclusion: string;
  tone: string;
  syntheticLabel?: string;
}) {
  return (
    <header className="check-result-header">
      <nav className="text-[13px]" aria-label="Путь к проверке">
        <Link to="/checks">Все проверки</Link>
        <span className="mx-1.5" aria-hidden="true">/</span>
        <span aria-current="page">{title}</span>
      </nav>
      <div className="mt-3">
        <h1>{title}</h1>
        <div className="result-header-meta mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
          <span className="tabular-nums">Договор {scope.contract_number} · Период {scope.period_start} — {scope.period_end}</span>
          <span className="result-header-badge" data-tone={tone}>{conclusion}</span>
          {syntheticLabel && <span className="result-synthetic-label">{syntheticLabel}</span>}
        </div>
      </div>
      <nav aria-label="Разделы проверки" className="check-result-tabs mt-6 flex border-b">
        {tabs.map(({ suffix, label }) => {
          const selected = suffix === '' ? view === 'table' || view === 'conclusion' : view === 'documents' || view === 'exceptions';
          return <Link key={suffix} to={runPath + suffix} aria-current={selected ? 'page' : undefined}>{label}</Link>;
        })}
      </nav>
    </header>
  );
}
