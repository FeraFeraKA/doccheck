import { runTitle } from './runTitle';
import { HttpError } from '../../shared/api/requestJson';
import { demoJob, demoTitle } from './demoData';
import { readDocumentParseStatus, readRubCoverage } from './loadFindings';
import type { ReviewResult } from './reviewResult';
import { isRunId, listRuns, pollRun } from './runStatusApi';
import type { RunState } from './runStatusApi';

export type RunStatus = 'queued' | 'processing' | 'completed' | 'completed_with_issues' | 'failed';

export type FindingFilter = 'verified' | 'discrepancy' | 'unverified';
export type FindingCounts = Record<FindingFilter, number>;

export const runStatusLabels: Record<RunStatus, string> = {
  queued: 'В очереди',
  processing: 'Обработка документов',
  completed: 'Готово',
  completed_with_issues: 'Готово с замечаниями',
  failed: 'Ошибка обработки',
};

export interface HistoryEntry {
  id: string;
  title: string;
  status: RunStatus;
  createdAt: string;
  archivedAt?: string;
  counts?: FindingCounts;
  synthetic?: boolean;
  documentCount?: number;
  contractNumber?: string;
  error?: string;
}

export interface CheckHistory {
  entries: HistoryEntry[];
  nextCursor: string | null;
}

export interface RunDetails {
  title: string;
  status: RunStatus;
  progress?: { processed: number; total: number };
  archivedAt?: string;
  error?: string;
  errorCode?: string;
  result: ReviewResult | null;
}

// The screens take display data. An API adapter must validate the HTTP responses
// against the contracts before mapping them into these props.
function demoRunStatus(value: string): RunStatus {
  if (value === 'completed' || value === 'completed_with_issues') return value;
  throw new Error('Ожидался завершённый синтетический запуск');
}

export async function loadRunHistory(
  signal: AbortSignal, cursor?: string, finding?: FindingFilter, view?: 'archive',
): Promise<CheckHistory> {
  const page = await listRuns(signal, { cursor, finding, view });
  return {
    entries: page.items.map((run) => ({
      id: run.run_id,
      title: run.synthetic && !run.report_number ? demoTitle : runTitle(run.run_id, run.report_number),
      status: run.status,
      createdAt: run.created_at,
      counts: run.counts,
      synthetic: run.synthetic,
      documentCount: run.document_count,
      contractNumber: run.contract_number,
      archivedAt: run.archived_at,
      error: run.error?.message,
    })),
    nextCursor: page.next_cursor,
  };
}

export async function loadDemoRun(id: string): Promise<RunDetails | null> {
  if (id !== demoJob.run_id) return null;
  const result = {
    ...demoJob.result,
    summary: { ...demoJob.result.summary, rubCoverage: readRubCoverage(demoJob.result.summary.rub_coverage) },
    documents: demoJob.result.documents.map((document) => ({
      ...document,
      parse_status: readDocumentParseStatus(document.parse_status),
    })),
  };
  return { title: demoTitle, status: demoRunStatus(demoJob.status), result };
}

function toRunDetails(run: RunState): RunDetails {
  return {
    title: runTitle(run.run_id),
    status: run.status,
    progress: run.progress === null ? undefined : {
      processed: run.progress.processed_documents,
      total: run.progress.total_documents,
    },
    error: run.error?.message,
    errorCode: run.error?.code,
    archivedAt: run.archived_at,
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
