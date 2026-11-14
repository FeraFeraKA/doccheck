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
  await expect(page.getByRole('table')).toHaveCount(1);
  await expect(page.getByRole('link', { name: 'К исключениям' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Скачать XLSX' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'В архив' })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const duplicate = table.getByRole('row').filter({ hasText: 'synthetic-ledger-copy.xlsx' });
  await expect(duplicate.getByText('Исключён', { exact: true })).toBeVisible();
  await expect(table.getByText('Ошибка чтения', { exact: true })).toBeVisible();
  await filters.getByRole('button', { name: 'Прочитано (2)' }).click();
  await expect(page).toHaveURL(/\/documents\?filter=read$/);
  await expect(table.getByRole('row')).toHaveCount(3);
  await expect(duplicate).toHaveCount(0);
  await expect(table.getByText('Ошибка чтения', { exact: true })).toHaveCount(0);
  await filters.getByRole('button', { name: 'Исключены (2)' }).click();
  await expect(page).toHaveURL(/\/documents\?filter=excluded$/);
  await expect(table.getByRole('row')).toHaveCount(3);
  await expect(duplicate.getByText('Операции уже учтены из выбранного экземпляра')).toBeVisible();
  await expect(table.getByText('Ошибка чтения', { exact: true })).toBeVisible();
  await expect(table.getByText('Основание', { exact: true })).toHaveCount(0);
  await page.goBack();
  await expect(filters.getByRole('button', { name: 'Прочитано (2)' })).toHaveAttribute('aria-pressed', 'true');
  await expect(duplicate).toHaveCount(0);
  await page.goForward();
  await expect(filters.getByRole('button', { name: 'Исключены (2)' })).toHaveAttribute('aria-pressed', 'true');
  await expect(duplicate).toHaveCount(1);
  await filters.getByRole('button', { name: 'Все (4)' }).click();
  const file = table.getByRole('button', { name: 'synthetic-ledger.xlsx', exact: true });
  await file.press('Enter');
  const dialog = page.getByLabel('Источник документа', { exact: true }).and(page.locator('.source-workspace-panel[open]'));
  await expect(dialog.getByText(/^Оригинал (в готовом примере|документа) недоступен\.$/)).toBeVisible();
  await expect(dialog.getByRole('combobox', { name: 'Документы комплекта' })).toHaveValue('ledger');
  await expect(dialog.getByRole('combobox')).toHaveCount(1);
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
  const filters = page.getByRole('group', { name: 'Статус файла' });
  await expect(filters.getByRole('button', { name: 'Исключены (2)' })).toHaveAttribute('aria-pressed', 'true');
  const table = page.getByRole('region', { name: 'Таблица документов' });
  await expect(page.getByRole('table')).toHaveCount(1);
  await expect(table.getByRole('row')).toHaveCount(3);
  await expect(table.getByRole('link', { name: 'Синтетическая статья B' })).toHaveCount(1);
  const file = table.getByRole('button', { name: example.result.documents[3].name });
  await file.click();
  const dialog = page.getByLabel('Источник документа', { exact: true }).and(page.locator('.source-workspace-panel[open]'));
  await expect(dialog.getByRole('combobox', { name: 'Документы комплекта' })).toHaveValue('unreadable');
  await expect(dialog.getByRole('combobox', { name: 'Адрес доказательства' })).toHaveCount(0);
  await expect(dialog.getByRole('alert')).toBeVisible();
  expect([...new Set(originals)]).toEqual([`/api/v0/runs/${id}/documents/unreadable`]);
  await page.keyboard.press('Escape');
  await expect(file).toBeFocused();
});

test('the exception filter restores the source from browser history', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/checks/synthetic-example/documents?filter=excluded');
  const filters = page.getByRole('group', { name: 'Статус файла' });
  const excluded = filters.getByRole('button', { name: 'Исключены (2)' });
  const all = filters.getByRole('button', { name: 'Все (4)' });
  await expect(excluded).toHaveAttribute('aria-pressed', 'true');
  const table = page.getByRole('region', { name: 'Таблица документов' });
  const file = table.getByRole('button', { name: 'synthetic-ledger-copy.xlsx' });
  const source = page.getByRole('region', { name: 'Источник документа', exact: true });
  await file.press('Enter');
  await expect(source).toBeVisible();
  await expect(page).toHaveURL(/\/documents\?filter=excluded&document=ledger-copy$/);
  await all.click();
  await expect(page).toHaveURL(/\/documents\?document=ledger-copy$/);
  await page.keyboard.press('Escape');
  await expect(file).toBeFocused();
  await expect(page).toHaveURL(/\/documents$/);
  await page.goBack();
  await expect(excluded).toHaveAttribute('aria-pressed', 'true');
  await expect(source.getByLabel('Документы комплекта')).toHaveValue('ledger-copy');
  await page.goForward();
  await expect(all).toHaveAttribute('aria-pressed', 'true');
  await expect(source).toHaveCount(0);
});

