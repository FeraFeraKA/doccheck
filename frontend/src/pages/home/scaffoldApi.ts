import { HttpError, requestJson } from '../../shared/api/requestJson';

export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed';

/** Synthetic lifecycle only; the document-processing contract is defined separately. */
export interface SyntheticJob {
  id: string;
  synthetic: true;
  status: JobStatus;
  result: { synthetic: true; message: string } | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export class InvalidResponseError extends Error {
  constructor() {
    super('Invalid scaffold API response');
    this.name = 'InvalidResponseError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isTimestamp(value: unknown): value is string {
  return typeof value === 'string' && Number.isFinite(Date.parse(value));
}

function isNullableTimestamp(value: unknown): value is string | null {
  return value === null || isTimestamp(value);
}

function isResult(value: unknown): value is SyntheticJob['result'] {
  return value === null || (isRecord(value) && value.synthetic === true
    && typeof value.message === 'string' && value.message.length > 0);
}

function isJobStatus(value: unknown): value is JobStatus {
  return value === 'queued' || value === 'processing' || value === 'completed' || value === 'failed';
}

function parseJob(value: unknown): SyntheticJob {
  if (!isRecord(value) || typeof value.id !== 'string'
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.id)
    || value.synthetic !== true || !isJobStatus(value.status) || !isResult(value.result)
    || !(value.error === null || typeof value.error === 'string')
    || !isTimestamp(value.created_at) || !isNullableTimestamp(value.started_at)
    || !isNullableTimestamp(value.finished_at)) {
    throw new InvalidResponseError();
  }
  if ((value.status === 'completed' && (value.result === null || value.error !== null))
    || (value.status === 'failed' && (value.result !== null || !value.error))
    || ((value.status === 'queued' || value.status === 'processing')
      && (value.result !== null || value.error !== null))) {
    throw new InvalidResponseError();
  }
  return {
    id: value.id,
    synthetic: true,
    status: value.status,
    result: value.result,
    error: value.error,
    created_at: value.created_at,
    started_at: value.started_at,
    finished_at: value.finished_at,
  };
}

function boundedSignal(signal: AbortSignal): AbortSignal {
  return AbortSignal.any([signal, AbortSignal.timeout(5_000)]);
}

export async function checkHealth(signal: AbortSignal): Promise<void> {
  const value = await requestJson<unknown>('/health', { signal: boundedSignal(signal) });
  if (!isRecord(value) || value.status !== 'ok' || value.database !== 'ok') {
    throw new InvalidResponseError();
  }
}

export async function createSyntheticJob(signal: AbortSignal): Promise<SyntheticJob> {
  return parseJob(await requestJson<unknown>('/api/synthetic-jobs', {
    method: 'POST', signal: boundedSignal(signal),
  }));
}

export async function getSyntheticJob(id: string, signal: AbortSignal): Promise<SyntheticJob> {
  const job = parseJob(await requestJson<unknown>(`/api/synthetic-jobs/${encodeURIComponent(id)}`, {
    signal: boundedSignal(signal),
  }));
  if (job.id !== id) throw new InvalidResponseError();
  return job;
}

export function connectionError(error: unknown): string {
  if (error instanceof InvalidResponseError || error instanceof SyntaxError) {
    return 'API вернул некорректный ответ. Повторите проверку позже.';
  }
  if (error instanceof HttpError && error.status === 503) {
    return 'API пока не готов: проверьте доступность PostgreSQL и инициализацию схемы.';
  }
  if (error instanceof HttpError) {
    return 'Не удалось получить данные API. Повторите проверку позже.';
  }
  return 'Нет связи с API. Убедитесь, что сервер запущен, и повторите проверку.';
}
