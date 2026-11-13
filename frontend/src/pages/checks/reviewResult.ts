import type fixture from '../../../../contracts/check-result.v1.synthetic.json';

type FixtureResult = typeof fixture.result;

interface PageAddress {
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

type SourceAddress = PageAddress | SheetAddress | ParagraphAddress | TableCellAddress;

type SourceEvidence = Pick<FixtureResult['evidence'][number], 'id' | 'document_id'> & {
  locator: SourceAddress;
  raw_value: string | null;
};

type ReviewDocument = Pick<FixtureResult['documents'][number], 'id' | 'name' | 'role' | 'decision' | 'errors'>;

type ReviewRow = Pick<FixtureResult['rows'][number],
  'id' | 'label' | 'status' | 'reported_evidence_refs' | 'reasons' | 'completeness'> & {
  reported_value: string | null;
  expected_value: string | null;
  delta: string | null;
  calculation?: { formula: string } | null;
};

// This projection covers the existing displays. The API adapter will
// validate responses against the versioned contract before passing them here.
export interface ReviewResult {
  scope: Pick<FixtureResult['scope'], 'contract_number' | 'period_start' | 'period_end'>;
  documents: ReviewDocument[];
  evidence: SourceEvidence[];
  rows: ReviewRow[];
  summary: Pick<FixtureResult['summary'], 'counts' | 'conclusion' | 'primary_issues'>;
}

export const statusLabels: Record<string, string> = {
  verified: 'Подтверждён',
  discrepancy: 'Расхождение',
  unverified: 'Не проверен',
};

export function formatMoney(value: string | null) {
  if (value === null) return '—';
  const [integer, decimals] = value.split('.');
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0') + ',' + decimals;
}

export function formatLocation(locator: SourceAddress) {
  if ('sheet' in locator) return `Лист «${locator.sheet}», ${locator.range}`;
  if ('paragraph' in locator) return `Абзац ${locator.paragraph}`;
  if ('table' in locator) return `Таблица ${locator.table}, строка ${locator.row}, ячейка ${locator.cell}`;

  const page = `Страница ${locator.page}`;
  if (locator.table_row != null && locator.table_column != null) {
    return `${page}, строка ${locator.table_row}, столбец ${locator.table_column}`;
  }
  if (locator.line != null) return `${page}, строка ${locator.line}`;
  if (locator.fragment_id != null) return `${page}, фрагмент ${locator.fragment_id}`;
  return page;
}
