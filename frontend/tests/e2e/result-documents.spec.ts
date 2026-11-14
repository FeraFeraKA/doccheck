import { expect, test } from '@playwright/test';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

test('synthetic document decisions, addresses and row links work without the document API', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const apiCalls: string[] = [];
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith('/api/')) apiCalls.push(path);
  });
  await page.goto('/checks/synthetic-example/documents');

  const table = page.getByRole('region', { name: 'Таблица документов' });
  const filters = page.getByRole('group', { name: 'Статус файла' });
  await expect(table.getByRole('row')).toHaveCount(5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await filters.getByRole('button', { name: 'Прочитано (3)' }).click();
  const duplicate = table.getByRole('row').filter({ hasText: 'synthetic-ledger-copy.xlsx' });
  await expect(duplicate.getByText('Исключён', { exact: true })).toBeVisible();
  await filters.getByRole('button', { name: 'Ошибочные (1)' }).click();
  await expect(duplicate).toHaveCount(0);
  await expect(table.getByText('Не удалось прочитать', { exact: true })).toBeVisible();
  await expect(table.getByText('Ошибка чтения', { exact: true })).toBeVisible();
  await filters.getByRole('button', { name: 'Все (4)' }).click();
  const file = table.getByRole('button', { name: 'synthetic-ledger.xlsx', exact: true });
  await file.press('Enter');
  const dialog = page.getByLabel('Источник документа', { exact: true }).and(page.locator('.source-workspace-panel[open]'));
  await expect(dialog.getByText(/^Оригинал (в готовом примере|документа) недоступен\.$/)).toBeVisible();
  await dialog.getByRole('combobox', { name: 'Адрес доказательства' }).selectOption('amount-2');
  await expect(dialog.getByRole('combobox', { name: 'Адрес доказательства' }).locator('option:checked'))
    .toHaveText('Лист «Синтетика», C7');
  await page.keyboard.press('Escape');
  await expect(file).toBeFocused();

  const ledger = table.getByRole('row').filter({ has: page.getByRole('button', { name: 'synthetic-ledger.xlsx', exact: true }) });
  await expect(ledger.getByRole('link', { name: 'Синтетическая статья A' })).toHaveCount(1);
  await ledger.getByRole('link', { name: 'Синтетическая статья A' }).click();
  await expect(page).toHaveURL(/synthetic-example\?indicator=row-a$/);
  const indicator = page.getByRole('button', { name: 'Синтетическая статья A', exact: true });
  await expect(indicator).toHaveAttribute('aria-expanded', 'true');
  await page.reload();
  await expect(indicator).toHaveAttribute('aria-expanded', 'true');
  await page.goto('/checks/synthetic-example?indicator=unknown');
  await expect(indicator).toHaveAttribute('aria-expanded', 'false');
  expect(apiCalls).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('stored exception without an address requests only its own original', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const id = 'stored-documents';
  const originals: string[] = [];
  await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({
    json: { ...example.result, run_id: id },
  }));
  await page.route(`**/api/v0/runs/${id}/documents/**`, (route) => {
    const url = new URL(route.request().url());
    originals.push(url.pathname + url.search);
    return route.fulfill({ status: 404 });
  });

  await page.goto(`/checks/${id}/exceptions`);
  const exceptions = page.getByRole('region', { name: 'Исключения', exact: true });
  const filters = exceptions.getByRole('group', { name: 'Статус исключения' });
  await expect(filters.getByRole('button', { name: 'Все (2)' })).toBeVisible();
  await expect(filters.getByRole('button', { name: 'Включён', exact: false })).toHaveCount(0);
  await filters.getByRole('button', { name: 'Ошибка чтения (1)' }).click();
  const table = exceptions.getByRole('region', { name: 'Таблица исключений' });
  await expect(page.getByRole('region', { name: 'Таблица документов' })).toBeVisible();
  await expect(table.getByRole('row')).toHaveCount(2);
  await expect(table.getByRole('link', { name: 'Синтетическая статья B' })).toHaveCount(1);
  const file = table.getByRole('button', { name: example.result.documents[3].name });
  await file.click();
  const dialog = page.getByLabel('Источник документа', { exact: true }).and(page.locator('.source-workspace-panel[open]'));
  await expect(dialog.getByText('Адрес фрагмента отсутствует.')).toBeVisible();
  await expect(dialog.getByRole('alert')).toBeVisible();
  expect([...new Set(originals)]).toEqual([`/api/v0/runs/${id}/documents/unreadable`]);
  await page.keyboard.press('Escape');
  await expect(file).toBeFocused();
});

