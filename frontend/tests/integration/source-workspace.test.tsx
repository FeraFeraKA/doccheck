import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SourceWorkspace, useSourceWorkspace } from '../../src/pages/checks/SourceWorkspace';
import { loadDemoRun } from '../../src/pages/checks/checkData';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

const demo = await loadDemoRun(example.run_id);
if (!demo?.result) throw new Error('The synthetic fixture has no result');
const { result } = demo;

function Preview({ runId }: { runId?: string }) {
  const source = useSourceWorkspace({ result, storedRunId: runId });
  const row = result.rows[0];
  return <div className="accountant-workspace"><div className="app-content">
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
  it('opens the КФЗ by default and switches documents independently of the indicator', async () => {
    render(<Preview />);
    const eye = screen.getByRole('button', { name: 'Показать источник документа' });
    expect(screen.queryByRole('region', { name: 'Источник документа' })).toBeNull();
    fireEvent.click(eye);

    const panel = screen.getByRole('region', { name: 'Источник документа' });
    expect(within(panel).getByRole('combobox', { name: 'Документы комплекта' })).toHaveValue('report');
    expect(within(panel).getByText('Оригинал в готовом примере недоступен.')).toBeVisible();
    expect(within(panel).getByText('Страница 1', { selector: 'p', exact: true })).toBeVisible();

    fireEvent.click(within(panel).getByRole('button', { name: 'Следующий документ' }));
    expect(within(panel).getByRole('combobox', { name: 'Документы комплекта' })).toHaveValue('ledger');
    fireEvent.change(within(panel).getByRole('combobox', { name: 'Адрес доказательства' }), { target: { value: 'amount-2' } });
    expect(within(panel).getByText('Лист «Синтетика», C7', { selector: 'p', exact: true })).toBeVisible();
  });

  it('links a selected address to its indicator and restores the opening control on Escape', () => {
    render(<Preview />);
    const opener = screen.getByRole('button', { name: 'Просмотреть источник' });
    fireEvent.click(opener);
    const panel = screen.getByRole('region', { name: 'Источник документа' });
    expect(within(panel).getByRole('combobox', { name: 'Документы комплекта' })).toHaveValue('ledger');
    expect(within(panel).getByText('Лист «Синтетика», C6', { exact: true })).toBeVisible();
    expect(screen.getByText('Активная строка: row-a')).toBeVisible();
    fireEvent.click(within(panel).getByRole('tab', { name: 'Правило проверки' }));
    expect(within(panel).getByText(result.rows[0].calculation.policy_id)).toBeVisible();
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
    fireEvent.click(screen.getByRole('button', { name: 'Показать источник документа' }));
    const panel = screen.getByRole('region', { name: 'Источник документа' });
    expect(await within(panel).findByTitle('Просмотр документа: synthetic-report.pdf')).toHaveAttribute(
      'src', 'blob:http://localhost/fixture#page=1&view=FitH&toolbar=0',
    );
    expect(within(panel).getByRole('link', { name: 'Открыть страницу 1 PDF (в новой вкладке)' }))
      .toHaveAttribute('href', 'blob:http://localhost/fixture#page=1');
    expect(within(panel).getByRole('link', { name: 'Скачать оригинал' }))
      .toHaveAttribute('download', 'synthetic-report.pdf');
  });
});
