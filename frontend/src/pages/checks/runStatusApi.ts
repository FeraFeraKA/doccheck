import { requestJson } from '../../shared/api/requestJson';
import type { FindingFilter, FindingCounts, RunStatus } from './checkData';

interface RunError {
  code: string;
  message: string;
}

interface RunSummary {
  run_id: string;
  status: RunStatus;
  created_at: string;
  error: RunError | null;
}

interface RunProgress {
  processed_documents: number;
  total_documents: number;
}

export interface RunState extends RunSummary {
  progress: RunProgress | null;
  archived_at?: string;
}

interface RunHistoryPage {
  items: (RunSummary & { counts?: FindingCounts; report_number?: string; synthetic?: boolean;
    document_count?: number; contract_number?: string; archived_at?: string })[];
  next_cursor: string | null;
}

interface RunHistoryQuery {
  cursor?: string;
  limit?: number;
  finding?: FindingFilter;
  view?: 'archive';
}

export class InvalidRunResponseError extends Error {
  constructor() {
    super('Invalid runs API response');
    this.name = 'InvalidRunResponseError';
  }
}

const runsPath = '/api/v0/runs';
const pollIntervalMs = 500;
const dateTimePattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isRunId(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && !/[^A-Za-z0-9_-]/.test(value);
}

function isRunStatus(value: unknown): value is RunStatus {
  return value === 'queued' || value === 'processing' || value === 'completed'
    || value === 'completed_with_issues' || value === 'failed';
}

function isRunError(value: unknown): value is RunError {
  return isRecord(value) && typeof value.code === 'string' && value.code.length > 0
    && typeof value.message === 'string' && value.message.length > 0;
}

function parseRunSummary(value: unknown): RunSummary {
  if (!isRecord(value) || !isRunId(value.run_id) || !isRunStatus(value.status)
    || typeof value.created_at !== 'string' || !dateTimePattern.test(value.created_at)
    || !Number.isFinite(Date.parse(value.created_at))
    || !(value.error === null || isRunError(value.error))) {
    throw new InvalidRunResponseError();
  }

  return {
    run_id: value.run_id,
    status: value.status,
    created_at: value.created_at,
    error: value.error,
  };
}

function isRunProgress(value: unknown): value is RunProgress {
  if (!isRecord(value)) return false;
  const { processed_documents, total_documents } = value;
  return typeof processed_documents === 'number' && Number.isInteger(processed_documents)
    && typeof total_documents === 'number' && Number.isInteger(total_documents)
    && total_documents >= 2 && total_documents <= 101
    && processed_documents >= 0 && processed_documents <= total_documents;
}

function parseRunState(value: unknown, runId: string): RunState {
  if (!isRecord(value)) throw new InvalidRunResponseError();
  const summary = parseRunSummary(value);
  const { progress } = value;
  if (summary.run_id !== runId || !(progress === null || isRunProgress(progress))) {
    throw new InvalidRunResponseError();
  }
  if (summary.status === 'queued' && progress?.processed_documents !== 0) {
    throw new InvalidRunResponseError();
  }
  if ((summary.status === 'completed' || summary.status === 'completed_with_issues')
    && (progress === null || progress.processed_documents !== progress.total_documents)) {
    throw new InvalidRunResponseError();
  }
  const archivedAt = readArchivedAt(value.archived_at);
  return { ...summary, progress, ...(archivedAt ? { archived_at: archivedAt } : {}) };
}

async function getRunJson(path: string, signal: AbortSignal): Promise<unknown> {
  signal.throwIfAborted();
  const boundedSignal = AbortSignal.any([signal, AbortSignal.timeout(5_000)]);
  const value = await requestJson<unknown>(path, { cache: 'no-store', signal: boundedSignal });
  boundedSignal.throwIfAborted();
  return value;
}

export async function getRun(runId: string, signal: AbortSignal): Promise<RunState> {
  if (!isRunId(runId)) throw new TypeError('Invalid run ID');
  const value = await getRunJson(`${runsPath}/${runId}`, signal);
  signal.throwIfAborted();
  return parseRunState(value, runId);
}

