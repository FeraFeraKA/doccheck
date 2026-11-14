import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SourceWorkspace, useSourceWorkspace } from '../../src/pages/checks/SourceWorkspace';
import { loadDemoRun } from '../../src/pages/checks/checkData';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

const demo = await loadDemoRun(example.run_id);
if (!demo?.result) throw new Error('The synthetic fixture has no result');
const { result } = demo;

function Preview({ runId, findings = result }: { runId?: string; findings?: typeof result }) {
  const source = useSourceWorkspace({ result: findings, storedRunId: runId });
  const row = findings.rows[0];
  return <div className="accountant-workspace"><div className="app-content">
    <button type="button" onClick={(event) => {
      source.openDocument('report', event.currentTarget);
    }}>Открыть КФЗ</button>
    <button type="button" onClick={(event) => {
      source.openEvidence('amount-1', event.currentTarget, row, ['report-a', 'amount-1', 'amount-2']);
    }}>Просмотреть источник</button>
    <p>Активная строка: {source.rowId ?? '—'}</p>
    <SourceWorkspace workspace={source} />
  </div></div>;
}

const pdfViewing = vi.fn(() => true);

beforeEach(() => {
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false })));
  const navigatorPrototype = Object.getPrototypeOf(navigator);
  Object.defineProperty(navigatorPrototype, 'pdfViewerEnabled', { configurable: true, get: pdfViewing });
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    callback(performance.now());
    return 0;
  });
});

