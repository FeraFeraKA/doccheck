import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DocumentSourcePreview } from '../../src/pages/checks';

const pdf = { id: 'report-1', name: 'Синтетический отчёт.pdf', format: 'pdf' };
const evidenceId = 'сумма/строка + %2F?#';
const createUrl = vi.fn<typeof URL.createObjectURL>();
const revokeUrl = vi.fn<typeof URL.revokeObjectURL>();

function original(): Response {
  return new Response(new Uint8Array([1, 2, 3]), {
    headers: { 'Content-Type': 'application/octet-stream' },
  });
}

function fragment(documentId: string, locator: object): Response {
  return Response.json({
    id: evidenceId,
    document_id: documentId,
    kind: 'amount',
    raw_value: '1,00',
    normalized_value: '1.00',
    unit: 'RUB',
    method: 'synthetic',
    locator,
  });
}

function mockSource(documentId: string, locator: object) {
  const fetchMock = vi.fn<typeof fetch>().mockImplementation(async (input) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname.endsWith('/fragments')) {
      expect(url.searchParams.get('evidence_id')).toBe(evidenceId);
      return fragment(documentId, locator);
    }
    return original();
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  createUrl.mockReset().mockReturnValue('blob:http://localhost/fixture');
  revokeUrl.mockReset();
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = createUrl;
    static revokeObjectURL = revokeUrl;
  });
});
afterEach(() => vi.unstubAllGlobals());

