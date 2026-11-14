import { expect, test } from '@playwright/test';

const viewports = [
  { width: 320, rail: 320 }, { width: 700, rail: 700 },
  { width: 701, rail: 210 }, { width: 768, rail: 210 },
  { width: 1250, rail: 210 }, { width: 1251, rail: 240 },
  { width: 1650, rail: 240 },
];

for (const { width, rail } of viewports) {
  test(`persistent navigation and system status are reachable at ${width}px`, async ({ page }) => {
    await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok', database: 'ok' } }));
    await page.route('**/api/v0/runs', (route) => route.fulfill({ json: { items: [], next_cursor: null } }));
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');

    const sidebar = page.getByRole('complementary', { name: 'Меню DocCheck' });
    const navigation = sidebar.getByRole('navigation', { name: 'Основная навигация' });
    const newCheck = navigation.getByRole('link', { name: 'Новая проверка', exact: true });
    const checks = navigation.getByRole('link', { name: 'Проверки', exact: true });
    await expect(newCheck).toHaveAttribute('aria-current', 'page');
    await expect(checks.getByText('Проверки', { exact: true })).toBeInViewport();
    await expect(sidebar.getByRole('button')).toHaveCount(0);
    const main = page.getByRole('main');
    const sidebarBounds = await sidebar.boundingBox();
    const mainBounds = await main.boundingBox();
    if (!sidebarBounds || !mainBounds) throw new Error('Место навигации недоступно');
    expect(sidebarBounds.width).toBe(rail);
    expect(mainBounds.x).toBe(width <= 700 ? 0 : rail);
    if (width <= 700) {
      expect(mainBounds.y).toBe(sidebarBounds.y + sidebarBounds.height);
    } else {
      const padding = width >= 1650 ? '48px' : width <= 1250 ? '24px' : '36px';
      await expect(main).toHaveCSS('padding-left', padding);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);

    await checks.press('Enter');
    await expect(checks).toHaveAttribute('aria-current', 'page');
    await expect(page).toHaveURL(/\/checks$/);
    await expect(navigation).toBeVisible();
    const status = page.getByRole('link', { name: 'Проверка системы', exact: true });
    await expect(status).toHaveCount(1);
    await expect(status).toBeVisible();
    await status.click();
    await expect(page).toHaveURL(/\/system-status$/);
    await expect(page.getByText('API и PostgreSQL доступны.')).toBeVisible();
  });
}
