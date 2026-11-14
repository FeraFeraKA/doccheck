import { HttpError } from '../../shared/api/requestJson';

interface PageLocator {
  kind: 'page';
  page: number;
  bbox?: [number, number, number, number] | null;
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

type SourceLocator = PageLocator | SheetLocator | ParagraphLocator | TableCellLocator;
type EvidenceKind = 'reported_value' | 'amount' | 'contract' | 'period' | 'article' | 'document_identity' | 'stage';
interface Period {
  start: string | null;
  end: string | null;
}

export interface SourceEvidence {
  id: string;
  document_id: string;
  kind: EvidenceKind;
  raw_value: string;
  normalized_value: string | Period;
  unit: string | null;
  method: string;
  locator: SourceLocator;
}

type SourceErrorCode = 'run_not_found' | 'document_not_found' | 'fragment_not_found'
  | 'result_pending' | 'run_failed' | 'invalid_input' | 'service_unavailable';

export class SourceHttpError extends HttpError {
  constructor(status: number, readonly code: SourceErrorCode | null) {
    super(status);
    this.name = 'SourceHttpError';
  }
}

export class InvalidSourceResponseError extends Error {
  constructor() {
    super('Invalid source API response');
    this.name = 'InvalidSourceResponseError';
  }
}

export function documentUrl(runId: string, documentId: string): string {
  const segment = /^[A-Za-z0-9_-]+(?![\s\S])/;
  if (!segment.test(runId) || !segment.test(documentId)) {
    throw new TypeError('Invalid run or document ID');
  }
  return `/api/v0/runs/${runId}/documents/${documentId}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function isIndex(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1;
}

function isCoordinate(value: unknown): value is number {
  return typeof value === 'number' && value >= 0 && value <= 1;
}

function isBox(value: unknown): value is [number, number, number, number] {
  if (!Array.isArray(value) || value.length !== 4) return false;
  const [left, top, right, bottom] = value;
  return isCoordinate(left) && isCoordinate(top) && isCoordinate(right) && isCoordinate(bottom)
    && left < right && top < bottom;
}

function isSheetRange(value: unknown): value is string {
  if (!isText(value)) return false;
  const bounds = /^([A-Z]{1,3})([1-9][0-9]{0,6})(?::([A-Z]{1,3})([1-9][0-9]{0,6}))?(?![\s\S])/.exec(value);
  if (!bounds) return false;
  const [, firstColumn, firstRow, lastColumn = firstColumn, lastRow = firstRow] = bounds;
  const columnNumber = (column: string) =>
    Array.from(column).reduce((index, char) => index * 26 + char.charCodeAt(0) - 64, 0);
  const first = columnNumber(firstColumn);
  const last = columnNumber(lastColumn);
  return first <= last && last <= 16_384
    && Number(firstRow) <= Number(lastRow) && Number(lastRow) <= 1_048_576;
}

function isLocator(locator: unknown): locator is SourceLocator {
  if (!isRecord(locator)) return false;
  switch (locator.kind) {
    case 'page': {
      if (!isIndex(locator.page)) return false;
      const { bbox, line, table_row: row, table_column: column, fragment_id: fragment } = locator;
      return (bbox == null || isBox(bbox)) && (line == null || isIndex(line))
        && (row == null ? column == null : isIndex(row) && isIndex(column))
        && (fragment == null || isText(fragment))
        && (bbox != null || line != null || row != null || fragment != null);
    }
    case 'sheet':
      return isText(locator.sheet) && isSheetRange(locator.range);
    case 'paragraph':
      return isIndex(locator.paragraph);
    case 'table_cell':
      return isIndex(locator.table) && isIndex(locator.row) && isIndex(locator.cell);
    default:
      return false;
  }
}

function isIsoDate(value: unknown): value is string {
  if (!isText(value) || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}(?![\s\S])/.test(value)
    || value.startsWith('0000')) return false;
  const date = new Date(value);
  return Number.isFinite(date.valueOf()) && date.toISOString().slice(0, 10) === value;
}

function isPeriod(value: unknown): value is Period {
  if (!isRecord(value)) return false;
  const { start, end } = value;
  if (start === null) return isIsoDate(end);
  return isIsoDate(start) && (end === null || (isIsoDate(end) && start <= end));
}

function isEvidence(value: unknown): value is SourceEvidence {
  if (!isRecord(value) || !isText(value.id) || !isText(value.document_id) || !isText(value.raw_value)
    || !isText(value.method) || !(value.unit === null || isText(value.unit))
    || !isLocator(value.locator)) return false;

  const normalized = value.normalized_value;
  switch (value.kind) {
    case 'period':
      return isPeriod(normalized);
    case 'amount':
    case 'reported_value':
      if (!isText(normalized)) return false;
      return value.unit === 'RUB'
        ? /^(?!-0+\.00(?![\s\S]))-?[0-9]+\.[0-9]{2}(?![\s\S])/.test(normalized)
        : /^-?[0-9]+(?:\.[0-9]+)?(?![\s\S])/.test(normalized);
    case 'contract':
    case 'article':
    case 'document_identity':
    case 'stage':
      return isText(normalized);
    default:
      return false;
  }
}

function isSourceErrorCode(value: unknown): value is SourceErrorCode {
  return value === 'run_not_found' || value === 'document_not_found' || value === 'fragment_not_found'
    || value === 'result_pending' || value === 'run_failed'
    || value === 'invalid_input' || value === 'service_unavailable';
}

async function responseJson(response: Response, signal: AbortSignal): Promise<unknown> {
  try {
    return await response.json();
  } catch (error) {
    signal.throwIfAborted();
    if (error instanceof SyntaxError) return null;
    throw error;
  }
}

async function requestSource(url: string, signal: AbortSignal): Promise<Response> {
  const response = await fetch(url, { signal });
  signal.throwIfAborted();
  if (response.status === 200) return response;
  if (response.ok) throw new InvalidSourceResponseError();
  const error = await responseJson(response, signal);
  signal.throwIfAborted();
  const code = isRecord(error) && isSourceErrorCode(error.code) ? error.code : null;
  throw new SourceHttpError(response.status, code);
}

export async function getSourceOriginal(
  runId: string, documentId: string, signal: AbortSignal,
): Promise<Blob> {
  const response = await requestSource(documentUrl(runId, documentId), signal);
  const contentType = response.headers.get('Content-Type')?.split(';', 1)[0]?.trim().toLowerCase();
  if (contentType !== 'application/octet-stream') throw new InvalidSourceResponseError();

  const original = await response.blob();
  signal.throwIfAborted();
  if (original.size === 0) throw new InvalidSourceResponseError();
  return original;
}

export async function getSourceEvidence(
  runId: string, documentId: string, evidenceId: string, signal: AbortSignal,
): Promise<SourceEvidence> {
  if (!isText(evidenceId)) throw new TypeError('Missing evidence ID');
  const query = new URLSearchParams({ evidence_id: evidenceId });
  const response = await requestSource(`${documentUrl(runId, documentId)}/fragments?${query}`, signal);
  const value = await responseJson(response, signal);
  signal.throwIfAborted();
  if (!isEvidence(value) || value.id !== evidenceId || value.document_id !== documentId) {
    throw new InvalidSourceResponseError();
  }
  return value;
}

type HighlightedText = { text: string; match?: [string, string, string] };

export async function getSourceFragmentPreview(
  runId: string, documentId: string, evidenceId: string, signal: AbortSignal,
): Promise<HighlightedText | null> {
  if (!isText(evidenceId)) throw new TypeError('Missing evidence ID');
  const query = new URLSearchParams({ evidence_id: evidenceId });
  const response = await requestSource(`${documentUrl(runId, documentId)}/fragment-preview?${query}`, signal);
  const value = await responseJson(response, signal);
  signal.throwIfAborted();
  if (!isRecord(value)) throw new InvalidSourceResponseError();
  const { text, highlight } = value;
  if (text === null && highlight === null) return null;
  if (typeof text !== 'string') throw new InvalidSourceResponseError();
  const bytes = new TextEncoder().encode(text);
  if (bytes.length > 4096) throw new InvalidSourceResponseError();
  if (highlight === null) return { text };
  if (!isRecord(highlight)) throw new InvalidSourceResponseError();

  const { start_byte: start, end_byte: end } = highlight;
  if (typeof start !== 'number' || typeof end !== 'number' || !Number.isInteger(start)
    || !Number.isInteger(end) || start < 0 || end <= start || end > bytes.length) {
    throw new InvalidSourceResponseError();
  }
  const decoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
  try {
    return { text, match: [
      decoder.decode(bytes.subarray(0, start)),
      decoder.decode(bytes.subarray(start, end)),
      decoder.decode(bytes.subarray(end)),
    ] };
  } catch {
    throw new InvalidSourceResponseError();
  }
}
