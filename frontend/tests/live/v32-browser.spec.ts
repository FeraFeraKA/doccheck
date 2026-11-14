import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import { isRunId } from '../../src/pages/checks/runStatusApi';

const packages = [
  { name: 'first', contract: 'TEST-5', partial: /9\s000,00/ },
  { name: 'changed', contract: 'TEST-6', partial: /8\s112,50/ },
];

for (const { name, contract, partial } of packages) {
  test(`real v3.2 upload opens DOCX source for ${name} package`, async ({ page }, testInfo) => {
    const report = fileURLToPath(new URL(`../../../data/nrt-43-live/${name}/report.xlsx`, import.meta.url));
    const act = fileURLToPath(new URL(`../../../data/nrt-43-live/${name}/act.docx`, import.meta.url));
    await page.goto('/checks/new');
    await page.getByLabel('Выберите КФЗ', { exact: true }).setInputFiles(report);
    await page.getByLabel('Выберите первичные документы', { exact: true }).setInputFiles(act);

    const [accepted] = await Promise.all([
      page.waitForResponse((response) => response.request().method() === 'POST'
        && /^\/api\/v0\/runs\/uploads\/[^/]+\/start$/.test(new URL(response.url()).pathname)),
      page.getByRole('button', { name: 'Запустить проверку' }).click(),
    ]);
    expect(accepted.status()).toBe(202);
    const { run_id: runId } = await accepted.json();
    if (!isRunId(runId)) throw new Error('The API did not return a valid run ID.');
    expect(accepted.headers().location).toBe(`/api/v0/runs/${runId}`);
    await testInfo.attach('run-id', { body: runId, contentType: 'text/plain' });
    const queue = page.getByRole('region', { name: 'Последние проверки' });
    await queue.locator(`a[href="/checks/${runId}"]`).click({ timeout: 240_000 });
    await expect(page).toHaveURL(`/checks/${runId}`);

    const table = page.getByRole('table', { name: 'Показатели КФЗ' });
    await expect.poll(async () => {
      if (await table.isVisible()) return 'result';
      if (await page.getByRole('alert').first().isVisible()) return 'error';
      return 'pending';
    }, { timeout: 240_000, intervals: [250, 1_000, 2_000] }).not.toBe('pending');
    await expect(table, 'The stored reconciliation must appear after the worker finishes.').toBeVisible();
    await expect(page.getByText(contract, { exact: false }).first()).toBeVisible();
    const row = table.getByRole('row').filter({ has: page.getByRole('button', { name: 'Общехозяйственные расходы', exact: true }) });
    await expect(row.getByRole('cell', { name: /10\s000,00/ })).toBeVisible();
    await expect(row.getByRole('cell', { name: 'Не проверен', exact: true })).toBeVisible();
    await expect(row.getByText(/Частичная сумма:/)).toContainText(partial);
    await expect(row.getByRole('cell', { name: '—', exact: true }).last()).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath('result.png') });

    await row.getByRole('button', { name: 'Общехозяйственные расходы' }).click();
    const detail = page.getByRole('region', { name: 'Подробности: Общехозяйственные расходы' });
    await detail.getByText('Адреса и основание', { exact: true }).first().click();
    const [fragmentResponse, fileResponse] = await Promise.all([
      page.waitForResponse((response) => new URL(response.url()).pathname.startsWith(`/api/v0/runs/${runId}/documents/`)
        && new URL(response.url()).pathname.endsWith('/fragments')),
      page.waitForResponse((response) => /^\/api\/v0\/runs\/[^/]+\/documents\/[^/]+$/.test(new URL(response.url()).pathname)
        && new URL(response.url()).pathname.startsWith(`/api/v0/runs/${runId}/documents/`)),
      detail.getByRole('button', { name: /Сумма · act\.docx · Абзац 6/ }).click(),
    ]);
    expect(fragmentResponse.status()).toBe(200);
    expect(fileResponse.status()).toBe(200);
    expect(await fileResponse.body()).toEqual(await readFile(act));
    const viewer = page.getByRole('region', { name: 'Просмотр источника' });
    await expect(viewer.getByText('Абзац 6', { exact: true })).toBeVisible();
    await expect(viewer.getByText(partial).last()).toBeVisible();
    await expect(viewer.getByRole('link', { name: 'Скачать оригинал' })).toHaveAttribute('download', 'act.docx');
    await page.screenshot({ path: testInfo.outputPath('source.png') });
    console.log(`${name}: ${runId}`);
  });
}
