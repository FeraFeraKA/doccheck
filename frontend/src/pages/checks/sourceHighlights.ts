import type { CSSProperties } from 'react';
import type { SourceAddress } from '../../shared/lib/sourceLocation';
import type { ReviewResult } from './reviewResult';

export const sourceFields = [
  ['amount', 'Суммы и значения'],
  ['contract', 'Договоры'],
  ['period', 'Даты и периоды'],
  ['document_identity', 'Реквизиты документов'],
  ['article', 'Статьи затрат'],
  ['source', 'Фрагмент источника'],
] as const;

export type SourceField = typeof sourceFields[number][0];

export interface SourceHighlight {
  locator: SourceAddress;
  kind: SourceField;
}

export type SourceBox = readonly [number, number, number, number];

export interface SourceImageHighlight {
  box: SourceBox;
  kinds: Set<SourceField>;
}

export function sourceField(kind?: string): SourceField | undefined {
  if (kind === 'reported_value') return 'amount';
  return sourceFields.find(([field]) => field === kind && field !== 'source')?.[0];
}

export function evidenceFields(rows: ReviewResult['rows']) {
  const kinds = new Map<string, SourceField>();
  function add(refs: string[] | undefined, kind: SourceField) {
    for (const ref of refs ?? []) if (!kinds.has(ref)) kinds.set(ref, kind);
  }
  for (const row of rows) {
    add(row.reported_evidence_refs, 'amount');
    for (const component of row.calculation.components) {
      add(component.amount_refs, 'amount');
      add(component.contract_refs, 'contract');
      add(component.period_refs, 'period');
      add(component.article_refs, 'article');
      add(component.identity_refs, 'document_identity');
    }
  }
  return kinds;
}

export function isVisibleAddress(locator: SourceAddress, format: string | null) {
  if (format === 'pdf' || format === 'png') {
    return 'page' in locator && (format === 'pdf' || locator.page === 1) && Boolean(sourceBox(locator.bbox));
  }
  if (format === 'xlsx') return 'sheet' in locator;
  return format === 'docx' && ('paragraph' in locator || 'table' in locator);
}

export function sourceMark(kinds: ReadonlySet<SourceField> | undefined, selected?: SourceField) {
  if (!kinds?.size && !selected) return;
  const fields = sourceFields.filter(([field]) => kinds?.has(field) || field === selected).map(([field]) => field);
  if (fields.length === 0) return undefined;
  const colors = fields.map((field) => sourceColor(field)['--source-color']);
  // Different fields can share one cell or frame. Paint a single mark with a color segment for each.
  const segments = colors.map((color, index) =>
    `${color} ${index * 100 / colors.length}% ${(index + 1) * 100 / colors.length}%`);
  const stripe = segments.length > 1
    ? `linear-gradient(to right, ${segments.join(', ')})`
    : `linear-gradient(${colors[0]}, ${colors[0]})`;
  return {
    'data-source-field': fields.join(' '),
    'data-source-active': selected !== undefined ? 'true' : undefined,
    style: { ...sourceColor(selected ?? fields[0]), '--source-stripe': stripe } as CSSProperties,
  };
}

export function sourceColor(field: SourceField): CSSProperties & { '--source-color': string } {
  return { '--source-color': `var(--source-${field})` };
}

export function sourceBox(value: readonly number[] | null | undefined): SourceBox | undefined {
  if (value?.length !== 4) return;
  const [left, top, right, bottom] = value;
  if (left >= 0 && left < right && right <= 1 && top >= 0 && top < bottom && bottom <= 1) {
    return [left, top, right, bottom];
  }
}

export function pageHighlights(highlights: readonly SourceHighlight[]) {
  const pages = new Map<number, Map<string, SourceImageHighlight>>();
  for (const { locator, kind } of highlights) {
    if (!('page' in locator)) continue;
    const box = sourceBox(locator.bbox);
    if (!box) continue;
    const markers = pages.get(locator.page) ?? new Map<string, SourceImageHighlight>();
    const key = box.join(',');
    const known = markers.get(key);
    if (known) known.kinds.add(kind);
    else markers.set(key, { box, kinds: new Set([kind]) });
    pages.set(locator.page, markers);
  }
  return new Map([...pages].map(([page, markers]) => [
    page, [...markers.values()],
  ]));
}
