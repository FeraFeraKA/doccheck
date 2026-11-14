import type { SourceAddress, PageAddress } from '../../shared/lib/sourceLocation';
export type { PageAddress };

export { formatLocation } from '../../shared/lib/sourceLocation';

interface SourceEvidence {
  kind?: string;
  id: string;
  document_id: string;
  locator: SourceAddress;
  raw_value: string | null;
  normalized_value?: unknown;
}

interface ReviewIssue {
  id: string;
  code: string;
  message: string;
}

interface PrimaryReviewIssue extends ReviewIssue {
  evidence_refs: string[];
  file_error_refs?: string[];
}

export const documentParseStatuses = ['pending', 'parsed', 'partial', 'error'] as const;
export type DocumentParseStatus = typeof documentParseStatuses[number];

interface ReviewDocument {
  id: string;
  name: string;
  format?: string | null;
  parse_status?: DocumentParseStatus;
  role: string;
  decision: { state: string; reason_code: string; message: string; evidence_refs: string[] };
  errors: ReviewIssue[];
}

interface ReviewComponent {
  amount: string;
  amount_refs: string[];
  contract_refs: string[];
  period_refs: string[];
  article_refs: string[];
  identity_refs?: string[];
  relation_reason: string;
}

interface ReviewCalculation {
  policy_id: string;
  formula: string;
  operation?: string | null;
  components: ReviewComponent[];
}

interface ReviewRow {
  id: string;
  label: string;
  status: ResultStatus;
  unit: string;
  reported_value: string | null;
  expected_value: string | null;
  observed_evidence_sum: string | null;
  delta: string | null;
  reported_evidence_refs: string[];
  reasons: { code: string; message: string; evidence_refs: string[] }[];
  completeness: { state: string; basis: string; reason: string; evidence_refs: string[] };
  calculation: ReviewCalculation;
  root_issue_id: string | null;
}

// Fields used by the transferred screens. The API client's decoder validates
// this projection before handing a server result to a caller.
type ResultStatus = 'verified' | 'discrepancy' | 'unverified';

const defaultExplanations: Record<ResultStatus, string> = {
  verified: 'Значение подтверждено документами.',
  discrepancy: 'Значение в КФЗ отличается от подтверждённого документами.',
  unverified: 'Недостаточно подтверждений для проверки показателя.',
};
export interface RubCoverage extends Record<ResultStatus, string | null> {
  total: string;
  shares: Partial<Record<ResultStatus, string>> | null;
}

export interface ReviewResult {
  reportNumber?: string;
  scope: {
    contract_number: string;
    period_start: string;
    period_end: string;
    report_document_id?: string;
    report_row_locator?: SourceAddress | null;
  };
  documents: ReviewDocument[];
  evidence: SourceEvidence[];
  rows: ReviewRow[];
  summary: {
    rubCoverage?: RubCoverage;
    counts: { verified: number; discrepancy: number; unverified: number };
    conclusion: string;
    primary_issues: PrimaryReviewIssue[];
  };
}

export const statusLabels: Record<string, string> = {
  verified: 'Подтверждён',
  discrepancy: 'Расхождение',
  unverified: 'Не проверен',
};

export function formatDecimal(value: string | null) {
  if (value === null) return '—';
  const [integer, decimals] = value.split('.');
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, '\u202f').replace(/^-/, '−');
  return decimals === undefined ? grouped : `${grouped},${decimals}`;
}

export function formatMeasure(value: string | null, unit: string) {
  return value === null ? '—' : `${formatDecimal(value)} ${unit === 'RUB' ? '₽' : unit}`;
}

export function rowExplanation(row: ReviewRow, issue?: ReviewIssue) {
  const explanation = row.reasons.find(({ message }) => message.trim())?.message;
  return (explanation ?? issue?.message.trim()) || (row.status === 'unverified' && row.completeness.reason.trim()
    ? row.completeness.reason : defaultExplanations[row.status]);
}