test('reading filters separate partial, pending and legacy states without changing decisions', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const id = 'reading-states';
  await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z', error: null,
    progress: { processed_documents: 4, total_documents: 4 },
  } }));
  const [report, included, duplicate, broken] = example.result.documents;
  const legacyWithError = {
    ...included, id: 'legacy-error', name: 'legacy-error.xlsx', parse_status: undefined,
    errors: [{ id: 'legacy-file-error', code: 'file_error', message: 'Не удалось обработать лист старого файла.' }],
  };
  const pending = { ...included, id: 'pending', name: 'pending.xlsx', parse_status: 'pending' };
  await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({ json: {
    ...example.result, run_id: id, documents: [
      { ...report, parse_status: undefined }, { ...included, parse_status: 'partial', errors: [
        { id: 'partial-sheet', code: 'partial_sheet', message: 'Часть листа недоступна.' },
      ] },
      duplicate, broken, pending, legacyWithError,
    ],
  } }));

  await page.goto(`/checks/${id}/documents`);
  const filters = page.getByRole('group', { name: 'Статус файла' });
  const table = page.getByRole('region', { name: 'Таблица документов' });
  await expect(table.getByText('Чтение не указано')).toBeVisible();
  await expect(table.getByText('Ожидает чтения')).toBeVisible();
  await filters.getByRole('button', { name: 'Прочитано (0)' }).click();
  await expect(table.getByText('Документов с этим статусом нет.')).toBeVisible();
  await filters.getByRole('button', { name: 'Исключены (4)' }).click();
  await expect(table.getByText('Чтение не указано')).toHaveCount(0);
  await expect(table.getByText('Ожидает чтения')).toHaveCount(0);
  const partial = table.getByRole('row').filter({ hasText: included.name });
  await expect(partial.getByText('Прочитано частично')).toBeVisible();
  await expect(partial.getByText('Часть листа недоступна.')).toBeVisible();
  const legacyError = table.getByRole('row').filter({ hasText: legacyWithError.name });
  await expect(legacyError.getByText('Требует проверки', { exact: true })).toBeVisible();
  await expect(legacyError.getByText(legacyWithError.errors[0].message)).toBeVisible();
  await expect(table.getByText('Ошибка чтения', { exact: true })).toBeVisible();
});

test('diagnostics return keyboard focus and the documents route restores selected evidence', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/checks/synthetic-example');
  await page.getByRole('link', { name: 'Исключения', exact: true }).press('Enter');
  const table = page.getByRole('region', { name: 'Таблица документов' });
  await expect(page.getByRole('button', { name: 'Исключены (2)' })).toHaveAttribute('aria-pressed', 'true');
  const excludedDocument = table.getByRole('button', { name: 'synthetic-ledger-copy.xlsx' });
  const source = page.getByRole('region', { name: 'Источник документа', exact: true });
  await excludedDocument.press('Enter');
  await expect(source.getByLabel('Документы комплекта')).toHaveValue('ledger-copy');
  await page.keyboard.press('Escape');
  await expect(excludedDocument).toBeFocused();

  await page.goto('/checks/synthetic-example/documents?document=report&evidence=report-a');
  const documents = source.getByLabel('Документы комплекта');
  await expect(documents).toHaveValue('report');
  await expect(page.getByRole('button', { name: 'Закрыть просмотр источника' })).toBeFocused();
  await expect(source.getByText('Страница 1', { exact: true })).toBeVisible();
  await page.reload();
  await expect(documents).toHaveValue('report');
  await expect(source.getByText('Страница 1', { exact: true })).toBeVisible();
  await documents.selectOption('ledger');
  await expect(documents).toHaveValue('ledger');
  await expect(page).toHaveURL(/document=ledger$/);
  await expect(source.getByRole('combobox')).toHaveCount(1);
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

  await page.goto(`/checks/${id}/documents?document=report&anchor=report-row#exceptions`);
  await expect(page.getByRole('button', { name: 'Исключены (2)' })).toHaveAttribute('aria-pressed', 'true');
  const address = page.getByText('Строка КФЗ · Страница 2, строка 4', { exact: true });
  await expect(address).toBeVisible();
  await page.reload();
  await expect(address).toBeVisible();
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
  const issueSources = indicator.getByRole('list', { name: 'Источники замечания' });
  await expect(issueSources.getByRole('button', { name: /synthetic-report\.pdf/ })).toHaveCount(2);
  await expect(issueSources.getByRole('button', { name: /synthetic-report\.pdf.*строка 4, столбец 2/ })).toBeVisible();
  const diagnostics = page.getByRole('region', { name: 'Дополнительные проверки' });
  await expect(diagnostics.getByText(detail, { exact: true })).toBeVisible();
  await diagnostics.getByRole('link', { name: 'Исключения', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Таблица документов', exact: true })
    .getByText('Ошибка чтения файла', { exact: true })).toBeVisible();
});
