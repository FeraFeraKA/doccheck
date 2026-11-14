import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CheckDetail, ChecksOverview } from '../../src/pages/checks';
import { loadDemoRun } from '../../src/pages/checks/checkData';
import type { RunDetails } from '../../src/pages/checks/checkData';

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: false }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it('открывает публичный обзор без запроса закрытой истории', () => {
  vi.stubEnv('VITE_DOCCHECK_PUBLIC_DEMO', '1');
  const loadHistory = vi.fn();
  render(<MemoryRouter initialEntries={['/checks']}>
    <ChecksOverview loadHistory={loadHistory} />
  </MemoryRouter>);

  expect(screen.getByText('История рабочих проверок доступна в локальной установке.')).toBeVisible();
  expect(screen.queryByRole('link', { name: 'Синтетическая сверка' })).not.toBeInTheDocument();
  expect(loadHistory).not.toHaveBeenCalled();
});

it('различает загрузку истории, ошибку и пустой список после повтора', async () => {
  const loadHistory = vi.fn()
    .mockRejectedValueOnce(new Error('Скрытая техническая причина'))
    .mockResolvedValueOnce({ entries: [], nextCursor: null });

  render(<MemoryRouter><ChecksOverview loadHistory={loadHistory} /></MemoryRouter>);

  expect(screen.getByRole('status')).toHaveTextContent('Загрузка проверок');
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить проверки.');
  expect(screen.queryByText('Скрытая техническая причина')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
  expect(await screen.findByText('Проверок пока нет.')).toBeVisible();
});

it('открывает сохранённый запуск из истории и показывает терминальное состояние', async () => {
  const summary = {
    run_id: 'saved-run', status: 'failed', created_at: '2026-11-13T12:00:00Z',
    error: { code: 'test_failure', message: 'Безопасная причина остановки' },
  };
  const fetchMock = vi.fn<typeof fetch>()
    .mockResolvedValueOnce(Response.json({ items: [summary], next_cursor: null }))
    .mockResolvedValueOnce(Response.json({ ...summary, progress: null }));
  vi.stubGlobal('fetch', fetchMock);

  render(<MemoryRouter initialEntries={['/checks']}>
    <Routes>
      <Route path="/checks" element={<ChecksOverview />} />
      <Route path="/checks/:id" element={<CheckDetail view="table" />} />
    </Routes>
  </MemoryRouter>);

  fireEvent.click(await screen.findByRole('link', { name: 'Проверка КФЗ №saved-run' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Безопасная причина остановки');
  expect(screen.getByRole('status')).toHaveTextContent('Ошибка обработки');
  expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
    '/api/v0/runs', '/api/v0/runs/saved-run',
  ]);
  expect(screen.queryByText('Синтетическая сверка · готовый пример')).not.toBeInTheDocument();
});

it('после ошибки получения состояния повторяет запрос для текущей ссылки', async () => {
  const fetchMock = vi.fn<typeof fetch>()
    .mockRejectedValueOnce(new TypeError('network unavailable'))
    .mockResolvedValueOnce(Response.json({
      run_id: 'saved-run', status: 'completed_with_issues', created_at: '2026-11-13T12:00:00Z',
      error: { code: 'test_issue', message: 'Проверка завершилась с замечаниями' },
      progress: { processed_documents: 2, total_documents: 2 },
    }))
    .mockResolvedValueOnce(Response.json({ code: 'result_pending', message: 'Нет результата' }, { status: 409 }));
  vi.stubGlobal('fetch', fetchMock);

  render(<MemoryRouter initialEntries={['/checks/saved-run']}>
    <Routes><Route path="/checks/:id" element={<CheckDetail view="table" />} /></Routes>
  </MemoryRouter>);

  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось получить состояние проверки.');
  fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
  expect(await screen.findByText('Результат проверки недоступен.')).toBeVisible();
  expect(screen.getByText('Состояние проверки · Готово с замечаниями')).toBeVisible();
  expect(screen.getByRole('alert')).toHaveTextContent('Проверка завершилась с замечаниями');
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

it('перенаправляет активную проверку в очередь и игнорирует ответ для старого ID', async () => {
  let finishFirst: ((value: RunDetails) => void) | undefined;
  let firstSignal: AbortSignal | undefined;
  const loadRun = (id: string, signal: AbortSignal): Promise<RunDetails> => {
    if (id === 'first') {
      firstSignal = signal;
      return new Promise((resolve) => { finishFirst = resolve; });
    }
    return Promise.resolve({
      title: 'Вторая проверка',
      status: 'processing',
      progress: { processed: 0, total: 2 },
      result: null,
    });
  };

  render(<MemoryRouter initialEntries={['/checks/first']}>
    <Link to="/checks/second">Следующая проверка</Link>
    <Routes>
      <Route path="/checks/new" element={<h1>Очередь проверок</h1>} />
      <Route path="/checks/:id" element={<CheckDetail view="table" loadRun={loadRun} />} />
    </Routes>
  </MemoryRouter>);

  expect(screen.getByRole('status')).toHaveTextContent('Загрузка проверки');
  await act(async () => {});
  fireEvent.click(screen.getByRole('link', { name: 'Следующая проверка' }));
  expect(await screen.findByRole('heading', { name: 'Очередь проверок' })).toBeVisible();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(firstSignal?.aborted).toBe(true);

  await act(async () => {
    finishFirst?.({ title: 'Первая проверка', status: 'completed', result: null });
  });
  expect(screen.getByRole('heading', { name: 'Очередь проверок' })).toBeVisible();
  expect(screen.queryByText('Первая проверка')).not.toBeInTheDocument();
});

it.each([
  ['failed', 'Не удалось выполнить проверку.'],
  ['completed', 'Результат проверки недоступен.'],
] as const)('показывает отсутствие результата для состояния %s', async (status, message) => {
  const fetchMock = vi.fn<typeof fetch>()
    .mockResolvedValueOnce(Response.json({ code: 'result_pending', message: 'Результат пока недоступен' }, { status: 409 }));
  vi.stubGlobal('fetch', fetchMock);
  const loadRun = async (): Promise<RunDetails> => ({
    title: 'Проверка',
    status,
    result: null,
  });

  render(<MemoryRouter initialEntries={['/checks/known']}>
    <Routes><Route path="/checks/:id" element={<CheckDetail view="table" loadRun={loadRun} />} /></Routes>
  </MemoryRouter>);

  expect(await screen.findByText(message)).toBeVisible();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(status === 'completed' ? 1 : 0);
});

it('показывает абзац и ячейку таблицы DOCX в списке доказательств и панели источника', async () => {
  const loadRun = async (): Promise<RunDetails | null> => {
    const demo = await loadDemoRun('synthetic-example');
    if (!demo?.result) throw new Error('Не найден синтетический результат');
    const document = {
      id: 'synthetic-docx',
      name: 'synthetic.docx',
      role: 'supporting',
      decision: {
        state: 'include',
        reason_code: 'synthetic_source',
        message: 'Синтетический документ',
        evidence_refs: [],
      },
      errors: [],
    };
    const [first, ...otherRows] = demo.result.rows;

    return {
      ...demo,
      result: {
        ...demo.result,
        documents: [...demo.result.documents, document],
        rows: [{
          ...first,
          reasons: [...first.reasons, {
            code: 'synthetic_docx',
            message: 'Адреса в синтетическом DOCX',
            evidence_refs: ['docx-paragraph', 'docx-cell'],
          }],
        }, ...otherRows],
        evidence: [...demo.result.evidence, {
          id: 'docx-paragraph',
          document_id: document.id,
          raw_value: 'Синтетический абзац',
          locator: { kind: 'paragraph', paragraph: 3 },
        }, {
          id: 'docx-cell',
          document_id: document.id,
          raw_value: 'Синтетическая ячейка',
          locator: { kind: 'table_cell', table: 1, row: 2, cell: 4 },
        }],
      },
    };
  };

  render(<MemoryRouter initialEntries={['/checks/docx-test']}>
    <Routes><Route path="/checks/:id" element={<CheckDetail view="table" loadRun={loadRun} />} /></Routes>
  </MemoryRouter>);

  fireEvent.click(await screen.findByRole('button', { name: /^150,50\s*₽$/ }));
  const select = await screen.findByRole('combobox', { name: 'Доказательство' });
  for (const [id, location] of [
    ['docx-paragraph', 'Абзац 3'],
    ['docx-cell', 'Таблица 1, строка 2, ячейка 4'],
  ]) {
    expect(within(select).getByRole('option', { name: 'synthetic.docx · ' + location })).toBeVisible();
    fireEvent.change(select, { target: { value: id } });
    expect(select).toHaveValue(id);
  }
});

it('показывает доказательства слагаемых при заявлении пользователя о полноте', async () => {
  const loadRun = async (): Promise<RunDetails> => {
    const demo = await loadDemoRun('synthetic-example');
    if (!demo?.result) throw new Error('Не найден синтетический результат');
    const result = demo.result;
    const [first, ...otherRows] = result.rows;
    const verifiedRow = {
      ...first,
      reported_value: first.expected_value,
      delta: '0.00',
      status: 'verified',
      root_issue_id: null,
      completeness: {
        state: 'complete',
        basis: 'user_declaration',
        reason: 'Пользователь подтвердил полноту пакета',
        evidence_refs: [],
      },
      reasons: [],
    };

    return {
      ...demo,
      result: {
        ...result,
        rows: [verifiedRow, ...otherRows],
        evidence: result.evidence.map((item) => item.id === 'report-a'
          ? { ...item, raw_value: '120,50', normalized_value: first.expected_value }
          : item),
        summary: {
          ...result.summary,
          counts: { verified: 1, discrepancy: 0, unverified: 1 },
          primary_issues: result.summary.primary_issues.filter(({ id }) => id !== 'issue-a'),
        },
      },
    };
  };

  render(<MemoryRouter initialEntries={['/checks/declared']}>
    <Routes><Route path="/checks/:id" element={<CheckDetail view="table" loadRun={loadRun} />} /></Routes>
  </MemoryRouter>);

  fireEvent.click(await screen.findByRole('button', { name: /^Синтетическая статья A$/ }));
  const breakdown = screen.getByRole('list', { name: 'Слагаемые показателя: Синтетическая статья A' });
  const [first, second] = breakdown.querySelectorAll<HTMLElement>(':scope > li');
  for (const item of [first, second]) item.querySelector('details')?.setAttribute('open', '');
  const firstAmount = within(first).getByRole('button', { name: /^Сумма · .*C6$/ });
  const secondAmount = within(second).getByRole('button', { name: /^Сумма · .*C7$/ });
  expect(within(first).queryByRole('button', { name: /^Сумма · .*C7$/ })).not.toBeInTheDocument();
  expect(within(second).getByRole('button', { name: /^Договор · .*A2$/ })).toBeVisible();
  fireEvent.click(secondAmount);
  const select = await screen.findByRole('combobox', { name: 'Доказательство' });
  expect(within(select).getByRole('option', { name: /Лист «Синтетика», C6/ })).toBeVisible();
  expect(within(select).getByRole('option', { name: /Лист «Синтетика», C7/ })).toBeVisible();
  expect(select).toHaveValue('amount-2');
  expect(firstAmount).toHaveAttribute('aria-pressed', 'false');
  expect(secondAmount).toHaveAttribute('aria-pressed', 'true');
});
