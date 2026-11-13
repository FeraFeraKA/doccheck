import { expect, test } from '@playwright/test';

test('the accountant opens the synthetic reconciliation and sees discrepancies and sources', async ({ page }) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url());
  });

  await page.goto('/checks/new');
  await expect(page.getByText('Синтетический режим · файлы остаются в браузере')).toBeVisible();
  await expect(page.getByRole('group', { name: 'Роль интерфейса' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Аспирант' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Бухгалтер' })).toHaveCount(0);
  await expect(page.getByLabel('Выберите КФЗ')).toBeVisible();
  await expect(page.getByText(/собирает сводные значения из первичных документов/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Далее' })).toBeDisabled();
  await page.getByRole('button', { name: 'Загрузить пример' }).click();
  await expect(page.getByText('01_kfz.pdf')).toBeVisible();
  await page.getByRole('button', { name: 'Далее' }).click();
  await expect(page.getByLabel('Выберите первичные документы')).toBeVisible();
  await page.getByRole('button', { name: 'Загрузить пример' }).click();
  await expect(page.getByText('02_payroll_06.xlsx')).toBeVisible();
  await page.getByRole('link', { name: 'Открыть готовый синтетический результат' }).click();

  const discrepancy = page.getByRole('row').filter({ hasText: 'Синтетическая статья A' });
  await expect(discrepancy.getByRole('cell', { name: 'Расхождение', exact: true })).toBeVisible();
  await expect(discrepancy.getByRole('cell', { name: '30,00', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Возможные причины расхождений' })).toBeVisible();
  await expect(page.getByText(/В этом примере таких гипотез нет/)).toBeVisible();

  const row = page.getByRole('row').filter({ hasText: 'Синтетическая статья B' });
  await expect(row.getByRole('cell', { name: '0,00', exact: true })).toBeVisible();
  await expect(row.getByRole('cell', { name: '—', exact: true })).toHaveCount(2);
  await page.getByLabel('Доказательство').selectOption('amount-1');
  await expect(page.getByText('Лист «Синтетика», C6', { exact: true })).toBeVisible();
  await row.getByRole('button').click();
  await expect(page.getByText('Страница 1, строка 4, столбец 2', { exact: true })).toBeVisible();

  await page.getByRole('link', { name: 'Исключения' }).click();
  await expect(page.getByText('Действия бухгалтера недоступны в синтетическом режиме.')).toBeVisible();
  await expect(page.getByText('Ошибка чтения', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('Действия бухгалтера недоступны в синтетическом режиме.')).toBeVisible();
  await expect(page.getByText('Ошибка чтения', { exact: true })).toBeVisible();
  expect(apiRequests).toEqual([]);
});

for (const width of [320, 390]) {
  test(`reconciliation shows the discrepancy count on entry at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.route('**/api/v0/runs', (route) => route.fulfill({ json: { items: [], next_cursor: null } }));
    await page.goto('/checks');
    await page.getByRole('link', { name: 'Синтетическая сверка' }).click();

    await expect(page.getByText('Расхождения: 1', { exact: true })).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole('heading', { name: 'Показатели' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Исключения' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

test('the upload wizard selects files without secure-context APIs', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window.crypto, 'randomUUID', { value: undefined });
  });
  await page.goto('/checks/new');
  await page.getByLabel('Выберите КФЗ').setInputFiles({
    name: 'example.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 synthetic example'),
  });
  await expect(page.getByText('example.pdf', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Далее' })).toBeEnabled();
});

test('the accountant distinguishes missing files, invalid selection and unknown checks', async ({ page }) => {
  await page.route('**/api/v0/runs/unknown', (route) => route.fulfill({ status: 404 }));
  await page.route('**/api/v0/runs', (route) => route.fulfill({ json: {
    items: [{ run_id: 'saved-run', status: 'queued', error: null, created_at: '2026-11-13T12:00:00Z' }],
    next_cursor: null,
  } }));
  await page.goto('/checks/new');
  await expect(page.getByText('КФЗ пока не выбрана.')).toBeVisible();
  await page.getByLabel('Выберите КФЗ').setInputFiles({
    name: 'empty.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.alloc(0),
  });
  await expect(page.getByRole('alert')).toHaveText('Добавьте непустые PDF, DOCX, XLSX или PNG.');
  await expect(page.getByRole('button', { name: 'Далее' })).toBeDisabled();

  await page.getByRole('button', { name: 'Загрузить пример' }).click();
  await page.getByRole('button', { name: 'Далее' }).click();
  await expect(page.getByText('Первичные документы пока не выбраны.')).toBeVisible();

  await page.goto('/checks/unknown/conclusion');
  await expect(page.getByRole('heading', { name: 'Проверка не найдена' })).toBeVisible();
  await page.getByRole('link', { name: 'Все проверки' }).click();
  await expect(page.getByRole('link', { name: 'Синтетическая сверка' })).toBeVisible();
  await page.getByRole('searchbox', { name: 'Поиск на странице' }).fill('нет совпадений');
  await expect(page.getByText('Проверки не найдены.')).toBeVisible();
});

test('saved run and history cursor are recovered from the URL', async ({ page }) => {
  const summary = {
    run_id: 'saved-run', status: 'completed', error: null, created_at: '2026-11-13T12:00:00Z',
  };
  const cursor = 'older-page';
  await page.route('**/api/v0/runs*', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname !== '/api/v0/runs') return route.fallback();
    return route.fulfill({ json: url.searchParams.get('cursor') === cursor
      ? { items: [{ ...summary, run_id: 'older-run' }], next_cursor: null }
      : { items: [summary], next_cursor: cursor } });
  });
  await page.route('**/api/v0/runs/saved-run', (route) => route.fulfill({ json: {
    ...summary, progress: { processed_documents: 2, total_documents: 2 },
  } }));
  await page.goto('/checks');
  await expect(page.getByRole('link', { name: 'Синтетическая сверка' })).toBeVisible();
  await page.getByRole('link', { name: 'Более ранние проверки' }).click();
  await page.reload();
  await expect(page.getByRole('link', { name: 'Проверка older-run' })).toBeVisible();
  await page.getByRole('link', { name: 'К новым проверкам' }).click();
  await page.getByRole('link', { name: 'Проверка saved-run' }).click();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Проверка saved-run' })).toBeVisible();
  await expect(page.getByText('Обработано документов: 2 из 2')).toBeVisible();
  await expect(page.getByText('Результат проверки недоступен.')).toBeVisible();
});

test('the synthetic conclusion shows XLSX export as unavailable', async ({ page }) => {
  await page.route('**/api/v0/runs', (route) => route.fulfill({ json: { items: [], next_cursor: null } }));
  await page.goto('/checks');
  await page.getByRole('link', { name: 'Синтетическая сверка' }).click();
  await page.getByRole('link', { name: 'Заключение' }).click();

  const download = page.getByRole('button', { name: 'Скачать XLSX' });
  await expect(download).toBeVisible();
  await expect(download).toBeDisabled();
  const note = 'Скачивание результата станет доступно после подключения экспорта.';
  await expect(download).toHaveAccessibleDescription(note);
  await expect(page.getByText(note)).toBeVisible();
});
