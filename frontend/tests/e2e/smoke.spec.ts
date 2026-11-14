import { expect, test } from '@playwright/test';

test('the old system status address opens the new check form', async ({ page }) => {
  const diagnosticRequests: string[] = [];
  page.on('request', (request) => {
    const { pathname } = new URL(request.url());
    if (pathname === '/health' || pathname.startsWith('/api/synthetic-jobs')) {
      diagnosticRequests.push(pathname);
    }
  });
  await page.route('**/api/v0/runs*', (route) => route.fulfill({ json: { items: [], next_cursor: null } }));

  await page.goto('/system-status');
  await expect(page).toHaveURL(/\/checks\/new$/);
  await expect(page.getByRole('heading', { name: 'Новая проверка', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Проверка системы' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Создать синтетическое задание' })).toHaveCount(0);
  expect(diagnosticRequests).toEqual([]);
});
