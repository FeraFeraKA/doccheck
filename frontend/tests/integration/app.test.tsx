import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { App } from '../../src/app/App';
import { jobId, syntheticJob } from '../fixtures/syntheticJob';

afterEach(() => vi.unstubAllGlobals());

function renderApp() {
  return render(<MemoryRouter initialEntries={['/system-status']}><App /></MemoryRouter>);
}

const health = () => Response.json({ status: 'ok', database: 'ok' });

it('показывает явно синтетический lifecycle с подменённым API', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(health())
    .mockResolvedValueOnce(Response.json(syntheticJob('queued'), { status: 201 }))
    .mockResolvedValueOnce(Response.json(syntheticJob('processing')))
    .mockResolvedValueOnce(Response.json(syntheticJob('completed')));
  vi.stubGlobal('fetch', fetchMock);
  renderApp();
  expect(screen.getByRole('heading', { name: 'DocCheck' })).toBeVisible();
  expect(screen.getByText('OCR и настоящая финансовая сверка здесь не выполняются.')).toBeVisible();
  await screen.findByText('API и PostgreSQL доступны.');
  fireEvent.click(screen.getByRole('button', { name: 'Создать синтетическое задание' }));
  await screen.findByText('Статус: В очереди');
  expect(screen.getByRole('button', { name: 'Создать синтетическое задание' })).toBeDisabled();
  await screen.findByText('Статус: Обрабатывается');
  await screen.findByText('Статус: Завершено');
  expect(screen.getByText('Тестовый результат: Синтетическая проверка завершена.')).toBeVisible();
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/synthetic-jobs', expect.objectContaining({ method: 'POST' }));
  expect(fetchMock).toHaveBeenNthCalledWith(3, `/api/synthetic-jobs/${jobId}`, expect.any(Object));
});

it.each([
  ['ошибка сети', () => Promise.reject(new TypeError('network')), 'Нет связи с API.'],
  ['БД недоступна', () => Promise.resolve(Response.json({ detail: 'Database unavailable' }, { status: 503 })), 'API пока не готов:'],
  ['неверный JSON', () => Promise.resolve(Response.json({ status: 'ok' })), 'API вернул некорректный ответ.'],
] as const)('показывает ошибку связи и допускает повторную проверку: %s', async (_label, failure, message) => {
  vi.stubGlobal('fetch', vi.fn().mockImplementationOnce(failure).mockResolvedValue(health()));
  renderApp();
  expect(await screen.findByRole('alert')).toHaveTextContent(message);
  expect(screen.getByRole('button', { name: 'Создать синтетическое задание' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить связь' }));
  await screen.findByText('API и PostgreSQL доступны.');
  expect(screen.getByRole('button', { name: 'Создать синтетическое задание' })).toBeEnabled();
});

it('сбрасывает статус API при потере связи во время создания и восстанавливает его после проверки', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(health())
    .mockRejectedValueOnce(new TypeError('network'))
    .mockResolvedValueOnce(health());
  vi.stubGlobal('fetch', fetchMock);
  renderApp();
  await screen.findByText('API и PostgreSQL доступны.');
  const create = screen.getByRole('button', { name: 'Создать синтетическое задание' });
  fireEvent.click(create);
  await screen.findByText(/Не удалось подтвердить создание задания/);
  expect(screen.getByText('API недоступен.')).toBeVisible();
  expect(screen.queryByText('API и PostgreSQL доступны.')).not.toBeInTheDocument();
  expect(create).toBeDisabled();

  fireEvent.click(screen.getByRole('button', { name: 'Проверить связь' }));
  await screen.findByText('API и PostgreSQL доступны.');
  expect(create).toBeEnabled();
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
});

it('сохраняет последнее известное задание при недоступном API и продолжает опрос после проверки связи', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(health())
    .mockResolvedValueOnce(Response.json(syntheticJob('queued'), { status: 201 }))
    .mockResolvedValueOnce(Response.json({ detail: 'Database unavailable' }, { status: 503 }))
    .mockResolvedValueOnce(health())
    .mockResolvedValueOnce(Response.json(syntheticJob('completed')));
  vi.stubGlobal('fetch', fetchMock);
  renderApp();
  await screen.findByText('API и PostgreSQL доступны.');
  fireEvent.click(screen.getByRole('button', { name: 'Создать синтетическое задание' }));
  await screen.findByText('Показан последний известный статус. Обновление приостановлено.');
  expect(screen.getByText('Статус: В очереди')).toBeVisible();
  expect(screen.getByText('API недоступен.')).toBeVisible();
  expect(screen.queryByText('API и PostgreSQL доступны.')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить связь' }));
  await screen.findByText('API и PostgreSQL доступны.');
  await screen.findByText('Статус: Завершено');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenNthCalledWith(5, `/api/synthetic-jobs/${jobId}`, expect.any(Object));
});

it('не выдаёт непризнанный ответ за завершённое синтетическое задание', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(health())
    .mockResolvedValueOnce(Response.json({ ...syntheticJob('completed'), synthetic: false })));
  renderApp();
  await screen.findByText('API и PostgreSQL доступны.');
  fireEvent.click(screen.getByRole('button', { name: 'Создать синтетическое задание' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось подтвердить создание задания.');
  expect(screen.queryByText('Статус: Завершено')).not.toBeInTheDocument();
});

it('показывает технический сбой задания без успешного результата', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(health())
    .mockResolvedValueOnce(Response.json(syntheticJob('failed'))));
  renderApp();
  await screen.findByText('API и PostgreSQL доступны.');
  fireEvent.click(screen.getByRole('button', { name: 'Создать синтетическое задание' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Синтетическое задание завершилось с ошибкой.');
  expect(screen.queryByText(/Тестовый результат:/)).not.toBeInTheDocument();
});

it('отменяет незавершённый запрос при уходе со страницы', async () => {
  const signals: AbortSignal[] = [];
  vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.signal) signals.push(init.signal);
    return new Promise<Response>(() => {});
  }));
  const app = renderApp();
  await waitFor(() => expect(signals).toHaveLength(1));
  app.unmount();
  expect(signals[0].aborted).toBe(true);
});