afterEach(() => {
  Reflect.deleteProperty(Object.getPrototypeOf(navigator), 'pdfViewerEnabled');
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('shared compact source workspace', () => {
  it('opens the whole КФЗ from the eye and preserves the document when clearing its address', () => {
    render(<Preview />);
    const eye = screen.getByRole('button', { name: 'Открыть просмотр документов' });
    expect(screen.queryByRole('region', { name: 'Источник документа' })).toBeNull();
    fireEvent.click(eye);

    const panel = screen.getByRole('region', { name: 'Источник документа' });
    expect(within(panel).getByRole('combobox', { name: 'Документы комплекта' })).toHaveValue('report');
    expect(within(panel).getByText('Оригинал документа недоступен.')).toBeVisible();
    const addresses = within(panel).getByRole('combobox', { name: 'Адрес доказательства' });
    expect(addresses).toHaveDisplayValue('Документ целиком');

    fireEvent.click(within(panel).getByRole('button', { name: 'Следующий документ' }));
    expect(within(panel).getByRole('combobox', { name: 'Документы комплекта' })).toHaveValue('ledger');
    expect(addresses).toHaveDisplayValue('Документ целиком');
    fireEvent.change(addresses, { target: { value: 'amount-2' } });
    expect(addresses).toHaveDisplayValue('Лист «Синтетика», C7');
    fireEvent.change(addresses, { target: { value: '' } });
    expect(addresses).toHaveDisplayValue('Документ целиком');
    fireEvent.click(within(panel).getByRole('button', { name: 'Закрыть просмотр источника' }));
    expect(eye).toHaveFocus();
  });

  it('links a selected address to its indicator and restores the opening control on Escape', () => {
    const row = result.rows[0];
    const repeatedReason = { code: 'copy', message: '  ' + row.completeness.reason, evidence_refs: [] };
    render(<Preview findings={{ ...result, rows: [
      { ...row, reasons: [...row.reasons, repeatedReason] }, ...result.rows.slice(1),
    ] }} />);
    const opener = screen.getByRole('button', { name: 'Просмотреть источник' });
    fireEvent.click(opener);
    const panel = screen.getByRole('region', { name: 'Источник документа' });
    expect(within(panel).getByRole('combobox', { name: 'Документы комплекта' })).toHaveValue('ledger');
    expect(within(panel).getByRole('combobox', { name: 'Доказательство' }))
      .toHaveDisplayValue('synthetic-ledger.xlsx · Лист «Синтетика», C6');
    expect(screen.getByText('Активная строка: row-a')).toBeVisible();
    fireEvent.click(within(panel).getByRole('tab', { name: 'Правило проверки' }));
    expect(within(panel).getByText(result.rows[0].calculation.policy_id)).toBeVisible();
    expect(within(panel).getAllByText(row.completeness.reason, { exact: true })).toHaveLength(1);
    fireEvent.keyDown(within(panel).getByRole('tab', { name: 'Правило проверки' }), { key: 'Escape' });
    expect(screen.queryByRole('region', { name: 'Источник документа' })).toBeNull();
    expect(opener).toHaveFocus();
  });

  it('uses the browser PDF viewer on the addressed page and retains both original-file actions', async () => {
    const file = new Uint8Array([37, 80, 68, 70, 45]);
    const fragment = example.result.evidence.find(({ id }) => id === 'report-a');
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async (url) =>
      String(url).includes('?evidence_id=')
        ? Response.json(fragment)
        : new Response(file, { headers: { 'Content-Type': 'application/octet-stream' } })));
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = () => 'blob:http://localhost/fixture';
      static revokeObjectURL = () => {};
    });
    render(<Preview runId="run-1" />);
    fireEvent.click(screen.getByRole('button', { name: 'Открыть КФЗ' }));
    const panel = screen.getByRole('region', { name: 'Источник документа' });
    fireEvent.change(within(panel).getByRole('combobox', { name: 'Адрес доказательства' }), {
      target: { value: 'report-a' },
    });
    const openPage = await within(panel).findByRole('link', { name: 'Открыть страницу 1 PDF (в новой вкладке)' });
    expect(await within(panel).findByTitle('Просмотр документа: synthetic-report.pdf')).toHaveAttribute(
      'src', 'blob:http://localhost/fixture#page=1&view=FitH&toolbar=0',
    );
    expect(openPage).toHaveAttribute('href', 'blob:http://localhost/fixture#page=1');
    expect(within(panel).getByRole('link', { name: 'Скачать оригинал' }))
      .toHaveAttribute('download', 'synthetic-report.pdf');
  });

  it('starts a workbook at row 1 and highlights addresses from all linked indicators', async () => {
    const [first, second] = result.rows;
    const findings = { ...result, rows: [first, { ...second, status: 'verified', reported_evidence_refs: ['third'] }],
      evidence: [...result.evidence, { ...result.evidence[2], id: 'third', locator: {
        kind: 'sheet', sheet: 'Синтетика', range: 'C8',
      } }] };
    const amounts = ['1', '2', '=SUM(C6:C7)'];
    const requests: URL[] = [];
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async (input) => {
      const url = new URL(String(input), 'http://localhost');
      requests.push(url);
      if (url.pathname.endsWith('/preview')) {
        const row = Number(url.searchParams.get('row') ?? 1);
        const rows = Array.from({ length: 8 }, (_, i) => [i === 0 ? 'Ведомость' : '', '', amounts[i - 5] ?? '']);
        return Response.json({ sheets: ['Синтетика'], sheet: 'Синтетика', row, column: 1,
          last_row: 8, last_column: 3, rows: rows.slice(row - 1) });
      }
      if (url.pathname.endsWith('/fragments')) {
        return Response.json(example.result.evidence.find(({ id }) => id === url.searchParams.get('evidence_id')));
      }
      if (url.pathname.endsWith('/fragment-preview')) return Response.json({ text: '2', highlight: { start_byte: 0, end_byte: 1 } });
      return new Response('original', { headers: { 'Content-Type': 'application/octet-stream' } });
    }));
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = () => 'blob:http://localhost/workbook';
      static revokeObjectURL = () => {};
    });
    render(<Preview runId="run-1" findings={findings} />);
    fireEvent.click(screen.getByRole('button', { name: 'Открыть просмотр документов' }));
    const panel = screen.getByRole('region', { name: 'Источник документа' });
    fireEvent.click(within(panel).getByRole('button', { name: 'Следующий документ' }));
    const addressPicker = within(panel).getByRole('combobox', { name: 'Адрес доказательства' });
    expect(addressPicker).toHaveDisplayValue('Документ целиком');
    expect(await within(panel).findByRole('cell', { name: 'Ведомость' })).toBeVisible();
    expect(within(panel).getByRole('cell', { name: '1' })).toHaveAttribute('data-source-tone', 'discrepancy');
    expect(within(panel).getByRole('cell', { name: '2' })).toHaveAttribute('data-source-tone', 'discrepancy');
    expect(within(panel).getByRole('cell', { name: '=SUM(C6:C7)' })).toHaveAttribute('data-source-tone', 'verified');
    expect(within(panel).getByRole('cell', { name: '2' })).not.toHaveAttribute('data-source-active');
    expect(requests.every(({ pathname }) => !pathname.endsWith('/fragments'))).toBe(true);

    fireEvent.change(addressPicker, { target: { value: 'amount-2' } });
    await waitFor(() => expect(within(panel).getByRole('cell', { name: '2' })).toHaveAttribute('data-source-active', 'true'));
    expect(within(panel).getByRole('cell', { name: '2' }).querySelector('mark')).toHaveTextContent('2');
    expect(within(panel).getByRole('cell', { name: '=SUM(C6:C7)' })).toHaveAttribute('data-source-tone', 'verified');
    fireEvent.change(addressPicker, { target: { value: '' } });
    expect(await within(panel).findByRole('cell', { name: 'Ведомость' })).toBeVisible();
    expect(within(panel).getByRole('cell', { name: '2' })).not.toHaveAttribute('data-source-active');
  });
});
