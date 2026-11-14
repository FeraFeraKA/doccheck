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
  await page.getByRole('button', { name: /^150,50\s*₽$/ }).click();
  const drawer = page.getByLabel('Источник документа', { exact: true }).and(page.locator('.source-workspace-panel[open]'));
  const image = drawer.getByRole('img', { name: 'synthetic-report.png' });
  await expect(drawer.getByRole('status').filter({ hasText: 'Загрузка документа' })).toHaveCount(1);
  await expect(image).toHaveCount(0);
  const source = drawer.getByRole('tab', { name: 'Источник' });
  const rule = drawer.getByRole('tab', { name: 'Правило проверки' });
  await rule.click();
  await expect(rule).toHaveAttribute('aria-selected', 'true');
  release();
  const mark = drawer.locator('.source-viewer-highlight');
  await expect(mark).toBeHidden();
  await source.click();
  await expect(mark).toBeInViewport({ ratio: 1 });
  const original = await image.getAttribute('src');
  const originalRequestCount = originals;
  const fragmentRequestCount = fragments;
  const viewport = drawer.getByRole('region', { name: 'Просмотр документа: synthetic-report.png' });
  await viewport.evaluate((element) => { element.scrollTop = 0; });
  await expect(mark).not.toBeInViewport();
  await rule.click();
  await source.click();
  expect(await viewport.evaluate((element) => element.scrollTop)).toBe(0);
  await expect(mark).not.toBeInViewport();
  await expect(image).toHaveAttribute('src', original ?? '');
  expect([originals, fragments]).toEqual([originalRequestCount, fragmentRequestCount]);
});

