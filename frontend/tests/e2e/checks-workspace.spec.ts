import { expect, test } from '@playwright/test';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

test('the accountant opens the synthetic reconciliation and sees discrepancies and sources', async ({ page }) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests.push(request.url());
  });

  await page.goto('/');
  await expect(page.getByRole('group', { name: 'Роль интерфейса' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Аспирант' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Бухгалтер' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Новая проверка' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Выбрать файл', exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })
    .getByRole('link', { name: 'Новая проверка' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('link', { name: 'Журнал действий' })).toHaveCount(0);
  await expect(page.getByText('Добавьте КФЗ и первичные документы.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Отправить на проверку' })).toBeDisabled();
  await page.getByRole('link', { name: 'Открыть готовый синтетический результат' }).click();

  const discrepancy = page.getByRole('row').filter({ hasText: 'Синтетическая статья A' });
  await expect(discrepancy.getByRole('cell', { name: 'Расхождение', exact: true })).toBeVisible();
  await expect(discrepancy.getByRole('cell', { name: '30,00', exact: true })).toBeVisible();
  const unverified = page.getByRole('region', { name: 'Недостаточно подтверждений' });
  await expect(unverified).toContainText('Синтетическая статья B');
  await expect(unverified).not.toContainText('Синтетическая статья A');

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
  await expect(page.getByRole('button', { name: 'Просмотреть источник' })).toHaveCount(0);
  expect(apiRequests).toEqual([]);
});

