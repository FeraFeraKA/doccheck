import { basename, join } from 'node:path';
import { readFile, readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { expect, test } from '@playwright/test';
import { isRunId } from '../../src/pages/checks/runStatusApi';

const examples = fileURLToPath(new URL('../../../docs/case/examples/', import.meta.url));
const caseEnabled = process.env.DOCCHECK_LIVE_CASE === '1';
const missingEnabled = process.env.DOCCHECK_LIVE_CASE_MISSING === '1';

for (const missingPayroll of [false, true]) {
  test(`live v3.2 case PDF with ${missingPayroll ? 'payroll omitted' : 'all 22 primary documents'}`, async ({ page }, testInfo) => {
    test.skip(!caseEnabled || (missingPayroll && !missingEnabled),
      'Set DOCCHECK_LIVE_CASE=1 and, for the second package, DOCCHECK_LIVE_CASE_MISSING=1.');
    test.setTimeout(30 * 60_000);

    const filenames = (await readdir(examples)).filter((name) =>
      /^\d{2}_/.test(name) && /\.(pdf|xlsx|docx|png)$/i.test(name) && !name.startsWith('00_'),
    ).sort();
    expect(filenames).toHaveLength(23);
    const reports = filenames.filter((name) => /^01_.*\.pdf$/i.test(name));
    expect(reports).toHaveLength(1);
    const report = reports[0];
    const primary = filenames.filter((name) =>
      name !== report && (!missingPayroll || !name.startsWith('02_')),
    );
    expect(primary).toHaveLength(missingPayroll ? 17 : 22);

    await page.goto('/checks/new');
    await page.getByLabel('Выберите КФЗ', { exact: true }).setInputFiles(join(examples, report));
    await page.getByLabel('Выберите первичные документы', { exact: true })
      .setInputFiles(primary.map((name) => join(examples, name)));
    const [accepted] = await Promise.all([
      page.waitForResponse((response) => response.request().method() === 'POST'
        && new URL(response.url()).pathname === '/api/v0/runs'),
      page.getByRole('button', { name: 'Отправить на проверку' }).click(),
    ]);
    expect(accepted.status()).toBe(202);
    const { run_id: id } = await accepted.json();
    if (!isRunId(id)) throw new Error('The API did not return a valid run ID.');
    expect(accepted.headers().location).toBe(`/api/v0/runs/${id}`);
    await testInfo.attach('run-id', { body: id, contentType: 'text/plain' });
    console.log(`Case run: ${id}`);
    await expect(page).toHaveURL(`/checks/${id}`);

    const status = page.getByRole('status').filter({ hasText: 'Состояние проверки' });
    const indicators = page.getByRole('table', { name: 'Показатели КФЗ' });
    await expect.poll(async () => {
      if (await indicators.isVisible()) return 'result';
      if ((await status.textContent({ timeout: 2_000 }).catch(() => null))?.includes('Завершилась ошибкой')) {
        return 'failed';
      }
      return 'pending';
    }, { timeout: 25 * 60_000, intervals: [1_000, 3_000, 5_000] }).not.toBe('pending');
    await expect(indicators, `The worker must save a reconciliation for ${id}.`).toBeVisible();
    // The 2026 row intersects the stage through May 30, as printed in the PDF.
    // May 31 is a document cutoff from the case note, not a date read from the report.
    await expect(page.getByText(/Договор 24\/03\/15-01 · Период 2026-01-01 — 2026-05-30/)).toBeVisible();

    const payroll = indicators.getByRole('row').filter({
      has: page.getByRole('button', { name: 'Оплата труда', exact: true }),
    });
    if (missingPayroll) {
      await expect(payroll.getByRole('cell', { name: 'Не проверен', exact: true })).toBeVisible();
      await expect(payroll.getByText('Нет источника суммы', { exact: true })).toBeVisible();
      await expect(payroll.getByText('Частичная сумма:', { exact: false })).toHaveCount(0);
    }

    const partialRow = indicators.getByRole('row').filter({
      has: page.getByText(/Частичная сумма: \d/),
    }).first();
    await expect(partialRow.getByRole('cell', { name: 'Не проверен', exact: true })).toBeVisible();
    await expect(partialRow.getByRole('cell', { name: '—', exact: true }).last()).toBeVisible();
    await partialRow.getByRole('button').click();
    const detail = indicators.getByRole('region', { name: /^Подробности:/ });
    const amountSource = detail.getByRole('button', { name: /^Сумма · / }).first();
    await expect(amountSource).toBeVisible();
    const caption = await amountSource.innerText();
    const sourceName = primary.find((name) => caption.includes(` · ${name} · `));
    expect(sourceName, 'An amount component must link to an uploaded primary document.').toBeDefined();
    if (sourceName === undefined) throw new Error('Missing amount source filename.');
    const documentPath = `/api/v0/runs/${id}/documents/`;
    const [fragment, original] = await Promise.all([
      page.waitForResponse((response) => {
        const path = new URL(response.url()).pathname;
        return path.startsWith(documentPath) && path.endsWith('/fragments');
      }),
      page.waitForResponse((response) => {
        const path = new URL(response.url()).pathname;
        return path.startsWith(documentPath) && /^[^/]+$/.test(path.slice(documentPath.length));
      }),
      amountSource.click(),
    ]);
    expect(fragment.status()).toBe(200);
    expect(original.status()).toBe(200);
    expect(new URL(fragment.url()).pathname).toBe(`${new URL(original.url()).pathname}/fragments`);
    expect(await original.body()).toEqual(await readFile(join(examples, sourceName)));
    const viewer = page.getByRole('region', { name: 'Просмотр источника' });
    await expect(viewer.getByText('Выбранный фрагмент')).toBeVisible();
    await expect(viewer.getByRole('link', { name: 'Скачать оригинал' }))
      .toHaveAttribute('download', sourceName);
    await page.getByRole('button', { name: 'Закрыть просмотр источника' }).click();

    await page.getByRole('navigation', { name: 'Разделы проверки' })
      .getByRole('link', { name: 'Документы' }).click();
    const documents = page.getByRole('region', { name: 'Таблица документов' });
    await expect(documents.getByRole('row')).toHaveCount(primary.length + 2);
    for (const filename of [report, ...primary]) {
      await expect(documents.getByRole('button', { name: filename, exact: true })).toBeVisible();
    }

    await documents.getByRole('button', { name: report, exact: true }).click();
    const reportViewer = page.getByRole('region', { name: 'Просмотр источника' });
    await expect(reportViewer.getByRole('link', { name: 'Открыть страницу 1 PDF (в новой вкладке)' })).toBeVisible();
    await page.getByRole('button', { name: 'Закрыть просмотр источника' }).click();

    const exceptionDecisions = [
      [/^10_/, /повтор|дубликат|копи/i],
      [/^14_/, /период/i],
      [/^15_/, /договор/i],
    ] as const;
    for (const [filePattern, reasonPattern] of exceptionDecisions) {
      const name = primary.find((filename) => filePattern.test(filename));
      expect(name).toBeDefined();
      const row = documents.getByRole('row').filter({
        has: documents.getByRole('button', { name, exact: true }),
      });
      await expect(row.getByText(/^(Исключён|Требует проверки)$/)).toBeVisible();
      await expect(row.getByText(reasonPattern).first()).toBeVisible();
    }

    const [workbook, download] = await Promise.all([
      page.waitForResponse((response) =>
        new URL(response.url()).pathname === `/api/v0/runs/${id}/exports/xlsx`),
      page.waitForEvent('download'),
      page.getByRole('button', { name: 'Скачать XLSX' }).click(),
    ]);
    expect(workbook.status()).toBe(200);
    expect((await workbook.body()).subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 3, 4]));
    expect(basename(download.suggestedFilename())).toBe(`doccheck-${id}.xlsx`);
    expect(await download.failure()).toBeNull();
  });
}
