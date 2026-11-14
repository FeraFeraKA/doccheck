import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes, useParams } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { CheckDetail, NewCheck } from '../../src/pages/checks';

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
      <Route path="/checks/new" element={<><NewCheck /><Link to="/checks/other">Другая страница</Link></>} />
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
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('group', { name: 'Строка КФЗ' })).not.toBeInTheDocument();
  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
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

  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
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

it('предлагает ручной выбор после неоднозначного скана и возвращается к обычной загрузке', async () => {
  const fetchMock = vi.fn<typeof fetch>().mockImplementation(async (url, init) => {
    if (init?.method === 'POST') return accept('retry-run');
    if (String(url) === '/api/v0/runs/ambiguous-scan') {
      return Response.json({
        run_id: 'ambiguous-scan',
        status: 'failed',
        created_at: '2031-02-01T00:00:00Z',
        progress: null,
        error: { code: 'scan_scope_required', message: 'Не удалось выбрать строку.' },
      });
    }
    return Response.json({ items: [], next_cursor: null });
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<MemoryRouter initialEntries={['/checks/ambiguous-scan']}>
    <Routes>
      <Route path="/checks/:id" element={<CheckDetail view="table" />} />
      <Route path="/checks/new" element={<NewCheck />} />
    </Routes>
  </MemoryRouter>);

  fireEvent.click(await screen.findByRole('link', { name: 'Выбрать строку КФЗ вручную' }));
  selectPacket();
  const fields = screen.getByRole('group', { name: 'Строка КФЗ' });
  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
  expect(submit).toBeDisabled();
  for (const [label, value] of [
    ['Номер договора', 'СИНТ-31'],
    ['Начало периода', '2031-02-01'],
    ['Конец периода', '2031-02-28'],
    ['Этап', '2'],
    ['Страница', '3'],
  ]) {
    fireEvent.change(within(fields).getByLabelText(label), { target: { value } });
  }
  expect(submit).toBeEnabled();
  fireEvent.click(submit);
  expect(await screen.findByRole('link', { name: 'Проверка КФЗ №retry-run' })).toBeVisible();
  const submission = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')?.[1];
  const form = submission?.body;
  if (!(form instanceof FormData)) throw new Error('Ожидался multipart');
  expect(form.get('contract_number')).toBe('СИНТ-31');
  expect(form.get('period_start')).toBe('2031-02-01');
  expect(form.get('period_end')).toBe('2031-02-28');
  expect(JSON.parse(String(form.get('report_row_locator')))).toEqual({
    kind: 'page',
    page: 3,
    fragment_id: 'kfz-stage-2-2031',
  });
  expect(form.has('complete_package')).toBe(false);
  selectPacket();
  expect(screen.queryByRole('group', { name: 'Строка КФЗ' })).not.toBeInTheDocument();
});

it('отменяет запрос при уходе из мастера', async () => {
  const fetchMock = vi.fn<typeof fetch>().mockImplementation((_path, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(init.signal?.reason), { once: true });
  }));
  vi.stubGlobal('fetch', (url: RequestInfo | URL, init?: RequestInit) =>
    init?.method === 'POST' ? fetchMock(url, init) : Promise.resolve(
      Response.json({ items: [], next_cursor: null }),
    ));
  renderWizard();
  selectPacket();

  fireEvent.click(screen.getByRole('button', { name: 'Запустить проверку' }));
  const state = fetchMock.mock.calls[0][1];
  fireEvent.click(screen.getByRole('link', { name: 'Другая страница' }));
  expect(await screen.findByRole('heading', { name: 'Карточка other' })).toBeVisible();
  await waitFor(() => expect(state?.signal?.aborted).toBe(true));
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('принимает первичные документы до отчёта и показывает ошибки отдельно', async () => {
  mockUpload();
  renderWizard();
  await screen.findByText('В очереди пока нет проверок.');
  const report = screen.getByRole('region', { name: 'КФЗ' });
  const documents = screen.getByRole('region', { name: 'Первичные документы' });

  pick('Выберите КФЗ', [new File([], 'empty.pdf')]);
  pick('Выберите первичные документы', [new File(['support'], 'support.xlsx')]);
  expect(within(documents).getByText('support.xlsx')).toBeVisible();
  expect(within(report).getByRole('alert')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Запустить проверку' })).toBeDisabled();

  pick('Выберите КФЗ', [new File(['synthetic report'], 'report.docx')]);
  expect(within(report).queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Запустить проверку' })).toBeEnabled();
});
