import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router';
import { expect, it, vi } from 'vitest';
import { CheckDetail, ChecksOverview } from '../../src/pages/checks';
import { loadDemoRun } from '../../src/pages/checks/checkData';
import type { RunDetails } from '../../src/pages/checks/checkData';

it('различает загрузку истории, ошибку и пустой список после повтора', async () => {
  const loadHistory = vi.fn()
    .mockRejectedValueOnce(new Error('Скрытая техническая причина'))
    .mockResolvedValueOnce({ entries: [] });

  render(<MemoryRouter><ChecksOverview loadHistory={loadHistory} /></MemoryRouter>);

  expect(screen.getByRole('status')).toHaveTextContent('Загрузка проверок');
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить проверки.');
  expect(screen.queryByText('Скрытая техническая причина')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
  expect(await screen.findByText('Проверок пока нет.')).toBeVisible();
});

it('показывает прогресс задания без готового результата и игнорирует ответ для старого ID', async () => {
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
    <Routes><Route path="/checks/:id" element={<CheckDetail view="table" loadRun={loadRun} />} /></Routes>
  </MemoryRouter>);

  expect(screen.getByRole('status')).toHaveTextContent('Загрузка проверки');
  await act(async () => {});
  fireEvent.click(screen.getByRole('link', { name: 'Следующая проверка' }));
  expect(await screen.findByRole('heading', { name: 'Вторая проверка' })).toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent('Обрабатывается');
  expect(screen.getByText('Обработано документов: 0 из 2')).toBeVisible();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(firstSignal?.aborted).toBe(true);

  await act(async () => {
    finishFirst?.({ title: 'Первая проверка', status: 'completed', result: null });
  });
  expect(screen.getByRole('heading', { name: 'Вторая проверка' })).toBeVisible();
  expect(screen.queryByText('Первая проверка')).not.toBeInTheDocument();
});

it.each([
  ['failed', 'Не удалось выполнить проверку.'],
  ['completed', 'Результат проверки недоступен.'],
] as const)('показывает отсутствие результата для состояния %s', async (status, message) => {
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

  const select = await screen.findByRole('combobox', { name: 'Доказательство' });
  for (const [id, location] of [
    ['docx-paragraph', 'Абзац 3'],
    ['docx-cell', 'Таблица 1, строка 2, ячейка 4'],
  ]) {
    expect(within(select).getByRole('option', { name: 'synthetic.docx · ' + location })).toBeVisible();
    fireEvent.change(select, { target: { value: id } });
    expect(screen.getByText(location, { selector: 'dd' })).toBeVisible();
  }
});
