import { expect, test } from '@playwright/test';

test('открывается стартовая страница приложения', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'DocCheck' })).toBeVisible();
  await expect(page.getByText('Интерфейс проверки документов находится в разработке.')).toBeVisible();
});
