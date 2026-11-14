import { HttpError } from '../../shared/api/requestJson';
import { documentParseStatuses } from './reviewResult';
import type { DocumentParseStatus, ReviewResult, RubCoverage } from './reviewResult';

type Dict = Record<string, unknown>;
type Read<T> = (value: unknown) => T;
type Address = ReviewResult['evidence'][number]['locator'];
type Row = ReviewResult['rows'][number];

type FindingsErrorCode = 'run_not_found' | 'result_pending' | 'run_failed' | 'service_unavailable';

export class FindingsHttpError extends HttpError {
  constructor(status: number, readonly code?: FindingsErrorCode) {
    super(status);
    this.name = 'FindingsHttpError';
  }
}

export class InvalidFindingsResponse extends Error {
  constructor() {
    super('API вернул некорректный результат сверки.');
    this.name = 'InvalidFindingsResponse';
  }
}

export interface RunFindings {
  runId: string;
  synthetic: boolean;
  result: ReviewResult;
}

function isRecord(value: unknown): value is Dict {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function record(value: unknown): Dict {
  if (!isRecord(value)) throw new InvalidFindingsResponse();
  return value;
}

function text(value: unknown): string {
  if (typeof value !== 'string' || value.length === 0) throw new InvalidFindingsResponse();
  return value;
}

function choice<T extends string>(value: unknown, choices: readonly T[]): T {
  const item = choices.find((candidate) => candidate === value);
  if (item === undefined) throw new InvalidFindingsResponse();
  return item;
}

function list<T>(value: unknown, read: Read<T>): T[] {
  if (!Array.isArray(value)) throw new InvalidFindingsResponse();
  return value.map(read);
}

function integer(value: unknown, minimum: number): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum) {
    throw new InvalidFindingsResponse();
  }
  return value;
}

function date(value: unknown): string {
  const item = text(value);
  if (!/^\d{4}-\d{2}-\d{2}(?![\s\S])/.test(item)) throw new InvalidFindingsResponse();
  return item;
}

function decimal(value: unknown, unit: string): string {
  const item = text(value);
  const pattern = unit === 'RUB'
    ? /^(?!-0+\.00(?![\s\S]))-?\d+\.\d{2}(?![\s\S])/
    : /^-?\d+(?:\.\d+)?(?![\s\S])/;
  if (!pattern.test(item)) throw new InvalidFindingsResponse();
  return item;
}

function nullableDecimal(value: unknown, unit: string): string | null {
  return value === null ? null : decimal(value, unit);
}

function optionalIndex(value: unknown): number | null {
  return value == null ? null : integer(value, 1);
}

function optionalBox(value: unknown): number[] | null {
  if (value == null) return null;
  const box = list(value, (item) => {
    if (typeof item !== 'number' || !Number.isFinite(item) || item < 0 || item > 1) {
      throw new InvalidFindingsResponse();
    }
    return item;
  });
  if (box.length !== 4 || box[0] >= box[2] || box[1] >= box[3]) throw new InvalidFindingsResponse();
  return box;
}

function address(value: unknown): Address {
  const item = record(value);
  switch (item.kind) {
    case 'sheet':
      return { sheet: text(item.sheet), range: text(item.range) };
    case 'paragraph':
      return { kind: item.kind, paragraph: integer(item.paragraph, 1) };
    case 'table_cell':
      return { kind: item.kind, table: integer(item.table, 1), row: integer(item.row, 1), cell: integer(item.cell, 1) };
    case 'page': {
      const bbox = optionalBox(item.bbox);
      const line = optionalIndex(item.line);
      const table_row = optionalIndex(item.table_row);
      const table_column = optionalIndex(item.table_column);
      const fragment_id = item.fragment_id == null ? null : text(item.fragment_id);
      if ((table_row === null) !== (table_column === null)
        || (bbox === null && line === null && table_row === null && fragment_id === null)) {
        throw new InvalidFindingsResponse();
      }
      return { page: integer(item.page, 1), bbox, line, table_row, table_column, fragment_id };
    }
    default:
      throw new InvalidFindingsResponse();
  }
}

function issue(value: unknown) {
  const item = record(value);
  return { id: text(item.id), code: text(item.code), message: text(item.message) };
}

function primaryIssue(value: unknown): ReviewResult['summary']['primary_issues'][number] {
  const item = record(value);
  return {
    ...issue(item),
    evidence_refs: list(item.evidence_refs, text),
    file_error_refs: item.file_error_refs === undefined ? [] : list(item.file_error_refs, text),
  };
}

export function readDocumentParseStatus(value: unknown): DocumentParseStatus | undefined {
  return value === undefined ? undefined : choice(value, documentParseStatuses);
}

function document(value: unknown): ReviewResult['documents'][number] {
  const item = record(value);
  const decision = record(item.decision);
  return {
    id: text(item.id),
    name: text(item.name),
    format: item.format === null ? null : choice(item.format, ['pdf', 'png', 'xlsx', 'docx']),
    role: choice(item.role, ['report', 'support']),
    parse_status: readDocumentParseStatus(item.parse_status),
    decision: {
      state: choice(decision.state, ['include', 'exclude', 'needs_review', 'parse_error']),
      reason_code: text(decision.reason_code),
      message: text(decision.message),
      evidence_refs: list(decision.evidence_refs, text),
    },
    errors: list(item.errors, issue),
  };
}