for (const width of [320, 390]) {
  test(`reconciliation shows the discrepancy count on entry at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.route('**/api/v0/runs', (route) => route.fulfill({ json: { items: [], next_cursor: null } }));
    await page.goto('/checks');
    await page.getByRole('link', { name: 'Синтетическая сверка', exact: true }).click();

    const summary = page.getByRole('region', { name: 'Заключение по проверке' });
    await expect(summary.getByText('Расхождения: 1', { exact: true })).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole('heading', { name: 'Показатели отчёта' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Исключения' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

test('the upload wizard selects files without secure-context APIs', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window.crypto, 'randomUUID', { value: undefined });
  });
  await page.route('**/api/v0/runs', async (route) => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().headers()['idempotency-key']).toMatch(/^[a-f0-9-]{36}$/);
    await route.fulfill({
      status: 202, headers: { Location: '/api/v0/runs/secure-fallback' },
      json: { run_id: 'secure-fallback', status: 'queued' },
    });
  });
  await page.route('**/api/v0/runs/secure-fallback', (route) => route.fulfill({ json: {
    run_id: 'secure-fallback', status: 'queued', created_at: '2026-11-14T00:00:00Z', error: null,
  } }));
  await page.goto('/checks/new');
  await page.getByLabel('Выберите КФЗ').setInputFiles({
    name: 'example.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 synthetic example'),
  });
  await expect(page.getByText('example.pdf', { exact: true })).toBeVisible();
  await page.getByLabel('Выберите первичные документы').setInputFiles({
    name: 'support.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 synthetic support'),
  });
  await page.getByRole('button', { name: 'Отправить на проверку' }).click();
  await expect(page).toHaveURL(/\/checks\/secure-fallback$/);
});

test('the accountant distinguishes missing files, invalid selection and unknown checks', async ({ page }) => {
  await page.route('**/api/v0/runs/unknown', (route) => route.fulfill({ status: 404 }));
  await page.route('**/api/v0/runs', (route) => route.fulfill({ json: {
    items: [{ run_id: 'saved-run', status: 'queued', error: null, created_at: '2026-11-13T12:00:00Z' }],
    next_cursor: null,
  } }));
  await page.goto('/checks/new');
  await expect(page.getByText('Перетащите КФЗ сюда')).toBeVisible();
  await page.getByLabel('Выберите КФЗ').setInputFiles({
    name: 'empty.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.alloc(0),
  });
  await expect(page.getByRole('alert')).toHaveText('Добавьте непустые PDF, DOCX, XLSX или PNG.');
  await expect(page.getByRole('button', { name: 'Отправить на проверку' })).toBeDisabled();

  await page.getByLabel('Выберите КФЗ').setInputFiles({
    name: 'report.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 synthetic report'),
  });
  await expect(page.getByRole('button', { name: 'Отправить на проверку' })).toBeDisabled();
  await expect(page.getByText('Перетащите документы сюда')).toBeVisible();

  await page.goto('/checks/unknown/conclusion');
  await expect(page.getByRole('heading', { name: 'Проверка не найдена' })).toBeVisible();
  await page.getByRole('link', { name: 'Все проверки' }).click();
  await expect(page.getByRole('link', { name: 'Синтетическая сверка', exact: true })).toBeVisible();
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
  await expect(page.getByRole('link', { name: 'Синтетическая сверка', exact: true })).toBeVisible();
  const older = page.getByRole('link', { name: 'Более ранние проверки' });
  await page.getByRole('complementary', { name: 'Меню DocCheck' }).hover({ position: { x: 4, y: 4 } });
  await expect(page.getByRole('button', { name: 'Свернуть меню' })).toHaveAttribute('aria-expanded', 'true');
  await older.click();
  await page.reload();
  await expect(page.getByRole('link', { name: 'Проверка older-run', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'К новым проверкам' }).click();
  await page.getByRole('link', { name: 'Проверка saved-run', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Проверка saved-run' })).toBeVisible();
  await expect(page.getByText('Обработано документов: 2 из 2')).toBeVisible();
  await expect(page.getByText('Результат проверки недоступен.')).toBeVisible();
});

test('the synthetic result and its document routes have no XLSX action', async ({ page }) => {
  const exportCalls: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.endsWith('/exports/xlsx')) exportCalls.push(request.url());
  });
  const runPath = '/checks/synthetic-example';
  for (const suffix of ['', '/documents', '/exceptions', '/conclusion']) {
    await page.goto(runPath + suffix);
    await expect(page.getByRole('navigation', { name: 'Разделы проверки' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Скачать XLSX' })).toHaveCount(0);
  }
  expect(exportCalls).toEqual([]);
});

test('documents and the direct stored conclusion download XLSX for the same run', async ({ page }) => {
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

  await page.goto(`/checks/${runId}`);
  await expect(page.getByText('Вывод по проверке')).toBeVisible();
  const button = page.getByRole('button', { name: 'Скачать XLSX' });
  await expect(button).toHaveCount(0);
  await page.getByRole('navigation', { name: 'Разделы проверки' }).getByRole('link', { name: 'Документы' }).click();
  await expect(page).toHaveURL(`/checks/${runId}/documents`);
  await expect(page.getByRole('region', { name: 'Документы' }).getByRole('button', { name: 'Скачать XLSX' })).toBeVisible();
  await button.click();
  await expect(page.getByRole('alert')).toHaveText('Не удалось скачать XLSX. Повторите попытку.');

  for (const suffix of ['/documents', '/conclusion']) {
    await page.goto(`/checks/${runId}${suffix}`);
    const downloaded = page.waitForEvent('download');
    await button.click();
    const file = await downloaded;
    expect(file.suggestedFilename()).toBe(`doccheck-${runId}.xlsx`);
    expect(await file.failure()).toBeNull();
    await expect(page).toHaveURL(`/checks/${runId}${suffix}`);
  }
  expect(exportCalls).toBe(3);
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
  await expect(page.getByRole('region', { name: 'Недостаточно подтверждений' }))
    .toContainText('Частичная сумма: 60,25 RUB');
  await expect(partial.getByRole('cell', { name: '—', exact: true })).toBeVisible();
  await expect(partial.getByRole('cell', { name: 'Не проверен', exact: true })).toBeVisible();
  await page.getByLabel('Доказательство').selectOption('amount-1');
  await expect(page.getByText('Лист «Синтетика», C6', { exact: true })).toBeVisible();
  await page.getByText('Основания по слагаемым').click();
  await expect(page.getByText(/Операция в строке 6 совпала по договору/)).toBeVisible();

  const zero = page.getByRole('row').filter({ hasText: 'Синтетическая статья B' });
  await expect(zero.getByRole('cell', { name: '0,00', exact: true })).toBeVisible();
  await zero.getByRole('button').click();
  const reconciliation = page.getByRole('region', { name: 'Рабочее место сверки' });
  await expect(reconciliation.getByText('Источник статьи B не прочитан')).toBeVisible();
  await expect(page.getByText(/Ошибка чтения файла/)).toBeVisible();
  await page.getByRole('link', { name: 'Исключения' }).click();
  await expect(page.getByText('Ошибка чтения', { exact: true })).toBeVisible();
  expect(statusCalls).toBe(1);
  expect(findingsCalls).toBe(2);
});

test('a complete document sum stays complete when the reported amount is missing', async ({ page }) => {
  const id = 'missing-reported-amount';
  const [first, ...rest] = example.result.rows;
  await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed_with_issues', created_at: '2026-11-13T12:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({ json: {
    ...example.result, run_id: id,
    rows: [{
      ...first, reported_value: null, reported_evidence_refs: [], delta: null, status: 'unverified',
      reasons: [{ code: 'missing_reported_value', message: 'Нет суммы в КФЗ', evidence_refs: [] }],
      root_issue_id: null,
    }, ...rest],
    summary: {
      ...example.result.summary, counts: { verified: 0, discrepancy: 0, unverified: 2 },
      primary_issues: example.result.summary.primary_issues.filter((issue) => issue.id !== 'issue-a'),
    },
  } }));

  await page.goto(`/checks/${id}`);
  const unverified = page.getByRole('region', { name: 'Недостаточно подтверждений' });
  await expect(unverified.getByText('Нет суммы в КФЗ')).toBeVisible();
  await expect(unverified.getByText('Сумма по документам: 120,50 RUB')).toBeVisible();
  await expect(unverified.getByText(/Частичная сумма/)).toHaveCount(0);
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
  const results = page.getByRole('region', { name: 'Заключение по проверке' });
  await expect(results.getByText('Показатели отсутствуют.', { exact: true })).toBeVisible();
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

test('the selected stored evidence opens its own original and address', async ({ page }) => {
  const runId = 'run-with-source';
  const result = { ...example.result, run_id: runId };
  const requested: string[] = [];
  await page.route('**/api/v0/runs/run-with-source', (route) => route.fulfill({ json: {
    run_id: runId, status: 'completed_with_issues', created_at: '2026-11-13T12:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route('**/api/v0/runs/run-with-source/findings', (route) => route.fulfill({ json: result }));
  await page.route('**/api/v0/runs/run-with-source/documents/**', (route) => {
    const url = new URL(route.request().url());
    requested.push(url.pathname + url.search);
    const evidenceId = url.searchParams.get('evidence_id');
    if (evidenceId === null) {
      return route.fulfill({ body: 'Synthetic file', contentType: 'application/octet-stream' });
    }
    const evidence = result.evidence.find(({ id }) => id === evidenceId);
    return route.fulfill({ json: evidence });
  });
  await page.goto('/checks/' + runId);

  const open = page.getByRole('button', { name: 'Просмотреть источник' });
  await expect(open).toBeVisible();
  expect(requested).toEqual([]);
  await open.click();
  const preview = page.getByRole('region', { name: 'Просмотр источника' });
  await expect(preview.getByRole('link', { name: 'Открыть страницу 1 PDF (в новой вкладке)' }))
    .toHaveAttribute('href', /^blob:.*#page=1$/);
  await expect(preview.getByRole('link', { name: 'Скачать оригинал' })).toHaveAttribute('download', 'synthetic-report.pdf');
  expect(requested).toEqual(expect.arrayContaining([
    '/api/v0/runs/run-with-source/documents/report',
    '/api/v0/runs/run-with-source/documents/report/fragments?evidence_id=report-a',
  ]));

  await page.getByRole('button', { name: 'Закрыть просмотр источника' }).click();
  await page.getByLabel('Доказательство').selectOption('amount-1');
  await expect(preview).toHaveCount(0);
  await open.click();
  await expect(preview.getByText(/Лист «Синтетика», C6/)).toBeVisible();
  await expect(preview.getByText('Для просмотра по адресу откройте скачанный файл в офисном приложении.')).toBeVisible();
  expect(requested).toEqual(expect.arrayContaining([
    '/api/v0/runs/run-with-source/documents/ledger',
    '/api/v0/runs/run-with-source/documents/ledger/fragments?evidence_id=amount-1',
  ]));
});

test('the compact wizard adapts its upload blocks and keeps the example link in view', async ({ page }) => {
  for (const width of [320, 390, 701, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');

    const example = page.getByRole('link', { name: 'Открыть готовый синтетический результат' });
    if (width < 700) await example.evaluate((link) => link.scrollIntoView({ block: 'center' }));
    await expect(example).toBeInViewport({ ratio: 1 });
    const report = await page.getByRole('region', { name: 'КФЗ', exact: true }).boundingBox();
    const documents = await page.getByRole('region', { name: 'Первичные документы' }).boundingBox();
    if (!report || !documents) throw new Error('Оба блока должны быть видны');
    if (width < 768) {
      expect(documents.y).toBeGreaterThan(report.y);
      expect(documents.x).toBe(report.x);
    } else {
      expect(documents.y).toBe(report.y);
      expect(documents.x).toBeGreaterThan(report.x);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  }
  await page.getByRole('link', { name: 'Открыть готовый синтетический результат' }).click();
  await expect(page.getByRole('heading', { name: 'Синтетическая сверка' })).toBeVisible();
});
