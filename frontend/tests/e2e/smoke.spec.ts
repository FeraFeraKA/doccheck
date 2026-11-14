import { expect, test } from '@playwright/test';
import { jobId, syntheticJob } from '../fixtures/syntheticJob';

test('system status remains reachable with the compact sidebar', async ({ page }) => {
  await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok', database: 'ok' } }));
  for (const width of [320, 700, 701, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    const sidebar = page.getByRole('complementary');
    const navigation = sidebar.getByRole('navigation', { name: 'Основная навигация' });
    await expect(sidebar.getByText('Бухгалтер', { exact: true })).toHaveCount(0);
    const link = page.getByRole('link', { name: 'Проверка системы', exact: true });
    await expect(link).toHaveCount(1);
    if (width <= 700) {
      await expect(sidebar.getByRole('link', { name: 'Проверка системы' })).toHaveCount(0);
      const sidebarBox = await sidebar.boundingBox();
      const navigationBox = await navigation.boundingBox();
      if (!sidebarBox || !navigationBox) throw new Error('Навигация недоступна');
      expect(sidebarBox.y + sidebarBox.height - (navigationBox.y + navigationBox.height)).toBeLessThanOrEqual(1);
    } else {
      await expect(sidebar.getByRole('link', { name: 'Проверка системы' })).toBeInViewport();
    }
    await link.click();
    await expect(page).toHaveURL(/\/system-status$/);
    await expect(page.getByText('API и PostgreSQL доступны.')).toBeVisible();
  }
});

test('synthetic API mock: queued → processing → completed', async ({ page }) => {
  await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok', database: 'ok' } }));
  await page.route('**/api/synthetic-jobs', (route) => route.fulfill({ status: 201, json: syntheticJob('queued') }));
  let pollCount = 0;
  await page.route(`**/api/synthetic-jobs/${jobId}`, (route) => {
    pollCount += 1;
    return route.fulfill({ json: syntheticJob(pollCount === 1 ? 'processing' : 'completed') });
  });
  await page.goto('/system-status');
  await expect(page.getByRole('heading', { name: 'DocCheck' })).toBeVisible();
  await expect(page.getByText('API и PostgreSQL доступны.')).toBeVisible();
  await page.getByRole('button', { name: 'Создать синтетическое задание' }).click();
  await expect(page.getByText('Статус: В очереди')).toBeVisible();
  await expect(page.getByText('Статус: Обрабатывается')).toBeVisible();
  await expect(page.getByText('Статус: Завершено')).toBeVisible();
  await expect(page.getByText('Тестовый результат: Синтетическая проверка завершена.')).toBeVisible();
  await expect(page.getByText('OCR и настоящая финансовая сверка здесь не выполняются.')).toBeVisible();
});

test('API mock: ошибка связи и восстановление после повторной проверки', async ({ page }) => {
  await page.route('**/health', (route) => route.abort('connectionrefused'));
  await page.goto('/system-status');
  await expect(page.getByRole('alert')).toContainText('Нет связи с API.');
  await expect(page.getByRole('button', { name: 'Создать синтетическое задание' })).toBeDisabled();
  await page.unroute('**/health');
  await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok', database: 'ok' } }));
  await page.getByRole('button', { name: 'Проверить связь' }).click();
  await expect(page.getByText('API и PostgreSQL доступны.')).toBeVisible();
});