test('an exception can be opened from the document list without leaving the documents tab', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/checks/synthetic-example/documents');
  const anchor = page.getByRole('link', { name: 'К исключениям' });
  await anchor.press('Enter');
  const exceptions = page.getByRole('region', { name: 'Исключения', exact: true });
  await expect(page).toHaveURL(/\/documents#exceptions$/);
  await expect(exceptions).toBeFocused();
  await expect(exceptions.getByRole('heading', { name: 'Исключения' })).toBeInViewport();

  const file = exceptions.getByRole('button', { name: 'synthetic-ledger-copy.xlsx' });
  await file.press('Enter');
  await expect(page.getByLabel('Источник документа', { exact: true }).and(page.locator('.source-workspace-panel[open]')))
    .toBeVisible();
  await expect(page).toHaveURL(/document=ledger-copy.*#exceptions$/);
  await page.keyboard.press('Escape');
  await expect(file).toBeFocused();
  await expect(page).toHaveURL(/\/documents#exceptions$/);
});

test('reading filters separate partial, pending and legacy states without changing decisions', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const id = 'reading-states';
  await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  const [report, included, duplicate, broken] = example.result.documents;
  const { parse_status: omitted, ...legacy } = report;
  expect(omitted).toBe('parsed');
  await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({ json: {
    ...example.result, run_id: id, documents: [
      legacy, { ...included, parse_status: 'partial', errors: [
        { id: 'partial-sheet', code: 'partial_sheet', message: 'Часть листа недоступна.' },
      ] },
      { ...duplicate, parse_status: 'pending' }, broken,
    ],
  } }));

  await page.goto(`/checks/${id}/documents`);
  const filters = page.getByRole('group', { name: 'Статус файла' });
  const table = page.getByRole('region', { name: 'Таблица документов' });
  await expect(table.getByText('Чтение не указано')).toBeVisible();
  await expect(table.getByText('Ожидает чтения')).toBeVisible();
  await filters.getByRole('button', { name: 'Прочитано (0)' }).click();
  await expect(table.getByText('Документов с этим статусом нет.')).toBeVisible();
  await filters.getByRole('button', { name: 'Ошибочные (2)' }).click();
  await expect(table.getByText('Чтение не указано')).toHaveCount(0);
  await expect(table.getByText('Ожидает чтения')).toHaveCount(0);
  const partial = table.getByRole('row').filter({ hasText: included.name });
  await expect(partial.getByText('Прочитано частично')).toBeVisible();
  await expect(partial.getByText('Включён', { exact: true })).toBeVisible();
  await expect(table.getByText('Не удалось прочитать')).toBeVisible();
});