describe('document source preview', () => {
  it('opens the exact PDF page and releases the object URL on unmount', async () => {
    mockSource(pdf.id, { kind: 'page', page: 8, line: 3, fragment_id: 'first' });
    const view = render(<DocumentSourcePreview runId="run-1" document={pdf} evidenceId={evidenceId} />);
    expect(screen.getByText('Загрузка оригинала…')).toBeVisible();
    expect(await screen.findByText('Страница 8, строка 3, фрагмент first')).toBeVisible();
    const open = screen.getByRole('link', { name: 'Открыть страницу 8 PDF (в новой вкладке)' });
    expect(open).toHaveAttribute('href', 'blob:http://localhost/fixture#page=8');
    expect(open).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByRole('link', { name: 'Скачать оригинал' })).toHaveAttribute('download', pdf.name);
    expect(createUrl).toHaveBeenCalledWith(expect.objectContaining({ type: 'application/pdf' }));
    view.unmount();
    expect(revokeUrl).toHaveBeenCalledExactlyOnceWith('blob:http://localhost/fixture');
  });

  it('keeps the PNG address separate from the render and handles image decode failure', async () => {
    const png = { id: 'report-image', name: 'Синтетическая страница.png', format: 'png' };
    mockSource(png.id, { kind: 'page', page: 1, bbox: [0.25, 0.125, 0.75, 0.625] });
    const view = render(<DocumentSourcePreview runId="run-1" document={png} evidenceId={evidenceId} />);
    const image = await screen.findByRole('img', { name: png.name });
    expect(await screen.findByText('Страница 1')).toBeVisible();
    expect(createUrl).toHaveBeenCalledWith(expect.objectContaining({ type: 'image/png' }));
    expect(view.container.querySelector('[aria-hidden="true"]')).toBeNull();
    fireEvent.load(image);
    expect(view.container.querySelector('[aria-hidden="true"]')).toHaveStyle({
      left: '25%', top: '12.5%', width: '50%', height: '50%',
    });
    fireEvent.error(image);
    expect(screen.getByRole('alert')).toHaveTextContent('Предпросмотр изображения недоступен.');
    expect(screen.getByRole('link', { name: 'Скачать оригинал' })).toBeVisible();
  });

  it.each([
    ['xlsx', { kind: 'sheet', sheet: 'Синтетика', range: 'C6:D8' }, 'Лист «Синтетика», C6:D8'],
    ['docx', { kind: 'paragraph', paragraph: 3 }, 'Абзац 3'],
    ['docx', { kind: 'table_cell', table: 1, row: 2, cell: 3 }, 'Таблица 1, строка 2, ячейка 3'],
  ] as const)('shows the address for %s and downloads the office original', async (format, locator, label) => {
    const document = { id: 'office-1', name: `example.${format}`, format };
    mockSource(document.id, locator);
    render(<DocumentSourcePreview runId="run-1" document={document} evidenceId={evidenceId} />);

    expect(await screen.findByText(label)).toBeVisible();
    expect(screen.getByText('Для просмотра по адресу откройте скачанный файл в офисном приложении.'))
      .toBeVisible();
    expect(screen.getByRole('link', { name: 'Скачать оригинал' })).toHaveAttribute('download', document.name);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('keeps the original downloadable if the evidence is missing', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async (input) =>
      String(input).includes('/fragments?')
        ? Response.json({ code: 'fragment_not_found' }, { status: 404 })
        : original()));
    render(<DocumentSourcePreview runId="run-1" document={pdf} evidenceId={evidenceId} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Адрес фрагмента недоступен.');
    expect(screen.getByRole('link', { name: 'Скачать оригинал' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Открыть PDF (в новой вкладке)' })).toHaveAttribute(
      'href', 'blob:http://localhost/fixture',
    );
  });

  it('keeps the evidence address accessible when the original fails and allows retry', async () => {
    let downloads = 0;
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async (input) => {
      if (String(input).includes('/fragments?')) return fragment(pdf.id, { kind: 'page', page: 1, line: 1 });
      downloads += 1;
      if (downloads === 1) return Response.json({ code: 'document_not_found' }, { status: 404 });
      return original();
    }));
    render(<DocumentSourcePreview runId="run-1" document={pdf} evidenceId={evidenceId} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Оригинал документа недоступен.');
    expect(await screen.findByText('Страница 1, строка 1')).toBeVisible();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку источника' }));
    expect(await screen.findByRole('link', { name: 'Скачать оригинал' })).toBeVisible();
  });

  it('shows missing and unsupported source data without inventing an address', async () => {
    const fetchMock = mockSource('unknown-1', { kind: 'page', page: 2, line: 1 });
    const unknown = { id: 'unknown-1', name: 'example.txt', format: null };
    const view = render(<DocumentSourcePreview runId="run-1" document={null} evidenceId={evidenceId} />);
    expect(screen.getByText('Документ источника недоступен.')).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();

    view.rerender(<DocumentSourcePreview runId="run-1" document={unknown} evidenceId={null} />);
    expect(screen.getByText('Адрес фрагмента отсутствует.')).toBeVisible();
    expect(await screen.findByText('Предпросмотр этого формата недоступен.')).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    view.rerender(<DocumentSourcePreview runId="run-1" document={unknown} evidenceId={evidenceId} />);
    expect(await screen.findByText('Адрес фрагмента не поддерживается для этого формата.')).toBeVisible();
  });

  it('aborts stale requests and never allocates a URL for a retired selection', async () => {
    const retired: AbortSignal[] = [];
    const respond: ((response: Response) => void)[] = [];
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async (input, options) => {
      if (String(input).includes('/documents/report-1')) {
        if (options?.signal) retired.push(options.signal);
        return new Promise((resolve) => respond.push(resolve));
      }
      if (String(input).includes('/fragments?')) {
        return fragment('other-1', { kind: 'page', page: 5, line: 1 });
      }
      return original();
    }));
    const view = render(<DocumentSourcePreview runId="run-1" document={pdf} evidenceId={evidenceId} />);
    await waitFor(() => expect(retired).toHaveLength(2));
    view.rerender(<DocumentSourcePreview
      runId="run-1" document={{ ...pdf, id: 'other-1', name: 'Новый источник' }} evidenceId={evidenceId}
    />);
    expect(retired.every((signal) => signal.aborted)).toBe(true);
    await act(async () => {
      for (const complete of respond) complete(original());
    });
    const preview = screen.getByRole('region', { name: 'Просмотр источника' });
    expect(within(preview).getByText('Новый источник')).toBeVisible();
    expect(within(preview).queryByText(pdf.name)).not.toBeInTheDocument();
    expect(await within(preview).findByText('Страница 5, строка 1')).toBeVisible();
    expect(createUrl).toHaveBeenCalledTimes(1);
  });
});
