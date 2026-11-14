import { HttpError } from '../../shared/api/requestJson';
import { documentUrl, InvalidSourceResponseError } from './sourceApi';

interface SheetPreview {
  sheets: string[];
  sheet: string;
  row: number;
  column: number;
  last_row: number;
  last_column: number;
  rows: string[][];
}

interface WordCell {
  column: number;
  span: number;
  text: string;
}

interface WordParagraph {
  paragraph: number;
  text: string;
  heading: boolean;
}

interface WordTable {
  table: number;
  rows: WordCell[][];
}

export type OfficePreview = SheetPreview | { blocks: (WordParagraph | WordTable)[]; truncated: boolean };

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function positive(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

function stringRow(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((text) => typeof text === 'string');
}

function wordCell(value: unknown): value is WordCell {
  return record(value) && positive(value.column) && positive(value.span) && value.span <= 16_384
    && typeof value.text === 'string';
}

function wordBlock(value: unknown): value is WordParagraph | WordTable {
  if (!record(value)) return false;
  if ('paragraph' in value) return positive(value.paragraph)
    && typeof value.heading === 'boolean' && typeof value.text === 'string';
  return positive(value.table) && Array.isArray(value.rows)
    && value.rows.every((row) => Array.isArray(row) && row.every(wordCell));
}

function isOfficePreview(value: unknown): value is OfficePreview {
  if (!record(value)) return false;
  if ('blocks' in value) return typeof value.truncated === 'boolean'
    && Array.isArray(value.blocks) && value.blocks.every(wordBlock);
  return stringRow(value.sheets) && typeof value.sheet === 'string' && value.sheets.includes(value.sheet)
    && positive(value.row) && positive(value.column) && positive(value.last_row) && positive(value.last_column)
    && value.row <= value.last_row && value.column <= value.last_column
    && Array.isArray(value.rows) && value.rows.length > 0 && value.rows.length <= 60
    && value.rows.every((row) => stringRow(row) && row.length > 0 && row.length <= 20);
}

async function readPreview(path: string, signal: AbortSignal) {
  const response = await fetch(path, { signal, cache: 'no-store', redirect: 'error' });
  signal.throwIfAborted();
  if (response.status !== 200) throw new HttpError(response.status);
  return response;
}

export async function getOfficePreview(
  runId: string, documentId: string, query: URLSearchParams, signal: AbortSignal,
): Promise<OfficePreview> {
  const result = await readPreview(documentUrl(runId, documentId) + '/preview?' + query, signal);
  const value: unknown = await result.json();
  signal.throwIfAborted();
  if (!isOfficePreview(value)) throw new InvalidSourceResponseError();
  return value;
}

export async function getPdfPage(runId: string, documentId: string, page: number, signal: AbortSignal) {
  const response = await readPreview(documentUrl(runId, documentId) + '/page-preview?page=' + page, signal);
  const pages = Number(response.headers.get('X-Document-Pages'));
  if (!positive(pages) || pages < page || response.headers.get('Content-Type') !== 'image/png') {
    throw new InvalidSourceResponseError();
  }
  const image = await response.blob();
  signal.throwIfAborted();
  if (!image.size) throw new InvalidSourceResponseError();
  return { image, pages };
}