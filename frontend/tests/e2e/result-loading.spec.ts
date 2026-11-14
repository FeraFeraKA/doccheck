import { expect, test } from '@playwright/test';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

const runId = 'slow-result';
const resultUrl = '/checks/' + runId;
const runPath = '/api/v0/runs/' + runId;
const summary = { run_id: runId, status: 'completed', created_at: '2026-11-14T10:00:00Z', error: null };

function delayResponse() {
  let release!: () => void;
  const wait = new Promise<void>((resolve) => { release = resolve; });
  return { wait, release };
}

for (const { width, from, section, contents, columns } of [
  { width: 390, from: '/documents', section: 'Документы', contents: 'Таблица документов', columns: 8 },
  { width: 1440, from: '/checks', section: 'Результат проверки', contents: 'Таблица показателей', columns: 6 },
]) {
  test('keeps the result skeleton through both API requests at ' + width + 'px', async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.route('**/api/v0/runs', (route) => route.fulfill({ json: { items: [summary], next_cursor: null } }));
    const status = delayResponse();
    await page.route('**' + runPath, async (route) => {
      await status.wait;
      await route.fulfill({ json: { ...summary, progress: { processed_documents: 4, total_documents: 4 } } });
    });
    const findings = delayResponse();
    await page.route('**' + runPath + '/findings', async (route) => {
      await findings.wait;
      await route.fulfill({ json: { ...example.result, run_id: runId } });
    });

    try {
      if (from === '/checks') {
        await page.goto(from);
        await page.getByRole('link', { name: 'Проверка КФЗ №' + runId }).click();
      } else {
        await page.goto(resultUrl + from);
      }

      const loading = page.getByRole('region', { name: section, exact: true }).and(page.locator('[aria-busy=true]'));
      await expect(loading).toBeVisible();
      await expect(loading.locator('thead th')).toHaveCount(columns);
      const titleBlock = loading.locator('.check-skeleton-title');
      await expect(titleBlock).toHaveCSS('animation-name', 'none');
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      const before = await loading.boundingBox();
      const sameNode = await loading.elementHandle();

      const requestedFindings = page.waitForRequest('**' + runPath + '/findings');
      status.release();
      await requestedFindings;
      await expect(loading).toBeVisible();
      expect(await loading.boundingBox()).toEqual(before);
      expect(await sameNode?.evaluate((node) => node.isConnected)).toBe(true);
      await expect(page.getByRole('status')).toHaveText('Загрузка проверки…');

      findings.release();
      await expect(loading).toHaveCount(0);
      await expect(page.getByRole('region', { name: contents, exact: true })).toBeVisible();
      await expect(page.getByRole('navigation', { name: 'Разделы проверки' })).toBeVisible();
    } finally {
      status.release();
      findings.release();
    }
  });
}

test('the pack editor shows its upload cards while the stored pack is loading', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await page.route('**/api/v0/runs', (route) => route.fulfill({ json: { items: [], next_cursor: null } }));
  const pack = delayResponse();
  await page.route('**' + runPath + '/pack', async (route) => {
    await pack.wait;
    await route.fulfill({ json: {
      documents: [{ id: 'report', name: 'report.pdf', size: 100, role: 'report' }],
    } });
  });

  try {
    await page.goto('/checks/new?from=' + runId);
    const loading = page.getByRole('region', { name: 'Комплект документов' });
    await expect(page.getByRole('heading', { name: 'Изменить комплект' })).toBeVisible();
    await expect(loading.locator('.upload-card')).toHaveCount(2);
    await expect(loading).toBeVisible();
    await expect(loading).toHaveAttribute('aria-busy', 'true');
    await expect(page.getByRole('link', { name: 'К результату' })).toHaveAttribute('href', resultUrl);
    await expect(page.getByRole('status')).toHaveText('Загружаем список документов…');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    pack.release();
    await expect(loading).toHaveCount(0);
    await expect(page.getByRole('region', { name: 'КФЗ', exact: true })).toContainText('report.pdf');
    await expect(page.getByRole('region', { name: 'Первичные документы' })).toBeVisible();
  } finally {
    pack.release();
  }
});
