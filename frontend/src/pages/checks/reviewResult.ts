import type { SourceAddress } from '../../shared/lib/sourceLocation';

export { formatLocation } from '../../shared/lib/sourceLocation';

interface SourceEvidence {
  id: string;
  document_id: string;
  locator: SourceAddress;
  raw_value: string | null;
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
  status: string;
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
export interface ReviewResult {
  scope: { contract_number: string; period_start: string; period_end: string };
  documents: ReviewDocument[];
  evidence: SourceEvidence[];
  rows: ReviewRow[];
  summary: {
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
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0');
  return decimals === undefined ? grouped : `${grouped},${decimals}`;
}
