import { expect, test } from '@playwright/test';

test('the result disclosure keeps each component and its source address selectable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/checks/synthetic-example');

  const table = page.getByRole('table', { name: 'Показатели КФЗ' });
  await expect(table.getByRole('button', { name: 'Как рассчитано' })).toHaveCount(0);
  await expect(table.getByRole('button', { name: 'Основание проверки' })).toHaveCount(0);
  const row = table.getByRole('button', { name: 'Синтетическая статья A' });
  await row.focus();
  await row.press('Enter');
  await expect(row).toHaveAttribute('aria-expanded', 'true');
  const details = table.getByRole('region', { name: 'Подробности: Синтетическая статья A' });
  const components = details.getByRole('list', { name: 'Слагаемые показателя: Синтетическая статья A' });
  const addresses = components.getByText('Адреса и основание', { exact: true });
  await addresses.nth(0).click();
  await addresses.nth(1).click();
  const amounts = components.getByRole('button', { name: /^Сумма · / });
  await expect(amounts).toHaveCount(2);
  await expect(amounts.nth(0)).toHaveText(/C6/);
  await expect(amounts.nth(1)).toHaveText(/C7/);
  await amounts.nth(1).click();
  await expect(amounts.nth(1)).toHaveAttribute('aria-pressed', 'true');
  const viewer = page.getByRole('region', { name: 'Источник документа' });
  await expect(viewer.getByText('Лист «Синтетика», C7', { exact: true })).toBeVisible();
  await expect(viewer.getByRole('combobox')).toHaveCount(1);
  await page.getByRole('button', { name: 'Закрыть просмотр источника' }).click();
  await expect(viewer).toHaveCount(0);
  await expect(amounts.nth(1)).toBeFocused();
  await row.press('Space');
  await expect(details).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('search finds document names and Alt+Arrow selects, opens and focuses an issue', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/checks/synthetic-example');

  const workspace = page.getByRole('region', { name: 'Рабочее место сверки' });
  const table = workspace.getByRole('table', { name: 'Показатели КФЗ' });
  const search = workspace.getByRole('searchbox', { name: 'Поиск показателя или документа' });
  const issue = table.getByRole('button', { name: 'Синтетическая статья A' });
  await search.fill('synthetic-ledger.xlsx');
  await expect(issue).toBeVisible();
  await expect(table.getByRole('button', { name: 'Синтетическая статья B' })).toHaveCount(0);
  await search.fill('synthetic-scan.png');
  await expect(table.getByRole('button', { name: 'Синтетическая статья B' })).toBeVisible();
  await expect(issue).toHaveCount(0);
  await search.fill('нет совпадений');
  await expect(workspace.getByText('Показатели не найдены.')).toBeVisible();
  await workspace.getByRole('button', { name: 'Сбросить фильтры' }).click();
  await expect(search).toHaveValue('');

  await workspace.getByRole('button', { name: 'Не проверено 1' }).click();
  await search.focus();
  await search.press('Alt+ArrowDown');
  await expect(issue).toHaveCount(0);
  await workspace.getByRole('button', { name: 'Следующее расхождение' }).focus();
  await page.keyboard.press('Alt+ArrowDown');
  await expect(issue).toBeFocused();
  await expect(issue).toHaveAttribute('aria-expanded', 'true');
  await expect(workspace.getByText('Расхождение 1 из 1')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1440);
});