function calculation(value: unknown, unit: string): Row['calculation'] {
  const item = record(value);
  if (item.operation != null && item.operation !== 'sum') throw new InvalidFindingsResponse();

  return {
    policy_id: text(item.policy_id),
    operation: item.operation ?? null,
    formula: text(item.formula),
    components: list(item.components, (entry) => {
      const component = record(entry);
      return {
        amount: decimal(component.amount, unit),
        amount_refs: list(component.amount_refs, text),
        contract_refs: list(component.contract_refs, text),
        period_refs: list(component.period_refs, text),
        article_refs: list(component.article_refs, text),
        identity_refs: component.identity_refs === undefined ? [] : list(component.identity_refs, text),
        relation_reason: text(component.relation_reason),
      };
    }),
  };
}

function row(value: unknown): Row {
  const item = record(value);
  const unit = text(item.unit);
  const completeness = record(item.completeness);
  return {
    id: text(item.id),
    label: text(item.label),
    unit,
    status: choice(item.status, ['verified', 'discrepancy', 'unverified']),
    reported_value: nullableDecimal(item.reported_value, unit),
    expected_value: nullableDecimal(item.expected_value, unit),
    observed_evidence_sum: nullableDecimal(item.observed_evidence_sum, unit),
    delta: nullableDecimal(item.delta, unit),
    reported_evidence_refs: list(item.reported_evidence_refs, text),
    reasons: list(item.reasons, (value) => {
      const reason = record(value);
      return { code: text(reason.code), message: text(reason.message), evidence_refs: list(reason.evidence_refs, text) };
    }),
    completeness: {
      state: choice(completeness.state, ['complete', 'incomplete', 'unknown']),
      basis: choice(completeness.basis, ['manifest', 'user_declaration', 'dataset_fixture', 'none']),
      reason: text(completeness.reason),
      evidence_refs: list(completeness.evidence_refs, text),
    },
    calculation: calculation(item.calculation, unit),
    root_issue_id: item.root_issue_id === null ? null : text(item.root_issue_id),
  };
}

export function readRubCoverage(value: unknown): ReviewResult['summary']['rubCoverage'] {
  if (value == null) return undefined;
  const item = record(value);
  const shareValues = item.shares == null ? null : record(item.shares);
  const shares: NonNullable<RubCoverage['shares']> = {};
  if (shareValues) {
    for (const status of ['verified', 'discrepancy', 'unverified'] as const) {
      if (shareValues[status] === undefined) continue;
      const share = decimal(shareValues[status], '%');
      if (Number(share) < 0 || Number(share) > 100) throw new InvalidFindingsResponse();
      shares[status] = share;
    }
  }
  return {
    total: decimal(item.total, 'RUB'),
    verified: nullableDecimal(item.verified, 'RUB'),
    discrepancy: nullableDecimal(item.discrepancy, 'RUB'),
    unverified: nullableDecimal(item.unverified, 'RUB'),
    shares: shareValues ? shares : null,
  };
}

function decodeFindings(value: unknown, runId: string): RunFindings {
  const findings = record(value);
  if (findings.schema_version !== 'doccheck-check-result/1'
    || findings.run_id !== runId || typeof findings.synthetic !== 'boolean') {
    throw new InvalidFindingsResponse();
  }

  const scope = record(findings.scope);
  const summary = record(findings.summary);
  const counts = record(summary.counts);
  return {
    runId,
    synthetic: findings.synthetic,
    result: {
      ...(findings.report_number == null ? {} : { reportNumber: text(findings.report_number) }),
      scope: {
        contract_number: text(scope.contract_number),
        period_start: date(scope.period_start),
        period_end: date(scope.period_end),
      },
      documents: list(findings.documents, document),
      evidence: list(findings.evidence, (value) => {
        const item = record(value);
        return {
          id: text(item.id),
          document_id: text(item.document_id),
          locator: address(item.locator),
          raw_value: text(item.raw_value),
        };
      }),
      rows: list(findings.rows, row),
      summary: {
        ...(summary.rub_coverage == null ? {} : { rubCoverage: readRubCoverage(summary.rub_coverage) }),
        counts: {
          verified: integer(counts.verified, 0),
          discrepancy: integer(counts.discrepancy, 0),
          unverified: integer(counts.unverified, 0),
        },
        conclusion: text(summary.conclusion),
        primary_issues: list(summary.primary_issues, primaryIssue),
      },
    },
  };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch (error) {
    if (error instanceof SyntaxError) return null;
    throw error;
  }
}

function findingsErrorCode(status: number, value: unknown): FindingsErrorCode | undefined {
  if (!isRecord(value)) return undefined;
  const code = value.code;
  if (status === 404 && code === 'run_not_found') return code;
  if (status === 409 && (code === 'result_pending' || code === 'run_failed')) return code;
  if (status === 503 && code === 'service_unavailable') return code;
  return undefined;
}

export async function loadFindings(runId: string, signal?: AbortSignal): Promise<RunFindings> {
  if (!/^[A-Za-z0-9_-]+(?![\s\S])/.test(runId)) throw new TypeError('Некорректный ID задания.');

  const response = await fetch(`/api/v0/runs/${runId}/findings`, { signal, redirect: 'error' });
  if (!response.ok) {
    throw new FindingsHttpError(response.status, findingsErrorCode(response.status, await readJson(response)));
  }
  if (response.status !== 200) throw new InvalidFindingsResponse();
  return decodeFindings(await readJson(response), runId);
}
