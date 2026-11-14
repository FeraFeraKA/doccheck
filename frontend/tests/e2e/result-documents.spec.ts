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
  await expect(duplicate.getByRole('cell', { name: 'Исключён', exact: true })).toBeVisible();
  await filters.getByRole('button', { name: 'Ошибочные (1)' }).click();
  await expect(duplicate).toHaveCount(0);
  await expect(table.getByRole('cell', { name: 'Не удалось прочитать', exact: true })).toBeVisible();
  await expect(table.getByRole('cell', { name: 'Ошибка чтения', exact: true })).toBeVisible();
  await filters.getByRole('button', { name: 'Все (4)' }).click();
  const file = table.getByRole('button', { name: 'synthetic-ledger.xlsx', exact: true });
  await file.press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Источник документа' });
  await expect(dialog.getByText('Оригинал в готовом примере недоступен.')).toBeVisible();
  await dialog.getByRole('combobox', { name: 'Адрес доказательства' }).selectOption('amount-2');
  await expect(dialog.getByRole('paragraph').filter({ hasText: 'Лист «Синтетика», C7' })).toBeVisible();
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
  await expect(filters.getByRole('button', { name: 'Все (2)' })).toBeVisible();
  await expect(filters.getByRole('button', { name: 'Включён', exact: false })).toHaveCount(0);
  await filters.getByRole('button', { name: 'Ошибка чтения (1)' }).click();
  const table = page.getByRole('region', { name: 'Таблица документов' });
  await expect(table.getByRole('row')).toHaveCount(2);
  await expect(table.getByRole('link', { name: 'Синтетическая статья B' })).toHaveCount(1);
  const file = table.getByRole('button', { name: example.result.documents[3].name });
  await file.click();
  const dialog = page.getByRole('dialog', { name: 'Источник документа' });
  await expect(dialog.getByText('Адрес фрагмента отсутствует.')).toBeVisible();
  await expect(dialog.getByRole('alert')).toBeVisible();
  expect([...new Set(originals)]).toEqual([`/api/v0/runs/${id}/documents/unreadable`]);
  await page.keyboard.press('Escape');
  await expect(file).toBeFocused();
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
