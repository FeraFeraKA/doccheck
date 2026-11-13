import { expect, test } from '@playwright/test';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

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
  await page.route('**/api/v0/runs/saved-run/findings', (route) => route.fulfill({
    status: 409,
    json: { code: 'result_pending', message: 'Результат пока недоступен' },
  }));
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
  const note = 'Скачивание XLSX доступно для сохранённой проверки.';
  await expect(download).toHaveAccessibleDescription(note);
  await expect(page.getByText(note)).toBeVisible();
});

test('the stored conclusion downloads XLSX from its own run', async ({ page }) => {
  const runId = 'saved-xlsx';
  const path = `/api/v0/runs/${runId}`;
  await page.route(`**${path}`, (route) => route.fulfill({ json: {
    run_id: runId, status: 'completed_with_issues', created_at: '2026-11-13T12:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route(`**${path}/findings`, (route) => route.fulfill({
    json: { ...example.result, run_id: runId },
  }));
  let exportCalls = 0;
  await page.route(`**${path}/exports/xlsx`, (route) => {
    exportCalls += 1;
    if (exportCalls === 1) return route.fulfill({ status: 503, json: { code: 'service_unavailable' } });
    return route.fulfill({
      body: 'Synthetic download transport response',
      contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
  });

  await page.goto(`/checks/${runId}/conclusion`);
  const button = page.getByRole('button', { name: 'Скачать XLSX' });
  await button.click();
  await expect(page.getByRole('alert')).toHaveText('Не удалось скачать XLSX. Повторите попытку.');
  const downloaded = page.waitForEvent('download');
  await button.click();
  const file = await downloaded;
  expect(file.suggestedFilename()).toBe(`doccheck-${runId}.xlsx`);
  expect(await file.failure()).toBeNull();
  expect(exportCalls).toBe(2);
  await expect(page).toHaveURL(`/checks/${runId}/conclusion`);
});

test('the finished check loads stored findings and can retry without repeating status polling', async ({ page }) => {
  const runId = 'partial-result';
  const [first, ...otherRows] = example.result.rows;
  const findings = {
    ...example.result,
    run_id: runId,
    rows: [{
      ...first,
      expected_value: null,
      observed_evidence_sum: first.calculation.components[0].amount,
      delta: null,
      status: 'unverified',
      completeness: { ...first.completeness, state: 'incomplete', reason: 'Не хватает одной операции', evidence_refs: [] },
      calculation: { ...first.calculation, components: first.calculation.components.slice(0, 1) },
      reasons: [{ code: 'missing_evidence', message: 'Одна операция не подтверждена', evidence_refs: [] }],
      root_issue_id: null,
    }, ...otherRows],
    summary: {
      ...example.result.summary,
      counts: { verified: 0, discrepancy: 0, unverified: 2 },
      primary_issues: example.result.summary.primary_issues.filter((issue) => issue.id !== 'issue-a'),
      conclusion: 'Оба показателя остаются непроверенными.',
    },
  };
  let statusCalls = 0;
  await page.route('**/api/v0/runs/partial-result', (route) => {
    statusCalls += 1;
    return route.fulfill({ json: {
      run_id: runId, status: 'completed_with_issues', created_at: '2026-11-13T12:00:00Z', error: null,
      progress: { processed_documents: 4, total_documents: 4 },
    } });
  });
  let finishFailure: (() => void) | undefined;
  const firstFailure = new Promise<void>((resolve) => { finishFailure = resolve; });
  let findingsCalls = 0;
  await page.route('**/api/v0/runs/partial-result/findings', async (route) => {
    findingsCalls += 1;
    if (findingsCalls === 1) {
      await firstFailure;
      return route.fulfill({ status: 503, json: { code: 'service_unavailable', message: 'Сервис недоступен' } });
    }
    return route.fulfill({ json: findings });
  });
  await page.goto('/checks/partial-result');
  await expect(page.getByText('Загрузка результата сверки…')).toBeVisible();
  finishFailure?.();
  await expect(page.getByRole('alert')).toHaveText('Не удалось загрузить результат сверки.');
  await expect(page.getByText('Состояние проверки · Завершена с замечаниями')).toBeVisible();
  await page.getByRole('button', { name: 'Повторить загрузку результата' }).click();

  await expect(page.getByText('Синтетический результат · сохранённая проверка')).toBeVisible();
  const partial = page.getByRole('row').filter({ hasText: 'Синтетическая статья A' });
  await expect(partial.getByText('Частичная сумма: 60,25 RUB')).toBeVisible();
  await expect(partial.getByRole('cell', { name: '—', exact: true })).toBeVisible();
  await expect(partial.getByRole('cell', { name: 'Не проверен', exact: true })).toBeVisible();
  await page.getByLabel('Доказательство').selectOption('amount-1');
  await expect(page.getByText('Лист «Синтетика», C6', { exact: true })).toBeVisible();
  await page.getByText('Основания по слагаемым').click();
  await expect(page.getByText(/Операция в строке 6 совпала по договору/)).toBeVisible();

  const zero = page.getByRole('row').filter({ hasText: 'Синтетическая статья B' });
  await expect(zero.getByRole('cell', { name: '0,00', exact: true })).toBeVisible();
  await zero.getByRole('button').click();
  await expect(page.getByText('Источник статьи B не прочитан')).toBeVisible();
  await expect(page.getByText(/Ошибка чтения файла/)).toBeVisible();
  await page.getByRole('link', { name: 'Исключения' }).click();
  await expect(page.getByText('Ошибка чтения', { exact: true })).toBeVisible();
  expect(statusCalls).toBe(1);
  expect(findingsCalls).toBe(2);
});

test('a non-synthetic saved result with no rows has an explicit empty state', async ({ page }) => {
  await page.route('**/api/v0/runs/empty-run', (route) => route.fulfill({ json: {
    run_id: 'empty-run', status: 'completed', created_at: '2026-11-13T12:00:00Z', error: null,
    progress: { processed_documents: 2, total_documents: 2 },
  } }));
  await page.route('**/api/v0/runs/empty-run/findings', (route) => route.fulfill({ json: {
    ...example.result,
    run_id: 'empty-run',
    synthetic: false,
    scope: { ...example.result.scope, report_row_locator: example.result.evidence[0].locator },
    rows: [],
    summary: {
      counts: { verified: 0, discrepancy: 0, unverified: 0 },
      primary_issues: [],
      conclusion: 'Показатели отсутствуют.',
    },
  } }));

  await page.goto('/checks/empty-run');
  await expect(page.getByText('Показатели отсутствуют.', { exact: true })).toBeVisible();
  await expect(page.getByText('Синтетический результат · сохранённая проверка')).toHaveCount(0);
  await expect(page.getByRole('table')).toHaveCount(0);
});

test('mixed units stay visible even when all values in a row are unknown', async ({ page }) => {
  const [money, missing] = example.result.rows;
  const quantity = {
    ...missing,
    unit: 'ч',
    reported_value: null,
    reported_evidence_refs: [],
  };
  const result = {
    ...example.result,
    run_id: 'mixed-units',
    rows: [money, quantity],
  };
  await page.route('**/api/v0/runs/mixed-units', (route) => route.fulfill({ json: {
    run_id: 'mixed-units', status: 'completed_with_issues', created_at: '2026-11-13T12:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route('**/api/v0/runs/mixed-units/findings', (route) => route.fulfill({ json: result }));

  await page.goto('/checks/mixed-units');
  const rub = page.getByRole('row').filter({ hasText: money.label });
  for (const value of ['RUB', '150,50', '120,50', '30,00']) {
    await expect(rub.getByRole('cell', { name: value, exact: true })).toBeVisible();
  }
  const hours = page.getByRole('row').filter({ hasText: quantity.label });
  await expect(hours.getByRole('cell', { name: 'ч', exact: true })).toBeVisible();
  await expect(hours.getByRole('cell', { name: 'Не проверен', exact: true })).toBeVisible();
  await expect(hours.getByRole('cell', { name: '—', exact: true })).toHaveCount(3);
  await expect(hours.getByText(/Частичная сумма/)).toHaveCount(0);
});
