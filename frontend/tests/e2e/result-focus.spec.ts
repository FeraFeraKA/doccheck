import { expect, test } from '@playwright/test';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

const pixelPng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8tcAAAAASUVORK5CYII=',
  'base64',
);

test('fullscreen reconciliation restores scrolling and focus on Escape and button', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/checks/synthetic-example');
  const enter = page.getByRole('button', { name: 'На весь экран' });
  const exit = page.getByRole('button', { name: 'Выйти из полноэкранного режима' });
  const focus = page.getByRole('dialog', { name: 'Полноэкранная сверка' });
  await enter.click();
  await expect(focus).toBeInViewport();
  await expect(exit).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('hidden');
  await page.keyboard.press('Escape');
  await expect(focus).toHaveCount(0);
  await expect(enter).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('');
  await enter.press('Enter');
  await exit.click();
  await expect(enter).toBeFocused();
  await expect(page.getByRole('region', { name: 'Рабочее место сверки' })).toBeVisible();
});

for (const width of [390, 768]) {
  test(`the PNG drawer keeps the selected discrepancy on Alt+Down at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    const id = 'focus-png';
    const [first] = example.result.rows;
    const [report] = example.result.documents;
    const [evidence] = example.result.evidence;
    const png = { ...report, name: 'synthetic-report.png', format: 'png' };
    await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
      run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null,
      progress: { processed_documents: 4, total_documents: 4 },
    } }));
    await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({ json: {
      ...example.result, run_id: id, documents: [png, ...example.result.documents.slice(1)],
      rows: [first, { ...first, id: 'row-next', label: 'Второе расхождение' }],
      summary: { ...example.result.summary, counts: { verified: 0, discrepancy: 2, unverified: 0 } },
    } }));
    await page.route(`**/api/v0/runs/${id}/documents/report/fragments?evidence_id=report-a`, (route) =>
      route.fulfill({ json: evidence }));
    await page.route(`**/api/v0/runs/${id}/documents/report`, (route) =>
      route.fulfill({ body: pixelPng, contentType: 'application/octet-stream' }));

    await page.goto('/checks/' + id);
    await page.getByText('Основания выбранного показателя', { exact: true }).click();
    await page.getByRole('button', { name: 'На весь экран' }).click();
    await expect(page.getByRole('dialog', { name: 'Полноэкранная сверка' })).toBeVisible();
    const source = page.getByRole('button', { name: 'Просмотреть источник' });
    await source.click();
    const drawer = page.getByLabel('Источник документа', { exact: true }).and(page.locator('.source-workspace-panel[open]'));
    await expect(drawer.getByRole('img', { name: 'synthetic-report.png' })).toBeVisible();
    await expect(drawer.locator('.source-viewer-highlight')).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Полноэкранная сверка' })).toHaveCount(0);
    await drawer.getByRole('button', { name: 'Закрыть просмотр источника' }).press('Alt+ArrowDown');
    await expect(drawer.locator('.source-viewer-highlight')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(drawer).toHaveCount(0);
    await expect(source).toBeFocused();
    await expect(page.getByText('Расхождение 1 из 2', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe('');

    await source.press('Alt+ArrowDown');
    await expect(page.getByText('Расхождение 2 из 2', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Второе расхождение', exact: true })).toBeFocused();
  });
}
