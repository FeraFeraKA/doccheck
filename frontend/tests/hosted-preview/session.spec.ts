import { expect, test } from '@playwright/test';

test('uses a Secure cookie and shows only the invited synthetic result', async ({ page }) => {
  const invitation = process.env.DOCCHECK_HOSTED_BROWSER_INVITE;
  if (!invitation) throw new Error('DOCCHECK_HOSTED_BROWSER_INVITE is required');
  await page.goto('/');
  await expect(page.getByText('Закрытое демо на синтетических документах')).toBeVisible();
  await expect(page.locator('input[type=file]')).toHaveCount(0);
  await page.getByLabel('Код приглашения').fill(invitation);
  await page.getByRole('button', { name: 'Войти' }).click();
  const items = page.getByRole('list', { name: 'Доступные проверки' }).getByRole('listitem');
  await expect(items).toHaveCount(1);
  await expect(items.first()).toContainText('Готово');
  const resultLink = page.getByRole('link', { name: 'Результат JSON' });
  const resultPath = await resultLink.getAttribute('href');
  if (!resultPath) throw new Error('Result link is missing');
  const response = await page.request.get(resultPath);
  expect(response.ok()).toBe(true);
  expect((await response.json()).synthetic).toBe(true);
  expect(response.headers()['cache-control'].split(',').map((item) => item.trim())).toContain('no-store');
  expect(await page.evaluate(() => document.cookie)).not.toContain('doccheck-preview');
  const cookie = (await page.context().cookies()).find(({ name }) => name === '__Host-doccheck-preview');
  expect(cookie?.secure).toBe(true);
  expect(cookie?.httpOnly).toBe(true);
  await page.reload();
  await expect(page.getByRole('link', { name: 'Выгрузка XLSX' })).toBeVisible();
  await page.getByRole('button', { name: 'Источники', exact: true }).click();
  const sources = page.getByRole('region', { name: 'Источники проверки' });
  await sources.getByRole('button', { name: /act.docx/ }).first().click();
  const original = sources.getByRole('link', { name: 'Скачать оригинал' });
  await expect(original).toBeVisible();
  await expect(sources.getByText('Без НДС.', { exact: false })).toBeVisible();
  await expect(sources.locator('mark')).toHaveText('9 000,00');
  const originalPath = await original.getAttribute('href');
  if (!originalPath) throw new Error('Original link is missing');
  const download = await page.request.get(originalPath);
  expect(download.ok()).toBe(true);
  expect(download.headers()['content-disposition']).toContain('attachment');
  const xlsx = await page.getByRole('link', { name: 'Выгрузка XLSX' }).getAttribute('href');
  if (!xlsx) throw new Error('XLSX link is missing');
  const exportResult = await page.request.get(xlsx);
  expect(exportResult.ok()).toBe(true);
  expect(exportResult.headers()['content-type']).toContain('spreadsheetml.sheet');
});

test('distinguishes a missing original, a retryable failure and an available original without text', async ({ page }) => {
  const runId = '11111111-1111-4111-8111-111111111111';
  const prefix = '/api/preview/v1/runs';
  await page.route('**' + prefix, (route) => route.fulfill({
    json: [{ run_id: runId, status: 'completed' }],
  }));
  await page.route('**' + prefix + '/' + runId + '/findings', (route) => route.fulfill({
    json: {
      synthetic: true,
      evidence: [
        { id: 'missing', document_id: 'missing-original' },
        { id: 'retry', document_id: 'retry-original' },
        { id: 'without-text', document_id: 'image' },
      ],
      documents: [
        { id: 'missing-original', name: 'Удалённый DOCX' },
        { id: 'retry-original', name: 'Временный сбой' },
        { id: 'image', name: 'Скан' },
      ],
    },
  }));
  let attempts = 0;
  await page.route('**/fragment-preview?*', (route) => {
    const id = new URL(route.request().url()).searchParams.get('evidence_id');
    if (id === 'missing') return route.fulfill({ status: 404, json: { code: 'document_not_found' } });
    if (id === 'retry' && attempts++ === 0) return route.fulfill({ status: 503 });
    return route.fulfill({ json: { text: null, highlight: null } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Источники', exact: true }).click();
  const sources = page.getByRole('region', { name: 'Источники проверки' });
  const original = sources.getByRole('link', { name: 'Скачать оригинал' });
  await sources.getByRole('button', { name: /Удалённый DOCX/ }).click();
  await expect(sources.getByRole('status')).toHaveText('Оригинал недоступен.');
  await expect(original).toHaveCount(0);
  const retry = sources.getByRole('button', { name: /Временный сбой/ });
  await retry.click();
  await expect(sources.getByRole('alert')).toContainText('Не удалось загрузить фрагмент.');
  await expect(original).toHaveCount(0);
  await retry.click();
  await expect(original).toHaveAttribute('href', prefix + '/' + runId + '/documents/retry-original');
  await sources.getByRole('button', { name: /Скан/ }).click();
  await expect(sources.getByRole('status')).toHaveText('У оригинала нет доступного текстового фрагмента.');
  await expect(original).toHaveAttribute('href', prefix + '/' + runId + '/documents/image');
});
