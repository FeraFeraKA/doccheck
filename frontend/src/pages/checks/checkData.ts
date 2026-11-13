import { demoJob, demoTitle } from './demoData';
import type { ReviewResult } from './reviewResult';

export type RunStatus = 'queued' | 'processing' | 'completed' | 'completed_with_issues' | 'failed';

export const runStatusLabels: Record<RunStatus, string> = {
  queued: 'В очереди',
  processing: 'Обрабатывается',
  completed: 'Завершена',
  completed_with_issues: 'Завершена с замечаниями',
  failed: 'Завершилась ошибкой',
};

export interface HistoryEntry {
  id: string;
  title: string;
  status: RunStatus;
  contractNumber?: string;
  period?: string;
  documentCount?: number;
}

export interface CheckHistory {
  entries: HistoryEntry[];
  indicatorCounts?: ReviewResult['summary']['counts'];
}

export interface RunDetails {
  title: string;
  status: RunStatus;
  progress?: { processed: number; total: number };
  error?: string;
  result: ReviewResult | null;
}

// The screens take display data. An API adapter must validate the HTTP responses
// against the contracts before mapping them into these props.
function demoRunStatus(value: string): RunStatus {
  if (value === 'completed' || value === 'completed_with_issues') return value;
  throw new Error('Ожидался завершённый синтетический запуск');
}

export async function loadDemoHistory(): Promise<CheckHistory> {
  const { scope, documents, summary } = demoJob.result;
  return { indicatorCounts: summary.counts, entries: [{
    id: demoJob.run_id,
    title: demoTitle,
    status: demoRunStatus(demoJob.status),
    contractNumber: scope.contract_number,
    period: scope.period_start + ' — ' + scope.period_end,
    documentCount: documents.length,
  }] };
}

export async function loadDemoRun(id: string): Promise<RunDetails | null> {
  if (id !== demoJob.run_id) return null;
  return { title: demoTitle, status: demoRunStatus(demoJob.status), result: demoJob.result };
}
