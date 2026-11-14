import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useParams } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { NewCheck } from '../../src/pages/checks';

afterEach(() => vi.unstubAllGlobals());

function mockUpload(...responses: Array<Response | Promise<Response> | Error>) {
  const pending = [...responses];
  const upload = vi.fn<typeof fetch>().mockImplementation(async () => {
    const next = pending.shift();
    if (next instanceof Error) throw next;
    if (!next) throw new Error('Unexpected upload');
    return await next;
  });
  vi.stubGlobal('fetch', (url: RequestInfo | URL, init?: RequestInit) =>
    init?.method === 'POST' ? upload(url, init) : Promise.resolve(
      Response.json({ items: [], next_cursor: null }),
    ));
  return upload;
}

function RunCard() {
  const { id } = useParams();
  return <h1>Карточка {id}</h1>;
}

function renderWizard() {
  render(<MemoryRouter initialEntries={['/checks/new']}>
    <Routes>
      <Route path="/checks/new" element={<NewCheck />} />
      <Route path="/checks/:id" element={<RunCard />} />
    </Routes>
  </MemoryRouter>);
}

function pick(label: string, files: File[]) {
  fireEvent.change(screen.getByLabelText(label), { target: { files } });
}

function selectPacket() {
  pick('Выберите КФЗ', [new File(['synthetic report'], 'report.pdf')]);
  pick('Выберите первичные документы', [
    new File(['synthetic second'], 'B.xlsx'),
    new File(['synthetic first'], 'A.docx'),
  ]);
}

function accept(id: string) {
  return Response.json({ run_id: id, status: 'queued' }, {
    status: 202,
    headers: { Location: '/api/v0/runs/' + id },
  });
}

it('отправляет только два поля, блокирует двойное действие и оставляет форму готовой к следующему комплекту', async () => {
  let finish: ((response: Response) => void) | undefined;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const fetchMock = mockUpload(pending, accept('second-run'));

  renderWizard();
  selectPacket();
  const submit = screen.getByRole('button', { name: 'Отправить на проверку' });
  fireEvent.click(submit);
  fireEvent.click(submit);
  expect(submit).toBeDisabled();
  expect(screen.getByRole('status')).toHaveTextContent('Загрузка файлов');
  expect(fetchMock).toHaveBeenCalledTimes(1);

  const [url, init] = fetchMock.mock.calls[0];
  expect(String(url)).toMatch(/\/api\/v0\/runs$/);
  const form = init?.body;
  if (!(form instanceof FormData)) throw new Error('Ожидался multipart');
  expect(Array.from(form.keys())).toEqual(['report', 'documents', 'documents']);
  expect(form.getAll('documents')).toMatchObject([{ name: 'B.xlsx' }, { name: 'A.docx' }]);
  finish?.(accept('saved-run'));
  expect(await screen.findByRole('link', { name: 'Проверка КФЗ №saved-run' })).toHaveAttribute('href', '/checks/saved-run');
  expect(screen.queryByText('report.pdf')).not.toBeInTheDocument();
  expect(submit).toBeDisabled();
  pick('Выберите КФЗ', [new File(['report two'], 'second.pdf')]);
  pick('Выберите первичные документы', [new File(['new support'], 'support.png')]);
  fireEvent.click(submit);
  expect(await screen.findByRole('link', { name: 'Проверка КФЗ №second-run' })).toBeVisible();
  expect(screen.getByRole('link', { name: 'Проверка КФЗ №saved-run' })).toBeVisible();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  const firstKey = new Headers(fetchMock.mock.calls[0][1]?.headers).get('Idempotency-Key');
  const secondKey = new Headers(fetchMock.mock.calls[1][1]?.headers).get('Idempotency-Key');
  expect(secondKey).not.toBe(firstKey);
});

it('повторяет тот же ключ после потери ответа и создаёт новый при изменении пакета', async () => {
  const fetchMock = mockUpload(
    new TypeError('network'),
    Response.json({ code: 'invalid_input', message: 'Проверьте КФЗ' }, { status: 422 }),
    accept('new-run'),
  );
  renderWizard();
  selectPacket();

  const submit = screen.getByRole('button', { name: 'Отправить на проверку' });
  fireEvent.click(submit);
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось подтвердить приём пакета');
  fireEvent.click(submit);
  expect(await screen.findByRole('alert')).toHaveTextContent('Проверьте КФЗ');

  fireEvent.click(screen.getByRole('button', { name: 'Удалить B.xlsx' }));
  fireEvent.click(submit);
  expect(await screen.findByRole('link', { name: 'Проверка КФЗ №new-run' })).toBeVisible();
  const attempts = fetchMock.mock.calls.map(([, init]) => new Headers(init?.headers).get('Idempotency-Key'));
  expect(attempts[0]).toMatch(/^[a-f0-9-]{36}$/);
  expect(attempts[1]).toBe(attempts[0]);
  expect(attempts[2]).not.toBe(attempts[0]);
});

it('не отправляет синтетический пример и отменяет запрос при уходе', async () => {
  const fetchMock = vi.fn<typeof fetch>().mockImplementation((_path, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
  }));
  vi.stubGlobal('fetch', (url: RequestInfo | URL, init?: RequestInit) =>
    init?.method === 'POST' ? fetchMock(url, init) : Promise.resolve(
      Response.json({ items: [], next_cursor: null }),
    ));
  renderWizard();
  selectPacket();

  fireEvent.click(screen.getByRole('button', { name: 'Отправить на проверку' }));
  const state = fetchMock.mock.calls[0][1];
  fireEvent.click(screen.getByRole('link', { name: 'Открыть готовый синтетический результат' }));
  expect(await screen.findByRole('heading', { name: 'Карточка synthetic-example' })).toBeVisible();
  await waitFor(() => expect(state?.signal?.aborted).toBe(true));
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('принимает первичные документы до отчёта и показывает ошибки отдельно', async () => {
  mockUpload();
  renderWizard();
  await screen.findByText('Проверок пока нет.');
  const report = screen.getByRole('region', { name: 'КФЗ' });
  const documents = screen.getByRole('region', { name: 'Первичные документы' });

  pick('Выберите КФЗ', [new File([], 'empty.pdf')]);
  pick('Выберите первичные документы', [new File(['support'], 'support.xlsx')]);
  expect(within(documents).getByText('support.xlsx')).toBeVisible();
  expect(within(report).getByRole('alert')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Отправить на проверку' })).toBeDisabled();

  pick('Выберите КФЗ', [new File(['synthetic report'], 'report.docx')]);
  expect(within(report).queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Отправить на проверку' })).toBeEnabled();
});
