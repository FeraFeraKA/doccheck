import { expect, test } from '@playwright/test';

test('Lovable workspace uses local examples and links values to their sources', async ({ page }) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url());
  });

  await page.goto('/checks/new');
  await expect(page.getByText('Синтетический режим · файлы остаются в браузере')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Далее' })).toBeDisabled();
  await page.getByRole('button', { name: 'Загрузить пример' }).click();
  await expect(page.getByText('01_kfz.pdf')).toBeVisible();
  await page.getByRole('button', { name: 'Далее' }).click();
  await page.getByRole('button', { name: 'Загрузить пример' }).click();
  await expect(page.getByText('02_payroll_06.xlsx')).toBeVisible();
  await page.getByRole('link', { name: 'Открыть готовый синтетический результат' }).click();

  const row = page.getByRole('row').filter({ hasText: 'Синтетическая статья B' });
  await expect(row.getByRole('cell', { name: '0,00', exact: true })).toBeVisible();
  await expect(row.getByRole('cell', { name: '—', exact: true })).toHaveCount(2);
  await page.getByLabel('Доказательство').selectOption('amount-1');
  await expect(page.getByText('Лист «Синтетика», C6', { exact: true })).toBeVisible();
  await row.getByRole('button').click();
  await expect(page.getByText('Страница 1, строка 4, столбец 2', { exact: true })).toBeVisible();

  await expect(page.getByRole('link', { name: 'Исключения' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Бухгалтер' }).click();
  await page.getByRole('link', { name: 'Исключения' }).click();
  await expect(page.getByText('Ошибка чтения', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('Откройте этот раздел в представлении бухгалтера.')).toBeVisible();
  await page.getByRole('button', { name: 'Бухгалтер' }).click();
  await expect(page.getByText('Ошибка чтения', { exact: true })).toBeVisible();
  expect(apiRequests).toEqual([]);
});

test('workspace navigation and table fit the mobile viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/checks');
  await page.getByRole('link', { name: 'Синтетическая сверка' }).click();
  await expect(page.getByRole('heading', { name: 'Показатели' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole('button', { name: 'Бухгалтер' }).click();
  await expect(page.getByRole('button', { name: 'Бухгалтер' })).toHaveAttribute('aria-pressed', 'true');
});

test('the upload wizard selects files without secure-context APIs', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window.crypto, 'randomUUID', { value: undefined });
  });
  await page.goto('/checks/new');
  await page.getByLabel('Выберите отчёт').setInputFiles({
    name: 'example.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 synthetic example'),
  });
  await expect(page.getByText('example.pdf', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Далее' })).toBeEnabled();
});
