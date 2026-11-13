import { requestJson } from '../../shared/api/requestJson';
import type { RunStatus } from './checkData';

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
}

interface RunHistoryPage {
  items: RunSummary[];
  next_cursor: string | null;
}

interface RunHistoryQuery {
  cursor?: string;
  limit?: number;
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

function isRunId(value: unknown): value is string {
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
  return { ...summary, progress };
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
  return parseRunState(await getRunJson(`${runsPath}/${runId}`, signal), runId);
}

export async function listRuns(
  signal: AbortSignal,
  { cursor, limit }: RunHistoryQuery = {},
): Promise<RunHistoryPage> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set('limit', String(limit));
  if (cursor !== undefined) params.set('cursor', cursor);
  const query = params.toString();
  const value = await getRunJson(query ? `${runsPath}?${query}` : runsPath, signal);
  if (!isRecord(value) || !Array.isArray(value.items)
    || !(value.next_cursor === null || typeof value.next_cursor === 'string')) {
    throw new InvalidRunResponseError();
  }
  return { items: value.items.map(parseRunSummary), next_cursor: value.next_cursor };
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
