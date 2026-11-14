import { HttpError } from '../../shared/api/requestJson';
import { isRunId } from './runStatusApi';

const runsPath = '/api/v0/runs';

export interface RunUpload {
  report: File;
  documents: readonly File[];
  synthetic?: boolean;
}

interface RunTransfer {
  report?: File;
  documents: readonly File[];
  sourceRunId?: string;
  retainedDocumentIds?: readonly string[];
}

export interface RetainedDocument {
  id: string;
  name: string;
  size: number;
  role: 'report' | 'supporting';
}

export interface AcceptedRun {
  run_id: string;
  status: 'queued';
  location: string;
}

const errorCodes = [
  'invalid_request',
  'invalid_input',
  'idempotency_conflict',
  'upload_too_large',
  'unsupported_media_type',
  'unsupported_file_format',
  'service_unavailable',
  'upload_expired',
  'upload_not_found',
  'run_not_found',
  'document_not_found',
  'result_pending',
] as const;

type UploadErrorCode = typeof errorCodes[number];

interface UploadErrorDetails {
  code: UploadErrorCode;
  message: string;
  field?: string;
  file_index?: number;
}

export class RunUploadHttpError extends HttpError {
  constructor(status: number, readonly details: UploadErrorDetails | null) {
    super(status);
    this.name = 'RunUploadHttpError';
  }
}

