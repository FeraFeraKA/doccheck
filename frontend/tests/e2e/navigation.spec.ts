import { expect, test } from '@playwright/test';

test('Tab scrolls the fixed sidebar to system status in a short window', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 200 });
  await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok', database: 'ok' } }));
  await page.goto('/');

  const sidebar = page.getByRole('complementary', { name: 'Меню DocCheck' });
  const status = sidebar.getByRole('link', { name: 'Проверка системы', exact: true });
  const scroll = () => sidebar.evaluate((element) => element.scrollTop);
  expect(await scroll()).toBe(0);
  await expect(status).not.toBeInViewport();
  for (const name of ['DocCheck', 'Новая проверка', 'Проверки', 'Проверка системы']) {
    await page.keyboard.press('Tab');
    await expect(sidebar.getByRole('link', { name, exact: true })).toBeFocused();
  }
  await expect(status).toBeInViewport({ ratio: 1 });
  await expect(sidebar).toHaveCSS('width', '220px');
  expect(await scroll()).toBeGreaterThan(0);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);

  const bounds = await status.boundingBox();
  if (!bounds) throw new Error('Ссылка проверки системы недоступна');
  await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await expect(page).toHaveURL(/\/system-status$/);
  await expect(page.getByText('API и PostgreSQL доступны.')).toBeVisible();
});

for (const width of [701, 768, 1250, 1251, 1650]) {
  test('desktop navigation overlays content at ' + width + 'px', async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    const sidebar = page.getByRole('complementary', { name: 'Меню DocCheck' });
    const navigation = sidebar.getByRole('navigation', { name: 'Основная навигация' });
    const checks = navigation.getByRole('link', { name: 'Проверки', exact: true });
    await expect(navigation.getByRole('link', { name: 'Новая проверка' })).toHaveAttribute('aria-current', 'page');
    await expect(sidebar.getByRole('button', { name: 'Меню разделов' })).toHaveCount(0);
    await expect(sidebar).toHaveCSS('width', '64px');
    const main = page.getByRole('main');
    const padding = width >= 1650 ? '48px' : width <= 1250 ? '24px' : '36px';
    await expect(main).toHaveCSS('padding-left', padding);
    expect((await main.boundingBox())?.x).toBe(64);
    await sidebar.hover({ position: { x: 30, y: 30 } });
    await expect(sidebar).toHaveCSS('width', '220px');
    await expect(checks.getByText('Проверки')).toHaveCSS('opacity', '1');
    expect((await main.boundingBox())?.x).toBe(64);
    await page.mouse.move(width - 4, 5);
    await expect(sidebar).toHaveCSS('width', '64px');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

for (const width of [320, 700]) {
  test('the mobile logo toggles navigation and Escape restores focus at ' + width + 'px', async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route('**/api/v0/runs', (route) => route.fulfill({ json: { items: [], next_cursor: null } }));
    await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok', database: 'ok' } }));
    await page.goto('/');
    const sidebar = page.getByRole('complementary', { name: 'Меню DocCheck' });
    const trigger = sidebar.getByRole('button', { name: 'Меню разделов' });
    const navigation = sidebar.getByRole('navigation', { name: 'Основная навигация' });
    await expect(navigation).toBeHidden();
    await trigger.press('Enter');
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    const checks = navigation.getByRole('link', { name: 'Проверки', exact: true });
    await checks.focus();
    await page.keyboard.press('Escape');
    await expect(navigation).toBeHidden();
    await expect(trigger).toBeFocused();
    await trigger.click();
    await checks.click();
    await expect(page).toHaveURL(/\/checks$/);
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(trigger).toBeFocused();
    await page.getByRole('link', { name: 'Проверка системы' }).click();
    await expect(page).toHaveURL(/\/system-status$/);
  });
}

test.describe('touch tablet', () => {
  test.use({ hasTouch: true, viewport: { width: 768, height: 900 } });

  test('the logo opens or closes the icon rail without moving the content', async ({ page }) => {
    await page.route('**/api/v0/runs', (route) => route.fulfill({ json: { items: [], next_cursor: null } }));
    await page.goto('/');
    const sidebar = page.getByRole('complementary');
    const trigger = sidebar.getByRole('button', { name: 'Меню разделов' });
    await expect(sidebar).toHaveCSS('width', '64px');
    await trigger.tap();
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await expect(sidebar).toHaveCSS('width', '220px');
    expect((await page.getByRole('main').boundingBox())?.x).toBe(64);
    await trigger.tap();
    await expect(sidebar).toHaveCSS('width', '64px');
    await trigger.tap();
    await sidebar.getByRole('link', { name: 'Проверки', exact: true }).tap();
    await expect(page).toHaveURL(/\/checks$/);
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await expect(sidebar).toHaveCSS('width', '64px');
    await expect(sidebar.getByRole('link', { name: 'Проверки', exact: true })).toBeFocused();
  });
});

test('Escape dismisses hover navigation without taking focus from the search or modal', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/checks/synthetic-example');
  const sidebar = page.getByRole('complementary');
  const search = page.getByRole('searchbox', { name: 'Поиск показателя или документа' });
  await search.focus();
  await sidebar.hover({ position: { x: 30, y: 30 } });
  await expect(sidebar).toHaveCSS('width', '220px');
  await page.keyboard.press('Escape');
  await expect(sidebar).toHaveCSS('width', '64px');
  await expect(search).toBeFocused();

  const fullscreen = page.getByRole('button', { name: 'На весь экран', exact: true });
  await fullscreen.click();
  const dialog = page.getByRole('dialog', { name: 'Полноэкранная сверка' });
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(fullscreen).toBeFocused();
});

