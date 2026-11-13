import { HttpError } from '../../shared/api/requestJson';
import { isRunId } from './runStatusApi';

const runsPath = '/api/v0/runs';

export interface RunUpload {
  report: File;
  documents: readonly File[];
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

  return async (signal?: AbortSignal): Promise<AcceptedRun> => {
    const requestUrl = new URL(runsPath, globalThis.location.origin);
    const response = await fetch(requestUrl.href, {
      method: 'POST',
      body: form,
      headers: { 'Idempotency-Key': idempotencyKey },
      redirect: 'error',
      signal,
    });

    if (!response.ok) throw new RunUploadHttpError(response.status, parseUploadError(await readJson(response)));
    if (response.status !== 202) throw new InvalidRunUploadResponse();

    const value = await readJson(response);
    if (!isRecord(value) || value.status !== 'queued'
      || !isRunId(value.run_id)) {
      throw new InvalidRunUploadResponse();
    }

    const location = runsPath + '/' + value.run_id;
    if (!hasExpectedLocation(response.headers.get('Location'), requestUrl, location)) {
      throw new InvalidRunUploadResponse();
    }
    return { run_id: value.run_id, status: value.status, location };
  };
}
