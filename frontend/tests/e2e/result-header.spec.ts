import { expect, test } from '@playwright/test';

test('the result opens with a conclusion and retains legacy document routes', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/checks/synthetic-example');
  const tabs = page.getByRole('navigation', { name: 'Разделы проверки' });
  await expect(tabs.getByRole('link')).toHaveCount(2);
  await expect(tabs.getByRole('link', { name: 'Результат' })).toHaveAttribute('aria-current', 'page');
  const summary = page.getByRole('region', { name: 'Заключение по проверке' });
  await expect(summary.getByRole('heading', { name: 'Есть расхождения' })).toBeVisible();
  await expect(summary.getByText(/По статье A обнаружено расхождение/)).toBeVisible();
  await expect(summary.getByText('0 из 2 подтверждено')).toBeVisible();
  await expect(summary.getByRole('button', { name: 'Скачать XLSX' })).toBeDisabled();
  await summary.getByRole('link', { name: 'Исключения' }).click();
  await expect(page).toHaveURL(/\/exceptions$/);
  await expect(tabs.getByRole('link', { name: 'Документы' })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByText('Ошибка чтения', { exact: true })).toBeVisible();
  await tabs.getByRole('link', { name: 'Документы' }).click();
  await expect(page).toHaveURL(/\/documents$/);
  await expect(page.getByText('synthetic-report.pdf', { exact: true })).toBeVisible();
  await page.goto('/checks/synthetic-example/conclusion');
  await expect(summary.getByRole('button', { name: 'Скачать XLSX' })).toBeDisabled();
  await expect(tabs.getByRole('link', { name: 'Результат' })).toHaveAttribute('aria-current', 'page');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
