import type fixture from '../../../../contracts/check-result.v1.synthetic.json';

type FixtureResult = typeof fixture.result;

interface PageAddress {
  page: number;
  table_row?: number;
  table_column?: number;
  bbox?: number[] | null;
}

interface SheetAddress {
  sheet: string;
  range: string;
}

type SourceAddress = PageAddress | SheetAddress;

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
  if ('sheet' in locator) return 'Лист «' + locator.sheet + '», ' + locator.range;
  if (locator.table_row !== undefined) {
    return 'Страница ' + locator.page + ', строка ' + locator.table_row + ', столбец ' + locator.table_column;
  }
  return 'Страница ' + locator.page;
}
