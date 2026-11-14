export interface PageAddress {
  page: number;
  table_row?: number | null;
  table_column?: number | null;
  bbox?: number[] | null;
  line?: number | null;
  fragment_id?: string | null;
}

interface SheetAddress {
  sheet: string;
  range: string;
}

interface ParagraphAddress {
  kind: 'paragraph';
  paragraph: number;
}

interface TableCellAddress {
  kind: 'table_cell';
  table: number;
  row: number;
  cell: number;
}

export type SourceAddress = PageAddress | SheetAddress | ParagraphAddress | TableCellAddress;

export function formatLocation(locator: SourceAddress) {
  if ('sheet' in locator) return `Лист «${locator.sheet}», ${locator.range}`;
  if ('paragraph' in locator) return `Абзац ${locator.paragraph}`;
  if ('table' in locator) return `Таблица ${locator.table}, строка ${locator.row}, ячейка ${locator.cell}`;

  const parts = [`Страница ${locator.page}`];
  if (locator.table_row != null && locator.table_column != null) {
    parts.push(`строка ${locator.table_row}`, `столбец ${locator.table_column}`);
  } else if (locator.line != null) {
    parts.push(`строка ${locator.line}`);
  }
  if (locator.fragment_id != null) parts.push(`фрагмент ${locator.fragment_id}`);
  return parts.join(', ');
}

function isIndex(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

function isText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function isBox(value: unknown): value is [number, number, number, number] {
  return Array.isArray(value) && value.length === 4
    && value.every((coordinate: unknown) => typeof coordinate === 'number'
      && coordinate >= 0 && coordinate <= 1)
    && value[0] < value[2] && value[1] < value[3];
}

function isSheetRange(value: unknown): value is string {
  if (!isText(value)) return false;
  const bounds = /^([A-Z]{1,3})([1-9][0-9]{0,6})(?::([A-Z]{1,3})([1-9][0-9]{0,6}))?(?![\s\S])/.exec(value);
  if (!bounds) return false;
  const [, firstColumn, firstRow, lastColumn = firstColumn, lastRow = firstRow] = bounds;
  const columnNumber = (column: string) =>
    Array.from(column).reduce((index, char) => index * 26 + char.charCodeAt(0) - 64, 0);
  return columnNumber(firstColumn) <= columnNumber(lastColumn) && columnNumber(lastColumn) <= 16_384
    && Number(firstRow) <= Number(lastRow) && Number(lastRow) <= 1_048_576;
}

export function isSourceLocator(locator: unknown): locator is SourceAddress {
  if (typeof locator !== 'object' || locator === null || Array.isArray(locator) || !('kind' in locator)) {
    return false;
  }
  const fields = locator as Record<string, unknown>;
  switch (fields.kind) {
    case 'page': {
      const { page, bbox, line, table_row: row, table_column: column, fragment_id: fragment } = fields;
      return isIndex(page) && (bbox == null || isBox(bbox)) && (line == null || isIndex(line))
        && (row == null ? column == null : isIndex(row) && isIndex(column))
        && (fragment == null || isText(fragment))
        && (bbox != null || line != null || row != null || fragment != null);
    }
    case 'sheet':
      return isText(fields.sheet) && isSheetRange(fields.range);
    case 'paragraph':
      return isIndex(fields.paragraph);
    case 'table_cell':
      return isIndex(fields.table) && isIndex(fields.row) && isIndex(fields.cell);
    default:
      return false;
  }
}