test('diagnostics return keyboard focus and the documents route restores selected evidence', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/checks/synthetic-example');
  await page.getByRole('link', { name: 'Исключения', exact: true }).press('Enter');
  const exceptions = page.getByRole('region', { name: 'Исключения', exact: true });
  const excludedDocument = exceptions.getByRole('button', { name: 'synthetic-ledger-copy.xlsx' });
  const source = page.getByRole('region', { name: 'Источник документа', exact: true });
  await excludedDocument.press('Enter');
  await expect(source.getByLabel('Документы комплекта')).toHaveValue('ledger-copy');
  await page.keyboard.press('Escape');
  await expect(excludedDocument).toBeFocused();

  await page.goto('/checks/synthetic-example/documents?document=report&evidence=report-a');
  const documents = source.getByLabel('Документы комплекта');
  await expect(documents).toHaveValue('report');
  await expect(page.getByRole('button', { name: 'Закрыть просмотр источника' })).toBeFocused();
  await documents.selectOption('ledger');
  await source.getByLabel('Адрес доказательства').selectOption('amount-2');
  await expect(page).toHaveURL(/document=ledger&evidence=amount-2/);
  await page.reload();
  await expect(documents).toHaveValue('ledger');
  await expect(source.getByLabel('Адрес доказательства')).toHaveValue('amount-2');
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(/\/documents$/);
});

test('a selected report row survives a reload and keeps its page', async ({ page }) => {
  const id = 'report-scope';
  const [report, ...others] = example.result.documents;
  const result = {
    ...example.result, run_id: id, documents: [report, ...others],
    scope: { ...example.result.scope, report_row_locator: { kind: 'page', page: 2, line: 4 } },
  };
  await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed', created_at: '2026-11-14T00:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({ json: result }));
  await page.route(`**/api/v0/runs/${id}/documents/${report.id}`, (route) => route.fulfill({
    body: '%PDF-1.4 synthetic original', contentType: 'application/octet-stream',
  }));
  await page.route(`**/api/v0/runs/${id}/documents/${report.id}/page-preview?*`, (route) =>
    route.fulfill({ status: 404, json: { code: 'page_not_found' } }));

  await page.goto(`/checks/${id}/documents#exceptions`);
  await page.getByRole('button', { name: 'Открыть просмотр документов' }).click();
  const picker = page.getByRole('combobox', { name: 'Адрес доказательства' });
  await picker.selectOption({ label: 'Строка КФЗ · Страница 2, строка 4' });
  await expect(page).toHaveURL(/document=report&anchor=report-row#exceptions$/);
  await page.reload();
  await expect(picker.locator('option:checked')).toHaveText('Строка КФЗ · Страница 2, строка 4');
  await expect(page.getByRole('link', { name: 'Открыть страницу 2 PDF (в новой вкладке)' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(/\/documents#exceptions$/);
});

test('a distinct primary issue remains visible beside the related file error', async ({ page }) => {
  const id = 'diagnostic-issue';
  const result = example.result;
  const detail = 'Проверьте наличие читаемого скана в новом комплекте.';
  await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null, progress: { processed_documents: 4, total_documents: 4 },
  } }));
  await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({ json: {
    ...result, run_id: id, summary: {
      ...result.summary, primary_issues: [
        ...result.summary.primary_issues.map((issue) => issue.id === 'issue-a' ? {
          ...issue, message: 'Сверьте договор в сопроводительном файле.',
          evidence_refs: [...issue.evidence_refs, 'report-b'],
        } : issue), {
        id: 'extra-scan-diagnostic', code: 'request_rescan', message: detail,
        evidence_refs: [], file_error_refs: ['scan-read-error'],
      }],
    },
  } }));
  await page.goto('/checks/' + id);
  await page.getByRole('button', { name: 'Синтетическая статья A', exact: true }).click();
  const indicator = page.getByRole('region', { name: 'Подробности: Синтетическая статья A' });
  await expect(indicator.getByText('Сверьте договор в сопроводительном файле.', { exact: true })).toBeVisible();
  await expect(indicator.getByRole('list', { name: 'Источники замечания' })
    .getByRole('button', { name: /synthetic-report\.pdf/ })).toBeVisible();
  const diagnostics = page.getByRole('region', { name: 'Дополнительные проверки' });
  await expect(diagnostics.getByText(detail, { exact: true })).toBeVisible();
  await diagnostics.getByRole('link', { name: 'Исключения', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Исключения', exact: true })
    .getByText('Ошибка чтения файла', { exact: true })).toBeVisible();
});
