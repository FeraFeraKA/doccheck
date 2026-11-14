import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

test('a PNG fragment received on the rule tab is centered once when shown', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 600 });
  const id = 'delayed-source-context';
  const path = `**/api/v0/runs/${id}`;
  const evidence = { ...example.result.evidence[0], locator: { kind: 'page', page: 1, bbox: [.2, .87, .5, .91] } };
  await page.route(path, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route(`${path}/findings`, (route) => route.fulfill({ json: {
    ...example.result, run_id: id,
    documents: example.result.documents.map((item) => item.id === 'report'
      ? { ...item, format: 'png', name: 'synthetic-report.png' } : item),
    evidence: example.result.evidence.map((item) => item.id === evidence.id ? evidence : item),
  } }));
  const png = readFileSync(new URL('../../../docs/synthetic/nrt-89/inputs/12_communication.png', import.meta.url));
  let originals = 0;
  let fragments = 0;
  let release: () => void = () => {};
  const delayed = new Promise<void>((resolve) => { release = resolve; });
  await page.route(`${path}/documents/report`, (route) => {
    originals += 1;
    return route.fulfill({ body: png, contentType: 'application/octet-stream' });
  });
  await page.route(`${path}/documents/report/fragments?evidence_id=${evidence.id}`, async (route) => {
    fragments += 1;
    await delayed;
    await route.fulfill({ json: evidence });
  });

  await page.goto('/checks/' + id);
  await page.getByRole('button', { name: 'Просмотреть источник' }).click();
  const drawer = page.getByLabel('Источник документа', { exact: true }).and(page.locator('.source-workspace-panel[open]'));
  const image = drawer.getByRole('img', { name: 'synthetic-report.png' });
  await drawer.getByRole('button', { name: 'Увеличить масштаб' }).click();
  const original = await image.getAttribute('src');
  const originalRequestCount = originals;
  const fragmentRequestCount = fragments;
  const source = drawer.getByRole('tab', { name: 'Источник' });
  const rule = drawer.getByRole('tab', { name: 'Правило проверки' });
  await rule.click();
  await expect(rule).toHaveAttribute('aria-selected', 'true');
  release();
  const mark = drawer.locator('.source-viewer-highlight');
  await expect(mark).toHaveCount(1);
  await expect(mark).toBeHidden();
  await source.click();
  await expect(mark).toBeInViewport({ ratio: 1 });
  await expect(drawer.getByText('125%', { exact: true })).toBeVisible();
  await expect(image).toHaveAttribute('src', original ?? '');
  const viewport = drawer.getByRole('region', { name: 'Просмотр документа: synthetic-report.png' });
  await viewport.evaluate((element) => { element.scrollTop = 0; });
  await expect(mark).not.toBeInViewport();
  await rule.click();
  await source.click();
  expect(await viewport.evaluate((element) => element.scrollTop)).toBe(0);
  await expect(mark).not.toBeInViewport();
  expect([originals, fragments]).toEqual([originalRequestCount, fragmentRequestCount]);
});

for (const width of [390, 768]) {
  test(`source context keeps the drawer and document mounted at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const id = 'source-context';
    const path = `**/api/v0/runs/${id}`;
    const first = example.result.evidence[0];
    const second = { ...first, id: 'report-alt', locator: { kind: 'page', page: 1, bbox: [.2, .72, .5, .8] } };
    await page.route(path, (route) => route.fulfill({ json: {
      run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null,
      progress: { processed_documents: 4, total_documents: 4 },
    } }));
    await page.route(`${path}/findings`, (route) => route.fulfill({ json: {
      ...example.result, run_id: id,
      documents: example.result.documents.map((item) => item.id === 'report'
        ? { ...item, format: 'png', name: 'synthetic-report.png' } : item),
      rows: example.result.rows.map((item, i) => i === 0
        ? { ...item, reported_evidence_refs: [first.id, second.id] } : item),
      evidence: [first, second, ...example.result.evidence.slice(1)],
    } }));
    const png = readFileSync(new URL('../../../docs/synthetic/nrt-89/inputs/12_communication.png', import.meta.url));
    const originals: string[] = [];
    await page.route(`${path}/documents/report`, (route) => {
      originals.push('report');
      return route.fulfill({ body: png, contentType: 'application/octet-stream' });
    });
    await page.route(`${path}/documents/ledger`, (route) => {
      originals.push('ledger');
      return route.fulfill({ body: 'Synthetic XLSX transport', contentType: 'application/octet-stream' });
    });
    const fragments: string[] = [];
    await page.route(`${path}/documents/*/fragments?*`, (route) => {
      const selected = new URL(route.request().url()).searchParams.get('evidence_id');
      if (!selected) throw new Error('Missing evidence id');
      fragments.push(selected);
      return route.fulfill({ json: selected === second.id ? second : example.result.evidence.find(({ id }) => id === selected) });
    });

    await page.goto('/checks/' + id);
    const opener = page.getByRole('button', { name: 'Просмотреть источник' });
    await opener.click();
    const drawer = page.getByLabel('Источник документа', { exact: true }).and(page.locator('.source-workspace-panel[open]'));
    await drawer.getByRole('button', { name: 'Развернуть источник на весь экран' }).click();
    await drawer.getByRole('button', { name: 'Увеличить масштаб' }).click();
    const source = drawer.getByRole('tab', { name: 'Источник' });
    const rule = drawer.getByRole('tab', { name: 'Правило проверки' });
    await source.press('ArrowRight');
    await expect(rule).toBeFocused();
    await expect(drawer.getByText('demo-sum/1', { exact: true })).toBeVisible();
    await rule.press('Alt+ArrowDown');
    await expect(rule).toBeFocused();
    await rule.press('Home');
    await expect(source).toBeFocused();
    await expect(drawer.getByText('125%', { exact: true })).toBeVisible();

    const image = drawer.getByRole('img', { name: 'synthetic-report.png' });
    const blob = await image.getAttribute('src');
    const originalCount = originals.length;
    const picker = drawer.getByRole('combobox', { name: 'Доказательство' });
    await drawer.getByRole('button', { name: 'Следующий источник' }).press('Enter');
    await expect(picker).toHaveValue('report-alt');
    await expect(drawer.locator('.source-viewer-highlight')).toHaveAttribute('style', /top: 72%/);
    await expect(drawer.getByText('125%', { exact: true })).toBeVisible();
    await expect(image).toHaveAttribute('src', blob ?? '');
    await expect(drawer).toHaveAttribute('data-fullscreen', 'true');
    expect(originals).toHaveLength(originalCount);
    expect(fragments).toContain('report-alt');
    await drawer.getByRole('button', { name: 'Предыдущий источник' }).press('Enter');
    await expect(picker).toHaveValue(first.id);
    await expect(drawer.locator('.source-viewer-highlight')).toHaveAttribute('style', /top: 40%/);

    await picker.selectOption('amount-1');
    await expect(drawer.getByText('Лист «Синтетика», C6', { exact: true })).toBeVisible();
    expect(originals).toContain('ledger');
    await expect(drawer).toHaveAttribute('data-fullscreen', 'true');
    await page.keyboard.press('Escape');
    await expect(opener).toBeFocused();
    await expect(page.getByRole('combobox', { name: 'Доказательство' })).toHaveValue('amount-1');
  });
}
