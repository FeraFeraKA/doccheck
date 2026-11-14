import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

for (const [width, height] of [[1440, 1100], [768, 844], [390, 600]]) {
  test(`the compact PNG drawer uses its available space and locates evidence at ${width}×${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    const id = 'png-preview';
    const evidence = { ...example.result.evidence[0], locator: { kind: 'page', page: 1, bbox: [.2, .72, .5, .8] } };
    const documents = example.result.documents.map((file) => file.id === 'report'
      ? { ...file, format: 'png', name: 'synthetic-report.png' }
      : file);
    await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
      run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null,
      progress: { processed_documents: 4, total_documents: 4 },
    } }));
    await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({ json: {
      ...example.result, run_id: id, documents,
      evidence: example.result.evidence.map((item) => item.id === evidence.id ? evidence : item),
    } }));
    let fragmentRequests = 0;
    let originalRequests = 0;
    await page.route(`**/api/v0/runs/${id}/documents/report/fragments?evidence_id=${evidence.id}`, (route) => {
      fragmentRequests += 1;
      return route.fulfill({ json: evidence });
    });
    const image = readFileSync(new URL('../../../docs/synthetic/nrt-89/inputs/12_communication.png', import.meta.url));
    await page.route(`**/api/v0/runs/${id}/documents/report`, (route) => {
      originalRequests += 1;
      return route.fulfill({ body: image, contentType: 'application/octet-stream' });
    });

    await page.goto(`/checks/${id}`);
    const opener = page.getByRole('button', { name: 'Просмотреть источник' });
    await opener.click();
    const drawer = page.getByRole('dialog', { name: 'Источник документа' });
    const viewport = drawer.getByRole('region', { name: 'Просмотр документа: synthetic-report.png' });
    const box = viewport.locator('.source-viewer-highlight');
    await expect(box).toBeInViewport({ ratio: 1 });
    await expect.poll(() => viewport.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    const header = drawer.getByRole('heading', { name: 'Источник документа' });
    const back = drawer.getByRole('button', { name: 'Вернуться к таблице' });
    await expect(back).toHaveText('К таблице');
    const titleBounds = await header.boundingBox();
    const backBounds = await back.boundingBox();
    const viewBounds = await viewport.boundingBox();
    if (!titleBounds || !backBounds || !viewBounds) throw new Error('Source layout not visible');
    expect(titleBounds.y).toBeGreaterThanOrEqual(backBounds.y);
    expect(titleBounds.y + titleBounds.height).toBeLessThanOrEqual(backBounds.y + backBounds.height);
    expect(viewBounds.height).toBeGreaterThan(Math.min(height * .6, 680));
    await expect(drawer.getByRole('link', { name: 'Скачать оригинал' })).toBeInViewport();
    await expect(drawer.getByRole('button', { name: 'К фрагменту' })).toBeInViewport();
    expect(await drawer.evaluate((element) => element.scrollWidth)).toBeLessThanOrEqual(Math.min(width, 800));
    await drawer.getByRole('button', { name: 'Увеличить масштаб' }).click();
    await drawer.getByRole('button', { name: 'К фрагменту' }).click();
    await expect(box).toBeInViewport({ ratio: 1 });

    const imageElement = viewport.getByRole('img', { name: 'synthetic-report.png' });
    const previousSrc = await imageElement.getAttribute('src');
    const requests = [originalRequests, fragmentRequests];
    const scrollRatio = () => viewport.evaluate((element) =>
      element.scrollTop / Math.max(1, element.scrollHeight - element.clientHeight));
    const before = await scrollRatio();
    expect(before).toBeGreaterThan(0);
    const expand = drawer.getByRole('button', { name: 'Развернуть источник на весь экран' });
    const collapse = drawer.getByRole('button', { name: 'Свернуть источник в боковую панель' });
    const highlight = drawer.getByRole('button', { name: 'Подсветка' });
    await highlight.click();
    await expand.press('Enter');
    await expect(collapse).toHaveAttribute('aria-pressed', 'true');
    await expect(collapse).toBeFocused();
    expect((await drawer.boundingBox())?.width).toBe(width);
    expect(await scrollRatio()).toBeCloseTo(before, 2);
    await expect(drawer.getByText('125%', { exact: true })).toBeVisible();
    await expect(highlight).toHaveAttribute('aria-pressed', 'false');
    await expect(imageElement).toHaveAttribute('src', previousSrc ?? '');
    await collapse.click();
    await expect(expand).toHaveAttribute('aria-pressed', 'false');
    expect((await drawer.boundingBox())?.width).toBe(Math.min(width, 800));
    expect(await scrollRatio()).toBeCloseTo(before, 2);
    expect([originalRequests, fragmentRequests]).toEqual(requests);
    await expand.click();
    await page.keyboard.press('Escape');
    await expect(opener).toBeFocused();
    await opener.click();
    await expect(expand).toHaveAttribute('aria-pressed', 'false');
    await drawer.getByRole('button', { name: 'Закрыть просмотр источника' }).click();
    await expect(opener).toBeFocused();
  });
}

test('results keep the selected row and its evidence together when filtering', async ({ page }) => {
  await page.goto('/checks/synthetic-example');
  const panel = page.getByRole('region', { name: 'Рабочее место сверки' });
  const table = panel.getByRole('table');
  await expect(table.getByRole('button', { name: 'Синтетическая статья A' })).toHaveAttribute('aria-pressed', 'true');
  await expect(panel.getByRole('heading', { name: 'Синтетическая статья A' })).toBeVisible();
  await panel.getByRole('button', { name: 'Не проверено 1' }).click();
  await expect(table.getByRole('row')).toHaveCount(2);
  await expect(panel.getByRole('heading', { name: 'Синтетическая статья B' })).toBeVisible();
  await expect(panel.getByText('Страница 1, строка 4, столбец 2', { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: 'Следующее расхождение' }).click();
  await expect(panel.getByRole('heading', { name: 'Синтетическая статья A' })).toBeVisible();
  await panel.getByRole('searchbox').fill('Отсутствующий показатель');
  await expect(panel.getByText('Показатели не найдены.')).toBeVisible();
  await expect(panel.getByText('Выберите показатель, чтобы увидеть источник.')).toBeVisible();
});

test('issue navigation scrolls the selected row into the mobile table and shows its position', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const id = 'long-result';
  const count = 22;
  const rows = Array.from({ length: count }, (_, index) => ({
    ...example.result.rows[0], id: 'row-' + index, label: 'Расход ' + (index + 1),
  }));
  await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({ json: {
    ...example.result, run_id: id, rows, summary: {
      ...example.result.summary, counts: { verified: 0, discrepancy: count, unverified: 0 },
    },
  } }));

  await page.goto(`/checks/${id}`);
  const panel = page.getByRole('region', { name: 'Рабочее место сверки' });
  const table = panel.getByRole('region', { name: 'Таблица показателей' });
  const next = panel.getByRole('button', { name: 'Следующее расхождение' });
  const previous = panel.getByRole('button', { name: 'Предыдущее расхождение' });
  const firstRow = table.getByRole('button', { name: 'Расход 1', exact: true });
  await expect(panel.getByText('Расхождения: 22', { exact: true })).toBeVisible();
  await expect(panel.getByText('Расхождение 1 из 22', { exact: true })).toBeVisible();
  await expect(previous).toBeDisabled();

  for (let index = 1; index < count; index += 1) await next.click();
  const lastRow = table.getByRole('button', { name: 'Расход 22', exact: true });
  await expect(panel.getByText('Расхождение 22 из 22', { exact: true })).toBeVisible();
  await expect(lastRow).toHaveAttribute('aria-pressed', 'true');
  await expect(lastRow).toBeInViewport({ ratio: 0.95 });
  expect(await table.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
  await expect(next).toBeDisabled();

  for (let index = 1; index < count; index += 1) await previous.click();
  await expect(panel.getByText('Расхождение 1 из 22', { exact: true })).toBeVisible();
  await expect(firstRow).toHaveAttribute('aria-pressed', 'true');
  await expect(firstRow).toBeInViewport({ ratio: 0.95 });
  expect(await table.evaluate((node) => node.scrollTop)).toBeLessThan(2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('source pane opens the stored original at a mobile width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const id = 'stored-layout';
  const ledgerRequests: string[] = [];
  await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({ json: {
    ...example.result, run_id: id, synthetic: true,
  } }));
  await page.route(`**/api/v0/runs/${id}/documents/report/fragments?evidence_id=report-a`, (route) =>
    route.fulfill({ json: example.result.evidence[0] }));
  await page.route(`**/api/v0/runs/${id}/documents/report`, (route) => route.fulfill({
    body: '%PDF-1.4 synthetic transport fixture', contentType: 'application/octet-stream',
  }));
  await page.route(`**/api/v0/runs/${id}/documents/ledger**`, (route) => {
    const url = new URL(route.request().url());
    ledgerRequests.push(url.pathname + url.search);
    return url.pathname.endsWith('/fragments')
      ? route.fulfill({ json: example.result.evidence.find(({ id }) => id === 'amount-2') })
      : route.fulfill({ body: 'synthetic XLSX transport fixture', contentType: 'application/octet-stream' });
  });

  await page.goto(`/checks/${id}`);
  await page.getByRole('button', { name: 'Просмотреть источник' }).click();
  const preview = page.getByRole('region', { name: 'Просмотр источника' });
  const drawer = page.getByRole('dialog', { name: 'Источник документа' });
  await expect(drawer).toBeVisible();
  await expect(preview.getByRole('link', { name: 'Скачать оригинал' })).toBeVisible();
  await expect(preview.getByRole('link', { name: /Открыть страницу 1 PDF/ })).toHaveAttribute('href', /#page=1$/);
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Просмотреть источник' })).toBeFocused();
  await page.getByText('Основания по слагаемым', { exact: true }).press('Enter');
  const amount = page.getByRole('button', { name: /^Сумма · .*C7$/ });
  await amount.press('Enter');
  await expect(amount).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('combobox', { name: 'Доказательство' })).toHaveValue('amount-2');
  await expect(preview).toHaveCount(0);
  expect(ledgerRequests).toEqual([]);
  await page.getByRole('button', { name: 'Просмотреть источник' }).click();
  await expect(preview.getByText(/Лист «Синтетика», C7/)).toBeVisible();
  await expect(preview.getByRole('link', { name: 'Скачать оригинал' })).toBeVisible();
  expect([...new Set(ledgerRequests)].sort()).toEqual([
    `/api/v0/runs/${id}/documents/ledger`,
    `/api/v0/runs/${id}/documents/ledger/fragments?evidence_id=amount-2`,
  ]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await drawer.getByRole('button', { name: 'Вернуться к таблице' }).click();
  await expect(drawer).toHaveCount(0);
});

test('sources on the same PDF page have distinct selectable boxes at 320px', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 780 });
  const id = 'box-result';
  const firstBox = [0.1, 0.2, 0.4, 0.25];
  const secondBox = [0.1, 0.7, 0.4, 0.75];
  const result = structuredClone(example.result);
  const contract = result.evidence.find(({ id }) => id === 'contract');
  if (!contract) throw new Error('Missing synthetic contract evidence');
  const first = { ...contract, locator: { kind: 'page', page: 1, bbox: firstBox } };
  const second = { ...first, id: 'contract-alt', locator: { ...first.locator, bbox: secondBox } };
  const documents = result.documents.map((doc) => {
    if (doc.id === 'ledger') return { ...doc, format: 'pdf', name: 'synthetic-ledger.pdf' };
    if (doc.id === 'ledger-copy') return { ...doc, format: 'pdf', name: 'synthetic-ledger-copy.pdf' };
    return doc;
  });
  const evidence = result.evidence.map((item, index) => {
    if (item.id === first.id) return first;
    return item.document_id === 'ledger'
      ? { ...item, locator: { kind: 'page', page: 1, line: index + 1 } }
      : item;
  });
  result.rows[0].calculation.components[0].contract_refs.push(second.id);

  await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z',
    error: null, progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({
    json: { ...result, run_id: id, documents, evidence: [...evidence, second] },
  }));
  await page.route(`**/api/v0/runs/${id}/documents/ledger`, (route) => route.fulfill({
    body: '%PDF-1.4 synthetic transport fixture', contentType: 'application/octet-stream',
  }));
  await page.route(`**/api/v0/runs/${id}/documents/ledger/fragments?evidence_id=${second.id}`, (route) =>
    route.fulfill({ json: second }));
  await page.goto('/checks/' + id);
  await page.getByText('Основания по слагаемым', { exact: true }).click();
  const component = page.getByRole('list', { name: 'Слагаемые' }).locator(':scope > li').first();
  const choices = page.getByRole('combobox', { name: 'Доказательство' });
  for (const item of [first, second]) {
    const coords = item.locator.bbox.join(', ');
    const label = `synthetic-ledger.pdf · Страница 1 · Рамка (${coords})`;
    await expect(choices.getByRole('option', { name: label, exact: true })).toHaveAttribute('value', item.id);
    const button = component.getByRole('button', { name: 'Договор · ' + label, exact: true });
    await expect(button).toBeVisible();
    await button.click();
    await expect(choices).toHaveValue(item.id);
    await expect(page.locator('.source-address-card').getByText(coords, { exact: true })).toBeVisible();
  }
  const fragmentRequest = page.waitForRequest((request) =>
    new URL(request.url()).pathname.endsWith('/fragments'));
  await page.getByRole('button', { name: 'Просмотреть источник' }).click();
  expect(new URL((await fragmentRequest).url()).searchParams.get('evidence_id')).toBe(second.id);
  await expect(page.getByRole('region', { name: 'Просмотр источника' })
    .getByRole('link', { name: /Открыть страницу 1 PDF/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});
