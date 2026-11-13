import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { ChecksOverview } from '../../src/pages/checks/ChecksOverview';
import type { HistoryEntry } from '../../src/pages/checks/checkData';

afterEach(() => vi.unstubAllEnvs());

it('filters and sorts only the returned cursor page, keeping unknown measures unknown', async () => {
  vi.stubEnv('VITE_DOCCHECK_PUBLIC_DEMO', '0');
  const entries: HistoryEntry[] = [
    { id: 'b', title: 'Бета', status: 'completed', createdAt: '2026-11-14T10:00:00Z' },
    { id: 'a', title: 'Альфа', status: 'failed', createdAt: '2026-11-14T09:00:00Z' },
    { id: 'q', title: 'Очередь', status: 'queued', createdAt: '2026-11-14T08:00:00Z' },
  ];
  const loadHistory = vi.fn().mockResolvedValue({ entries, nextCursor: 'older + opaque' });
  render(<MemoryRouter><ChecksOverview loadHistory={loadHistory} /></MemoryRouter>);
  const history = screen.getByRole('region', { name: 'История запусков' });
  const table = await within(history).findByRole('table');
  expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Бета');
  expect(within(table).getAllByLabelText('Покрытие: нет данных')).toHaveLength(3);
  expect(within(table).getAllByLabelText('Документы: нет данных')).toHaveLength(3);
  expect(within(history).getByRole('link', { name: 'Более ранние проверки' }))
    .toHaveAttribute('href', '/checks?cursor=older+%2B+opaque');

  fireEvent.click(within(history).getByRole('button', { name: 'Сортировать по названию' }));
  expect(within(table).getAllByRole('row')[1]).toHaveTextContent('Альфа');
  fireEvent.click(within(history).getByRole('button', { name: 'Требуют внимания' }));
  expect(within(table).queryByText('Бета')).not.toBeInTheDocument();
  expect(within(table).getByRole('link', { name: 'Альфа' })).toHaveAttribute('href', '/checks/a');

  fireEvent.change(within(history).getByRole('searchbox', { name: 'Поиск на странице' }),
    { target: { value: 'несуществующая' } });
  expect(within(history).getByText('Проверки не найдены.')).toBeVisible();
  fireEvent.click(within(history).getByRole('button', { name: 'Сбросить фильтры' }));
  expect(within(table).getByText('Бета')).toBeVisible();
  expect(loadHistory).toHaveBeenCalledTimes(1);
  expect(within(history).queryByText('Синтетическая сверка')).not.toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Готовый пример' })).toHaveTextContent('Синтетический пример');
});

it('keeps the synthetic example separate in the public overview and never loads history', () => {
  vi.stubEnv('VITE_DOCCHECK_PUBLIC_DEMO', '1');
  const loadHistory = vi.fn();
  render(<MemoryRouter><ChecksOverview loadHistory={loadHistory} /></MemoryRouter>);
  const history = screen.getByRole('region', { name: 'История запусков' });
  expect(within(history).queryByRole('table')).not.toBeInTheDocument();
  expect(within(history).queryByRole('searchbox')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Синтетическая сверка' })).toBeVisible();
  expect(loadHistory).not.toHaveBeenCalled();
});
