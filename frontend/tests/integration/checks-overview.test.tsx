import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { ChecksOverview } from '../../src/pages/checks/ChecksOverview';
import type { HistoryEntry } from '../../src/pages/checks/checkData';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it('applies server filters before pagination while sorting the current page locally', async () => {
  vi.stubEnv('VITE_DOCCHECK_PUBLIC_DEMO', '0');
  const entries: HistoryEntry[] = [
    { id: 'b', title: 'Бета', status: 'completed', counts: { verified: 1, discrepancy: 2, unverified: 3 }, createdAt: '2026-11-14T10:00:00Z' },
    { id: 'a', title: 'Альфа', status: 'failed', createdAt: '2026-11-14T09:00:00Z' },
    { id: 'q', title: 'Очередь', status: 'queued', createdAt: '2026-11-14T08:00:00Z' },
  ];
  const loadHistory = vi.fn<typeof import('../../src/pages/checks/checkData').loadRunHistory>()
    .mockImplementation(async (_signal, _cursor, finding) => ({
      entries: finding ? entries.filter((entry) => (entry.counts?.[finding] ?? 0) > 0) : entries,
      nextCursor: 'older + opaque',
    }));
  render(<MemoryRouter><ChecksOverview loadHistory={loadHistory} /></MemoryRouter>);
  const history = screen.getByRole('region', { name: 'История запусков' });
  const table = await within(history).findByRole('table');
  expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Бета');
  expect(within(table).getAllByRole('columnheader').map((column) => column.textContent))
    .toEqual(['Проверка', 'Результат', 'Покрытие по сумме', 'Документы', 'Дата']);
  const firstResult = within(table).getAllByRole('row')[1];
  expect(within(firstResult).getByText('Есть расхождения')).toBeVisible();
  expect(within(firstResult).getByText('Неполные данные')).toBeVisible();
  expect(within(firstResult).getByText('Готово')).toBeVisible();
  expect(within(firstResult).getByText('1 из 6 показателей')).toBeVisible();
  expect(within(firstResult).getByLabelText('Покрытие по сумме недоступно')).toHaveTextContent('—');
  expect(within(firstResult).getByLabelText('Количество документов недоступно')).toHaveTextContent('—');
  expect(within(history).getByRole('link', { name: 'Очередь' })).toHaveAttribute('href', '/checks/new?run=q#queue');
  expect(within(history).getByRole('link', { name: 'Альфа' })).toHaveAttribute('href', '/checks/a');
  expect(within(history).getByRole('link', { name: 'Более ранние проверки' }))
    .toHaveAttribute('href', '/checks?cursor=older+%2B+opaque');

  fireEvent.change(within(history).getByRole('combobox', { name: 'Сортировка' }), { target: { value: 'name' } });
  expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Альфа');
  for (const [label, filter] of [['Есть расхождения', 'discrepancy'], ['Неполные данные', 'unverified']]) {
    fireEvent.click(within(history).getByRole('button', { name: label }));
    expect(await within(history).findByRole('link', { name: 'Бета' })).toHaveAttribute('href', '/checks/b');
    expect(within(history).queryByText('Альфа')).not.toBeInTheDocument();
    expect(loadHistory).toHaveBeenLastCalledWith(expect.any(AbortSignal), undefined, filter);
    expect(within(history).getByRole('link', { name: 'Более ранние проверки' }))
      .toHaveAttribute('href', `/checks?finding=${filter}&cursor=older+%2B+opaque`);
  }

  fireEvent.change(within(history).getByRole('searchbox', { name: 'Поиск на странице' }),
    { target: { value: 'несуществующая' } });
  expect(within(history).getByText('Проверки не найдены.')).toBeVisible();
  fireEvent.click(within(history).getByRole('button', { name: 'Сбросить фильтры' }));
  expect(await within(history).findByText('Бета')).toBeVisible();
  expect(within(history).queryByText('Синтетическая сверка')).not.toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Готовый пример' })).not.toBeInTheDocument();
});

it('shows the archive in server order with search and without a sort control', async () => {
  vi.stubEnv('VITE_DOCCHECK_PUBLIC_DEMO', '0');
  const fetchHistory = vi.fn().mockResolvedValueOnce(Response.json({
    items: [
      {
        run_id: 'recent', report_number: '2', status: 'completed', error: null,
        created_at: '2026-11-12T12:00:00Z', archived_at: '2026-11-14T14:00:00Z',
      },
      {
        run_id: 'older', report_number: '1', status: 'completed', error: null,
        created_at: '2026-11-13T12:00:00Z', archived_at: '2026-11-14T13:00:00Z',
      },
    ],
    next_cursor: 'old-archive',
  }));
  vi.stubGlobal('fetch', fetchHistory);
  render(<MemoryRouter initialEntries={['/archive']}><ChecksOverview archive /></MemoryRouter>);

  const archive = screen.getByRole('region', { name: 'Архив запусков' });
  expect(await within(archive).findAllByRole('link', { name: /КФЗ №/ })).toEqual([
    within(archive).getByRole('link', { name: 'КФЗ №2' }),
    within(archive).getByRole('link', { name: 'КФЗ №1' }),
  ]);
  expect(fetchHistory).toHaveBeenCalledWith('/api/v0/runs?view=archive', expect.any(Object));
  expect(within(archive).queryByRole('combobox', { name: 'Сортировка' })).not.toBeInTheDocument();
  expect(within(archive).getByRole('columnheader', { name: 'Дата архивации' })).toHaveAttribute('aria-sort', 'descending');
  expect(within(archive).getByRole('link', { name: 'Более ранние проверки' })).toHaveAttribute('href', '/archive?cursor=old-archive');
  fireEvent.change(within(archive).getByRole('searchbox'), { target: { value: '№1' } });
  expect(within(archive).getByRole('link', { name: 'КФЗ №1' })).toHaveAttribute('href', '/checks/older');
  expect(within(archive).queryByRole('link', { name: 'КФЗ №2' })).not.toBeInTheDocument();
});

it('shows the local history notice in the public overview without links to an example', () => {
  vi.stubEnv('VITE_DOCCHECK_PUBLIC_DEMO', '1');
  const loadHistory = vi.fn();
  render(<MemoryRouter><ChecksOverview loadHistory={loadHistory} /></MemoryRouter>);
  const history = screen.getByRole('region', { name: 'История запусков' });
  expect(within(history).queryByRole('table')).not.toBeInTheDocument();
  expect(within(history).queryByRole('searchbox')).not.toBeInTheDocument();
  expect(within(history).getByText('История рабочих проверок доступна в локальной установке.')).toBeVisible();
  expect(screen.queryByRole('link', { name: 'Синтетическая сверка' })).not.toBeInTheDocument();
  expect(loadHistory).not.toHaveBeenCalled();
});