export class InvalidRunUploadResponse extends Error {
  constructor() {
    super('API вернул некорректное подтверждение загрузки.');
    this.name = 'InvalidRunUploadResponse';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isUploadErrorCode(value: unknown): value is UploadErrorCode {
  return errorCodes.some((code) => code === value);
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch (error) {
    if (error instanceof SyntaxError) return null;
    throw error;
  }
}

function parseUploadError(value: unknown): UploadErrorDetails | null {
  if (!isRecord(value) || !isUploadErrorCode(value.code) || typeof value.message !== 'string') return null;

  const { code, message, field, file_index } = value;
  if (field !== undefined && typeof field !== 'string') return null;
  if (file_index !== undefined && !(typeof file_index === 'number' && Number.isInteger(file_index) && file_index >= 0)) {
    return null;
  }
  const details: UploadErrorDetails = { code, message };
  if (field !== undefined) details.field = field;
  if (file_index !== undefined) details.file_index = file_index;
  return details;
}

function hasExpectedLocation(value: string | null, requestUrl: URL, path: string): boolean {
  if (value === null) return false;
  try {
    return new URL(value, requestUrl).href === requestUrl.origin + path;
  } catch {
    return false;
  }
}

/** Один снимок пакета и UUID на осознанную отправку. Для повтора вызовите ту же функцию. */
export function prepareRunUpload(upload: RunUpload, idempotencyKey: string) {
  const form = new FormData();
  form.append('report', upload.report);
  for (const document of upload.documents) form.append('documents', document);
  if (upload.synthetic) form.append('synthetic', 'true');

  return async (signal?: AbortSignal, onProgress?: (percent: number) => void): Promise<AcceptedRun> => {
    const requestUrl = new URL(runsPath, globalThis.location.origin);
    if (onProgress) {
      return sendWithProgress(requestUrl, form, idempotencyKey, signal, onProgress, acceptResponse);
    }
    const response = await fetch(requestUrl.href, {
      method: 'POST',
      body: form,
      headers: { 'Idempotency-Key': idempotencyKey },
      redirect: 'error',
      signal,
    });

    return acceptResponse(response.status, await readJson(response), response.headers.get('Location'), requestUrl);
  };
}

export function prepareRunTransfer(upload: RunTransfer, idempotencyKey: string) {
  const form = new FormData();
  if (upload.report) form.append('report', upload.report);
  for (const document of upload.documents) form.append('documents', document);
  if (upload.sourceRunId) form.append('source_run_id', upload.sourceRunId);
  for (const id of upload.retainedDocumentIds ?? []) form.append('retained_document_id', id);

  function acceptTransfer(status: number, value: unknown): { upload_id: string } {
    if (status < 200 || status >= 300) throw new RunUploadHttpError(status, parseUploadError(value));
    if (status !== 201 || !isRecord(value) || !isRunId(value.upload_id)) {
      throw new InvalidRunUploadResponse();
    }
    return { upload_id: value.upload_id };
  }

  return async (signal?: AbortSignal, onProgress?: (percent: number) => void) => {
    const url = new URL(runsPath + '/uploads', globalThis.location.origin);
    if (onProgress) return sendWithProgress(url, form, idempotencyKey, signal, onProgress, acceptTransfer);
    const response = await fetch(url.href, {
      method: 'POST', body: form, headers: { 'Idempotency-Key': idempotencyKey }, signal,
      redirect: 'error',
    });
    return acceptTransfer(response.status, await readJson(response));
  };
}

export async function startPreparedRun(uploadId: string, signal?: AbortSignal): Promise<AcceptedRun> {
  if (!isRunId(uploadId)) throw new TypeError('Invalid upload ID');
  const url = new URL(`${runsPath}/uploads/${uploadId}/start`, globalThis.location.origin);
  const response = await fetch(url.href, { method: 'POST', signal, redirect: 'error' });
  return acceptResponse(response.status, await readJson(response), response.headers.get('Location'), url);
}

export async function discardPreparedRun(uploadId: string, signal?: AbortSignal): Promise<void> {
  if (!isRunId(uploadId)) throw new TypeError('Invalid upload ID');
  const response = await fetch(`${runsPath}/uploads/${uploadId}`, {
    method: 'DELETE', signal, redirect: 'error',
  });
  if (!response.ok && response.status !== 404) {
    throw new RunUploadHttpError(response.status, parseUploadError(await readJson(response)));
  }
}

export async function getEditableRunPack(runId: string, signal: AbortSignal) {
  if (!isRunId(runId)) throw new TypeError('Invalid run ID');
  const response = await fetch(`${runsPath}/${runId}/pack`, { signal, cache: 'no-store', redirect: 'error' });
  const value = await readJson(response);
  if (!response.ok) throw new RunUploadHttpError(response.status, parseUploadError(value));
  if (!isRecord(value) || !Array.isArray(value.documents) || !value.documents.every(isRetainedDocument)) {
    throw new InvalidRunUploadResponse();
  }
  return { runId, documents: value.documents };
}

function isRetainedDocument(value: unknown): value is RetainedDocument {
  return isRecord(value) && isRunId(value.id) && typeof value.name === 'string'
    && typeof value.size === 'number' && Number.isSafeInteger(value.size) && value.size > 0
    && (value.role === 'report' || value.role === 'supporting');
}

function acceptResponse(status: number, value: unknown, location: string | null, requestUrl: URL): AcceptedRun {
  if (status < 200 || status >= 300) throw new RunUploadHttpError(status, parseUploadError(value));
  if (status !== 202 || !isRecord(value) || value.status !== 'queued' || !isRunId(value.run_id)) {
    throw new InvalidRunUploadResponse();
  }

  const path = runsPath + '/' + value.run_id;
  if (!hasExpectedLocation(location, requestUrl, path)) throw new InvalidRunUploadResponse();
  return { run_id: value.run_id, status: 'queued', location: path };
}

function sendWithProgress<T>(
  url: URL,
  form: FormData,
  key: string,
  signal: AbortSignal | undefined,
  onProgress: (percent: number) => void,
  accept: (status: number, value: unknown, location: string | null, url: URL) => T,
): Promise<T> {
  return new Promise((resolve, reject) => {
    signal?.throwIfAborted();
    const request = new XMLHttpRequest();
    const abort = () => request.abort();
    request.open('POST', url.href);
    request.timeout = 60_000;
    request.responseType = 'json';
    request.setRequestHeader('Idempotency-Key', key);
    let sentPercent = -1;
    function reportProgress(percent: number) {
      if (percent <= sentPercent) return;
      sentPercent = percent;
      onProgress(percent);
    }
    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && event.total > 0) {
        reportProgress(Math.min(100, Math.floor(100 * event.loaded / event.total)));
      }
    });
    request.upload.addEventListener('load', () => reportProgress(100), { once: true });
    request.addEventListener('load', () => {
      try {
        if (request.responseURL !== url.href) throw new InvalidRunUploadResponse();
        resolve(accept(request.status, request.response, request.getResponseHeader('Location'), url));
      } catch (error) {
        reject(error);
      }
    });
    request.addEventListener('error', () => reject(new TypeError('Не удалось отправить пакет')));
    request.addEventListener('timeout', () => reject(new DOMException('Время отправки истекло', 'TimeoutError')));
    request.addEventListener('abort', () => reject(signal?.reason ?? new DOMException('Отправка прервана', 'AbortError')));
    request.addEventListener('loadend', () => signal?.removeEventListener('abort', abort));
    signal?.addEventListener('abort', abort, { once: true });
    request.send(form);
  });
}
