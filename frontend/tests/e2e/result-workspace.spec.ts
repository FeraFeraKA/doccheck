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

test('source pane opens the stored original at a mobile width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const id = 'stored-layout';
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

  await page.goto(`/checks/${id}`);
  await page.getByRole('button', { name: 'Просмотреть источник' }).click();
  const preview = page.getByRole('region', { name: 'Просмотр источника' });
  await expect(preview.getByRole('link', { name: 'Скачать оригинал' })).toBeVisible();
  await expect(preview.getByRole('link', { name: /Открыть страницу 1 PDF/ })).toHaveAttribute('href', /#page=1$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
