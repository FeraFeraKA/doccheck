import { expect, test } from '@playwright/test';

test('the result opens with a compact summary and retains legacy document routes', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/checks/synthetic-example');
  const tabs = page.getByRole('navigation', { name: 'Разделы проверки' });
  await expect(tabs.getByRole('link')).toHaveCount(2);
  await expect(tabs.getByRole('link', { name: 'Результат' })).toHaveAttribute('aria-current', 'page');
  const conclusion = page.getByRole('region', { name: 'Заключение по проверке' });
  await expect(conclusion.getByRole('list', { name: 'Счётчики показателей' })).toBeVisible();
  const table = page.getByRole('table', { name: 'Показатели КФЗ' });
  await expect(table.getByRole('columnheader')).toHaveText(
    ['Показатель КФЗ', 'В КФЗ', 'Ожидаемо', 'Разница Δ', 'Статус', 'Пояснение'],
  );
  expect((await conclusion.boundingBox())?.y).toBeLessThan((await table.boundingBox())?.y ?? 0);
  await expect(conclusion.getByRole('heading', { name: 'Недостоверен' })).toBeVisible();
  await expect(conclusion.getByText(/По статье A обнаружено расхождение/)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Найденные проблемы' })).toHaveCount(0);
  const indicator = page.getByRole('button', { name: 'Синтетическая статья A', exact: true });
  await indicator.click();
  await expect(indicator).toHaveAttribute('aria-expanded', 'true');
  const diagnostics = page.getByRole('region', { name: 'Дополнительные проверки' });
  await diagnostics.getByRole('link', { name: 'Исключения' }).click();
  await expect(page).toHaveURL(/\/documents\?filter=excluded$/);
  await expect(tabs.getByRole('link', { name: 'Документы' })).toHaveAttribute('aria-current', 'page');
  const exceptions = page.getByRole('region', { name: 'Таблица документов', exact: true });
  await expect(exceptions.getByText('Ошибка чтения', { exact: true })).toBeVisible();
  await tabs.getByRole('link', { name: 'Документы' }).click();
  await expect(page).toHaveURL(/\/documents$/);
  await expect(page.getByText('synthetic-report.pdf', { exact: true })).toBeVisible();
  await page.goto('/checks/synthetic-example/exceptions');
  await expect(page.getByRole('button', { name: /^Исключены/ })).toHaveAttribute('aria-pressed', 'true');
  await expect(tabs.getByRole('link', { name: 'Документы' })).toHaveAttribute('aria-current', 'page');
  await page.goto('/checks/synthetic-example/conclusion');
  await expect(page.getByRole('button', { name: 'Принять и скачать заключение' })).toHaveCount(0);
  await expect(tabs.getByRole('link', { name: 'Результат' })).toHaveAttribute('aria-current', 'page');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
