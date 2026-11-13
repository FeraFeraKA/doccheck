import { expect, test } from '@playwright/test';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

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
  await expect(preview.getByRole('link', { name: 'Скачать оригинал' })).toBeVisible();
  await expect(preview.getByRole('link', { name: /Открыть страницу 1 PDF/ })).toHaveAttribute('href', /#page=1$/);
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
});
