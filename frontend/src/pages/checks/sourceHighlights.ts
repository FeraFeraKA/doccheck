import type { SourceAddress } from '../../shared/lib/sourceLocation';

export type SourceTone = 'discrepancy' | 'unverified' | 'verified';

export interface SourceHighlight {
  locator: SourceAddress;
  tone: SourceTone;
}

export type SourceBox = readonly [number, number, number, number];

export interface SourceImageHighlight {
  box: SourceBox;
  tone: SourceTone;
}

const priority: Record<SourceTone, number> = { discrepancy: 3, unverified: 2, verified: 1 };

export function strongestTone(current: SourceTone | undefined, next: SourceTone | undefined) {
  return next && (!current || priority[next] > priority[current]) ? next : current;
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
  for (const { locator, tone } of highlights) {
    if (!('page' in locator)) continue;
    const box = sourceBox(locator.bbox);
    if (!box) continue;
    const markers = pages.get(locator.page) ?? new Map<string, SourceImageHighlight>();
    const key = box.join(',');
    const preferred = strongestTone(markers.get(key)?.tone, tone);
    if (preferred) markers.set(key, { box, tone: preferred });
    pages.set(locator.page, markers);
  }
  return new Map([...pages].map(([page, markers]) => [
    page, [...markers.values()].sort((first, second) => priority[first.tone] - priority[second.tone]),
  ]));
}