for (const width of [390, 768]) {
  test(`source context keeps the drawer and document mounted at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const id = 'source-context';
    const path = `**/api/v0/runs/${id}`;
    const first = example.result.evidence[0];
    const second = { ...first, id: 'report-contract', kind: 'contract', locator: { kind: 'page', page: 1, bbox: [.2, .72, .5, .8] } };
    const duplicate = { ...second, id: 'report-contract-copy' };
    await page.route(path, (route) => route.fulfill({ json: {
      run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null,
      progress: { processed_documents: 4, total_documents: 4 },
    } }));
    await page.route(`${path}/findings`, (route) => route.fulfill({ json: {
      ...example.result, run_id: id,
      documents: example.result.documents.map((item) => item.id === 'report'
        ? { ...item, format: 'png', name: 'synthetic-report.png' } : item),
      rows: example.result.rows.map((item, i) => i === 0
        ? { ...item, reported_evidence_refs: [first.id] } : item),
      evidence: [first, second, duplicate, ...example.result.evidence.slice(1)],
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
    await page.route(`${path}/documents/ledger/preview?*`, (route) => route.fulfill({ json: {
      sheets: ['Синтетика'], sheet: 'Синтетика', row: 1, column: 1, last_row: 7, last_column: 3,
      rows: Array.from({ length: 7 }, () => ['', '', '']),
    } }));
    const fragments: string[] = [];
    await page.route(`${path}/documents/*/fragments?*`, (route) => {
      const selected = new URL(route.request().url()).searchParams.get('evidence_id');
      if (!selected) throw new Error('Missing evidence id');
      fragments.push(selected);
      return route.fulfill({ json: example.result.evidence.find(({ id }) => id === selected) });
    });

    await page.goto('/checks/' + id);
    const opener = page.getByRole('button', { name: /^150,50\s*₽$/ });
    await opener.click();
    const drawer = page.getByLabel('Источник документа', { exact: true }).and(page.locator('.source-workspace-panel[open]'));
    await drawer.getByRole('button', { name: 'Развернуть источник на весь экран' }).click();
    await drawer.getByRole('button', { name: 'Увеличить масштаб' }).click();
    const source = drawer.getByRole('tab', { name: 'Источник' });
    const rule = drawer.getByRole('tab', { name: 'Правило проверки' });
    await source.press('ArrowRight');
    await expect(rule).toBeFocused();
    await expect(drawer.getByText(example.result.rows[0].calculation.formula, { exact: true })).toBeVisible();
    await rule.press('Alt+ArrowDown');
    await expect(rule).toBeFocused();
    await rule.press('Home');
    await expect(source).toBeFocused();
    await expect(drawer.getByText('125%', { exact: true })).toBeVisible();

    const image = drawer.getByRole('img', { name: 'synthetic-report.png' });
    const blob = await image.getAttribute('src');
    const originalCount = originals.length;
    const fragmentCount = fragments.length;
    const docPicker = drawer.getByRole('combobox', { name: 'Документы комплекта' });
    await expect(drawer.getByRole('combobox')).toHaveCount(1);
    expect((await drawer.getByRole('button', { name: 'Увеличить масштаб' }).boundingBox())?.width).toBeGreaterThanOrEqual(36);
    await expect(drawer.locator('.source-viewer-highlight')).toHaveCount(2);
    const contract = drawer.getByRole('checkbox', { name: 'Договоры' });
    const contractMark = drawer.locator('.source-viewer-highlight[data-source-field="contract"]');
    await expect(contractMark).toHaveAttribute('style', /top: 72%/);
    await contract.uncheck();
    await expect(contractMark).toHaveCount(0);
    await expect(drawer.locator('.source-viewer-highlight[data-source-active="true"]')).toHaveAttribute('style', /top: 40%/);
    await expect(drawer.getByText('125%', { exact: true })).toBeVisible();
    await expect(image).toHaveAttribute('src', blob ?? '');
    await expect(drawer).toHaveAttribute('data-fullscreen', 'true');
    expect([...new Set(originals)]).toEqual(['report']);
    expect([...new Set(fragments)]).toEqual([first.id]);
    expect(originals).toHaveLength(originalCount);
    expect(fragments).toHaveLength(fragmentCount);

    await docPicker.selectOption('ledger');
    await expect(docPicker).toHaveValue('ledger');
    await expect(rule).toBeVisible();
    await rule.click();
    await expect(drawer.getByText(example.result.rows[0].calculation.formula, { exact: true })).toBeVisible();
    await source.click();
    await expect(drawer.getByRole('link', { name: 'Скачать оригинал' })).toBeVisible();
    expect(originals).toContain('ledger');
    await docPicker.selectOption('report');
    await expect(contract).not.toBeChecked();
    await expect(drawer.getByText('125%', { exact: true })).toBeVisible();
    await expect(drawer).toHaveAttribute('data-fullscreen', 'true');
    const zoomIn = drawer.getByRole('button', { name: 'Увеличить масштаб' });
    await zoomIn.click();
    await zoomIn.click();
    await zoomIn.click();
    await expect(drawer.getByLabel('Масштаб документа')).toHaveText('200%');
    await page.keyboard.press('Escape');
    await expect(opener).toBeFocused();
    await expect(drawer).toHaveCount(0);
  });
}

test('the document eye has no side rail and the workbook opens at the first row', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  const id = 'document-overview';
  const base = `**/api/v0/runs/${id}`;
  const ledger = example.result.documents.find(({ id }) => id === 'ledger');
  await page.route(base, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route(`${base}/findings`, (route) => route.fulfill({ json: { ...example.result, run_id: id } }));
  await page.route(`${base}/documents/**`, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/preview')) {
      const row = Number(url.searchParams.get('row') ?? '1');
      const sheet = url.searchParams.get('sheet') ?? 'Синтетика';
      return route.fulfill({ json: {
        sheets: ['Синтетика', 'Дополнения'], sheet, row, column: 1, last_row: 8, last_column: 3,
        rows: Array.from({ length: 9 - row }, (_, i) => {
          const index = i + row;
          return index === 1 ? ['Ведомость', 'Описание', 'Сумма']
            : ['', '', index === 6 || index === 7 ? '60.25' : ''];
        }),
      } });
    }
    if (url.pathname.endsWith('/page-preview')) return route.fulfill({ status: 404 });
    return route.fulfill({ contentType: 'application/octet-stream', body: 'synthetic transport fixture' });
  });

  await page.goto(`/checks/${id}`);
  const launcher = page.getByRole('button', { name: 'Открыть просмотр документов' });
  const panel = page.getByRole('region', { name: 'Источник документа', exact: true });
  await expect(panel).toHaveCount(0);
  await expect(launcher).toHaveCSS('position', 'absolute');
  await expect(page.locator('.app-content')).toHaveCSS('margin-right', '0px');
  await launcher.press('Enter');
  const documents = panel.getByRole('combobox', { name: 'Документы комплекта' });
  await expect(documents).toHaveValue('report');
  await documents.selectOption('ledger');
  const addresses = panel.getByRole('combobox', { name: 'Адрес доказательства' });
  await expect(addresses).toHaveCount(0);
  await expect(panel.getByRole('cell', { name: 'Ведомость' })).toBeVisible();
  await expect(panel.locator('td[data-source-field~="amount"]')).toHaveCount(2);
  await expect(panel.locator('[data-source-active="true"]')).toHaveCount(0);
  await panel.getByRole('checkbox', { name: 'Суммы и значения' }).uncheck();
  await expect(panel.locator('td[data-source-field~="amount"]')).toHaveCount(0);
  await expect(panel.locator('td[data-source-field="contract"]')).toHaveCount(1);
  await expect(panel.getByRole('link', { name: 'Скачать оригинал' })).toHaveAttribute('download', ledger?.name ?? '');
  await expect(panel.getByRole('cell', { name: 'Ведомость' })).toBeVisible();
  await expect(panel.locator('[data-source-active="true"]')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(launcher).toBeFocused();
});