test('the expanded desktop rail does not cover history pagination', async ({ page }) => {
  await page.setViewportSize({ width: 701, height: 900 });
  await page.route(/\/api\/v0\/runs(?:\?.*)?$/, (route) => {
    const older = new URL(route.request().url()).searchParams.has('cursor');
    return route.fulfill({ json: {
      items: [{
        run_id: older ? 'older-run' : 'recent-run', status: 'queued',
        created_at: '2026-11-14T10:00:00Z', error: null,
      }],
      next_cursor: older ? null : 'next-page',
    } });
  });
  await page.goto('/checks');
  const sidebar = page.getByRole('complementary', { name: 'Меню DocCheck' });
  const older = page.getByRole('link', { name: 'Более ранние проверки' });
  await sidebar.hover({ position: { x: 30, y: 30 } });
  await expect(sidebar).toHaveCSS('width', '220px');
  const reachable = await older.evaluate((element) => {
    const { x, y, width, height } = element.getBoundingClientRect();
    return element.contains(document.elementFromPoint(x + width / 2, y + height / 2));
  });
  expect(reachable).toBe(true);
  await older.click();
  await expect(page.getByRole('link', { name: 'Проверка older-run', exact: true })).toBeVisible();
});

test('Escape immediately restores breadcrumb clicks with animations enabled', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.route('**/api/v0/runs', (route) => route.fulfill({ json: { items: [], next_cursor: null } }));
  await page.goto('/checks/synthetic-example');
  const breadcrumb = page.getByRole('link', { name: 'Все проверки', exact: true });
  const bounds = await breadcrumb.boundingBox();
  if (!bounds) throw new Error('Ссылка на список проверок недоступна');
  const target = { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };
  const sidebar = page.getByRole('complementary', { name: 'Меню DocCheck' });
  await page.mouse.move(25, target.y);
  await expect(sidebar).toHaveCSS('width', '220px');

  await page.keyboard.press('Escape');
  // Click through the shrinking area without letting Playwright wait for actionability.
  await page.mouse.click(target.x, target.y);
  await expect(page).toHaveURL(/\/checks$/);
});
