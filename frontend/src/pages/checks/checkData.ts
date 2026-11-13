import { HttpError } from '../../shared/api/requestJson';
import { demoJob, demoTitle } from './demoData';
import type { ReviewResult } from './reviewResult';
import { isRunId, listRuns, pollRun } from './runStatusApi';
import type { RunState } from './runStatusApi';

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
  createdAt: string;
}

export interface CheckHistory {
  entries: HistoryEntry[];
  nextCursor: string | null;
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

export async function loadRunHistory(signal: AbortSignal, cursor?: string): Promise<CheckHistory> {
  const page = await listRuns(signal, { cursor });
  return {
    entries: page.items.map((run) => ({
      id: run.run_id,
      title: `Проверка ${run.run_id}`,
      status: run.status,
      createdAt: run.created_at,
    })),
    nextCursor: page.next_cursor,
  };
}

export async function loadDemoRun(id: string): Promise<RunDetails | null> {
  if (id !== demoJob.run_id) return null;
  return { title: demoTitle, status: demoRunStatus(demoJob.status), result: demoJob.result };
}

function toRunDetails(run: RunState): RunDetails {
  return {
    title: `Проверка ${run.run_id}`,
    status: run.status,
    progress: run.progress === null ? undefined : {
      processed: run.progress.processed_documents,
      total: run.progress.total_documents,
    },
    error: run.error?.message,
    result: null,
  };
}

export async function loadCheckRun(
  id: string,
  signal: AbortSignal,
  onUpdate: (run: RunDetails) => void,
): Promise<RunDetails | null> {
  if (id === demoJob.run_id) return loadDemoRun(id);
  if (!isRunId(id)) return null;
  try {
    return toRunDetails(await pollRun(id, signal, (run) => onUpdate(toRunDetails(run))));
  } catch (error) {
    if (error instanceof HttpError && error.status === 404) return null;
    throw error;
  }
}
