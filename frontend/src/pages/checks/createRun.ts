import { HttpError } from '../../shared/api/requestJson';

const runsPath = '/api/v0/runs';
const runIdPattern = /^[A-Za-z0-9_-]+$/;

interface PageLocator {
  kind: 'page';
  page: number;
  bbox?: readonly [number, number, number, number] | null;
  line?: number | null;
  table_row?: number | null;
  table_column?: number | null;
  fragment_id?: string | null;
}

interface SheetLocator {
  kind: 'sheet';
  sheet: string;
  range: string;
}

interface ParagraphLocator {
  kind: 'paragraph';
  paragraph: number;
}

interface TableCellLocator {
  kind: 'table_cell';
  table: number;
  row: number;
  cell: number;
}

export interface RunUpload {
  report: File;
  documents: readonly File[];
  contract_number: string;
  period_start: string;
  period_end: string;
  report_row_locator: PageLocator | SheetLocator | ParagraphLocator | TableCellLocator;
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
  return { code, message, field, file_index };
}

/** Один снимок пакета и UUID на осознанную отправку. Для повтора вызовите ту же функцию. */
export function prepareRunUpload(upload: RunUpload, idempotencyKey: string) {
  const form = new FormData();
  form.append('report', upload.report);
  for (const document of upload.documents) form.append('documents', document);
  form.append('contract_number', upload.contract_number);
  form.append('period_start', upload.period_start);
  form.append('period_end', upload.period_end);
  form.append('report_row_locator', JSON.stringify(upload.report_row_locator));

  return async (signal?: AbortSignal): Promise<AcceptedRun> => {
    const response = await fetch(runsPath, {
      method: 'POST',
      body: form,
      headers: { 'Idempotency-Key': idempotencyKey },
      redirect: 'error',
      signal,
    });

    if (!response.ok) throw new RunUploadHttpError(response.status, parseUploadError(await readJson(response)));
    if (response.status !== 202) throw new InvalidRunUploadResponse();

    const value = await readJson(response);
    const location = response.headers.get('Location');
    if (!isRecord(value) || value.status !== 'queued'
      || typeof value.run_id !== 'string' || !runIdPattern.test(value.run_id)
      || location !== runsPath + '/' + value.run_id) {
      throw new InvalidRunUploadResponse();
    }
    return { run_id: value.run_id, status: value.status, location };
  };
}