export async function listRuns(
  signal: AbortSignal,
  { cursor, limit, finding, view }: RunHistoryQuery = {},
): Promise<RunHistoryPage> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set('limit', String(limit));
  if (cursor !== undefined) params.set('cursor', cursor);
  if (finding !== undefined) params.set('finding', finding);
  if (view) params.set('view', view);
  const query = params.toString();
  const value = await getRunJson(query ? `${runsPath}?${query}` : runsPath, signal);
  signal.throwIfAborted();
  if (!isRecord(value) || !Array.isArray(value.items)
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')) {
    throw new InvalidRunResponseError();
  }
  return { items: value.items.map(parseHistoryRun), next_cursor: value.next_cursor };
}

function parseHistoryRun(value: unknown): RunHistoryPage['items'][number] {
  const run = parseRunSummary(value);
  if (!isRecord(value)) throw new InvalidRunResponseError();
  const { counts, report_number: number, synthetic, document_count, contract_number } = value;
  const archivedAt = readArchivedAt(value.archived_at);
  if (number != null && typeof number !== 'string') throw new InvalidRunResponseError();
  if (synthetic != null && typeof synthetic !== 'boolean') throw new InvalidRunResponseError();
  if (contract_number != null && typeof contract_number !== 'string') throw new InvalidRunResponseError();
  if (document_count != null && (typeof document_count !== 'number' || !Number.isSafeInteger(document_count)
    || document_count < 0 || document_count > 101)) throw new InvalidRunResponseError();
  return {
    ...run,
    ...(counts == null ? {} : { counts: parseCounts(counts) }),
    ...(number == null ? {} : { report_number: number }),
    ...(synthetic == null ? {} : { synthetic }),
    ...(document_count == null ? {} : { document_count }),
    ...(contract_number == null ? {} : { contract_number }),
    ...(archivedAt ? { archived_at: archivedAt } : {}),
  };
}

function readArchivedAt(value: unknown) {
  if (value == null) return undefined;
  if (typeof value !== 'string' || !dateTimePattern.test(value) || !Number.isFinite(Date.parse(value))) {
    throw new InvalidRunResponseError();
  }
  return value;
}

export async function updateRunArchive(runId: string, archived: boolean, signal: AbortSignal) {
  if (!isRunId(runId)) throw new TypeError('Invalid run ID');
  const value = await requestJson<unknown>(`${runsPath}/${runId}/archive`, {
    method: archived ? 'PUT' : 'DELETE', cache: 'no-store', signal,
  });
  if (!isRecord(value) || !('archived_at' in value)) throw new InvalidRunResponseError();
  const timestamp = readArchivedAt(value.archived_at);
  if (archived !== Boolean(timestamp)) throw new InvalidRunResponseError();
  return timestamp;
}

function parseCounts(value: unknown): FindingCounts {
  if (!isRecord(value)) throw new InvalidRunResponseError();
  const { verified, discrepancy, unverified } = value;
  function count(input: unknown): number {
    if (typeof input !== 'number' || !Number.isSafeInteger(input) || input < 0) {
      throw new InvalidRunResponseError();
    }
    return input;
  }
  return { verified: count(verified), discrepancy: count(discrepancy), unverified: count(unverified) };
}

function waitForNextPoll(signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', cancelWait);
      resolve();
    }, pollIntervalMs);

    function cancelWait() {
      clearTimeout(timer);
      reject(signal.reason);
    }

    signal.addEventListener('abort', cancelWait, { once: true });
  });
}

export async function pollRun(
  runId: string,
  signal: AbortSignal,
  onState: (state: RunState) => void,
): Promise<RunState> {
  for (;;) {
    const run = await getRun(runId, signal);
    signal.throwIfAborted();
    onState(run);
    if (run.status !== 'queued' && run.status !== 'processing') return run;
    await waitForNextPoll(signal);
  }
}
