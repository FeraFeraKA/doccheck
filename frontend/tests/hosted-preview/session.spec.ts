import { expect, test } from '@playwright/test';

test('uses a Secure cookie and shows only the invited synthetic result', async ({ page }) => {
  const invitation = process.env.DOCCHECK_HOSTED_BROWSER_INVITE;
  if (!invitation) throw new Error('DOCCHECK_HOSTED_BROWSER_INVITE is required');
  await page.goto('/');
  await expect(page.getByText('Закрытое демо на синтетических документах')).toBeVisible();
  await expect(page.locator('input[type=file]')).toHaveCount(0);
  await page.getByLabel('Код приглашения').fill(invitation);
  await page.getByRole('button', { name: 'Войти' }).click();
  const items = page.getByRole('list', { name: 'Доступные проверки' }).getByRole('listitem');
  await expect(items).toHaveCount(1);
  await expect(items.first()).toContainText('Готово');
  const resultLink = page.getByRole('link', { name: 'Результат JSON' });
  const resultPath = await resultLink.getAttribute('href');
  if (!resultPath) throw new Error('Result link is missing');
  const response = await page.request.get(resultPath);
  expect(response.ok()).toBe(true);
  expect((await response.json()).synthetic).toBe(true);
  expect(response.headers()['cache-control'].split(',').map((item) => item.trim())).toContain('no-store');
  expect(await page.evaluate(() => document.cookie)).not.toContain('doccheck-preview');
  const cookie = (await page.context().cookies()).find(({ name }) => name === '__Host-doccheck-preview');
  expect(cookie?.secure).toBe(true);
  expect(cookie?.httpOnly).toBe(true);
  await page.reload();
  await expect(page.getByRole('link', { name: 'Выгрузка XLSX' })).toBeVisible();
});
