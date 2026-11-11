/** View-only types. These are NOT the unavailable canonical CheckResult API schema. */
export type FindingStatus = 'verified' | 'discrepancy' | 'unverified';
export type RunStatus = 'queued' | 'processing' | 'completed_with_issues';
export type SourcePreview = {
  id: string;
  filename: string;
  previewUrl: string;
  originalUrl: string;
  amount: string;
  page: number;
  bbox: readonly [number, number, number, number];
};
export type Finding = {
  id: string;
  article: string;
  reported: string | null;
  expected: string | null;
  delta: string | null;
  status: FindingStatus;
  explanation: string;
  formula: string | null;
  sources: SourcePreview[];
};
export type DemoRun = {
  id: string;
  createdAt: string;
  status: RunStatus;
};

/** Format exact decimal strings without coercing money into floating point. */
export function money(value: string | null, signed = false): string {
  if (value === null) return '—';
  if (!/^-?\d+\.\d{2}$/.test(value)) throw new Error('Ожидалась точная десятичная строка');
  const negative = value.startsWith('-');
  const [whole, fraction] = value.replace(/^-/, '').split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0');
  const nonzero = /[1-9]/.test(whole + fraction);
  const sign = nonzero ? (negative ? '−' : signed ? '+' : '') : '';
  return `${sign}${grouped},${fraction}`;
}

export const statusLabels: Record<FindingStatus, string> = {
  verified: 'Подтверждено', discrepancy: 'Расхождение', unverified: 'Не проверено',
};

export function filterFindings(findings: Finding[], filter: FindingStatus | 'all') {
  return filter === 'all' ? findings : findings.filter((finding) => finding.status === filter);
}

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]!);
}
