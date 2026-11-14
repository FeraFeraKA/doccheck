import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CheckDetail } from '../../src/pages/checks';
import { NewCheck } from '../../src/pages/checks/NewCheck';
import type { InitialRunPack } from '../../src/pages/checks/NewCheck';
import { RunPackEditor } from '../../src/pages/checks/RunPackEditor';
import { discardPreparedRun, prepareRunTransfer, RunUploadHttpError, startPreparedRun } from '../../src/pages/checks/createRun';

vi.mock('../../src/pages/checks/createRun', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../src/pages/checks/createRun')>();
  return {
    ...original,
    prepareRunTransfer: vi.fn(),
    startPreparedRun: vi.fn(),
    discardPreparedRun: vi.fn(),
  };
});

const prepareTransfer = vi.mocked(prepareRunTransfer);
const startRun = vi.mocked(startPreparedRun);
const discard = vi.mocked(discardPreparedRun);

beforeEach(() => {
  startRun.mockReset();
  prepareTransfer.mockReset();
  discard.mockReset().mockResolvedValue(undefined);
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() =>
    Promise.resolve(Response.json({ items: [], next_cursor: null })),
  ));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function WizardRoute({ initialPack }: { initialPack?: InitialRunPack }) {
  const { search } = useLocation();
  const editing = new URLSearchParams(search).has('from');
  return <NewCheck key={editing ? 'editing' : 'new'} initialPack={editing ? initialPack : undefined} />;
}

function renderWizard(initialPack?: InitialRunPack) {
  render(<MemoryRouter initialEntries={[initialPack ? '/checks/new?from=saved' : '/checks/new']}>
    <Routes>
      <Route path="/checks/new" element={<WizardRoute initialPack={initialPack} />} />
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

function accepted(id: string): Awaited<ReturnType<typeof startPreparedRun>> {
  return { run_id: id, status: 'queued', location: '/api/v0/runs/' + id };
}

function defer<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

it('берёт файлы после чтения, ждёт подтверждения передачи и запускает только по нажатию', async () => {
  const pendingUpload = defer<{ upload_id: string }>();
  const pendingStart = defer<Awaited<ReturnType<typeof startPreparedRun>>>();
  const send = vi.fn<ReturnType<typeof prepareRunTransfer>>().mockImplementation((_signal, progress) => {
    progress?.(100);
    return pendingUpload.promise;
  });
  const reading = vi.spyOn(FileReader.prototype, 'readAsArrayBuffer');
  prepareTransfer.mockReturnValue(send);
  startRun.mockReturnValue(pendingStart.promise);

  renderWizard();
  selectPacket();
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('group', { name: 'Строка КФЗ' })).not.toBeInTheDocument();
  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
  expect(screen.getByRole('status')).toHaveTextContent('Чтение файлов');
  expect(submit).toBeDisabled();
  expect(prepareTransfer).not.toHaveBeenCalled();

  await screen.findByText('Ожидаем подтверждения загрузки…');
  expect(reading).toHaveBeenCalledTimes(3);
  expect(send).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('progressbar', { name: 'Загрузка пакета' })).toHaveAttribute('aria-valuenow', '100');
  expect(submit).toBeDisabled();
  expect(startRun).not.toHaveBeenCalled();

  const [packet, key] = prepareTransfer.mock.calls[0];
  expect(key).toMatch(/^[a-f0-9-]{36}$/);
  expect(packet.report?.name).toBe('report.pdf');
  expect(packet.documents.map((file) => file.name)).toEqual(['B.xlsx', 'A.docx']);
  expect(packet.scanScope).toBeUndefined();
  pendingUpload.resolve({ upload_id: 'first-upload' });
  await waitFor(() => expect(submit).toBeEnabled());

  fireEvent.click(submit);
  fireEvent.click(submit);
  expect(startRun).toHaveBeenCalledExactlyOnceWith('first-upload', expect.any(AbortSignal));
  expect(submit).toBeDisabled();
  expect(screen.getByRole('status')).toHaveTextContent('Запуск проверки');
  pendingStart.resolve(accepted('saved-run'));
  const queue = screen.getByRole('region', { name: 'Последние проверки' });
  expect(await within(queue).findByRole('heading', { name: 'Проверка КФЗ №saved-run' })).toBeVisible();
  expect(within(queue).queryByRole('link', { name: 'Проверка КФЗ №saved-run' })).not.toBeInTheDocument();
  expect(screen.queryByText('report.pdf')).not.toBeInTheDocument();
  expect(discard).not.toHaveBeenCalled();
});

it('загружает пакет с явным выбором строки только после заполнения реквизитов', async () => {
  prepareTransfer.mockReturnValue(vi.fn().mockResolvedValue({ upload_id: 'manual-upload' }));
  startRun.mockResolvedValue(accepted('retry-run'));
  vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockImplementation(async (url) => {
    if (String(url) === '/api/v0/runs/ambiguous-scan') {
      return Response.json({
        run_id: 'ambiguous-scan', status: 'failed', created_at: '2031-02-01T00:00:00Z',
        progress: null, error: { code: 'scan_scope_required', message: 'Не удалось выбрать строку.' },
      });
    }
    if (String(url) === '/api/v0/runs/ambiguous-scan/pack') {
      return Response.json({ documents: [
        { id: 'report', name: 'КФЗ.pdf', size: 512, role: 'report' },
        { id: 'act', name: 'Акт.docx', size: 512, role: 'supporting' },
      ] });
    }
    if (String(url) === '/api/v0/runs/retry-run') {
      return Response.json({
        run_id: 'retry-run', status: 'queued', created_at: '2031-02-01T00:00:00Z',
        progress: { processed_documents: 0, total_documents: 2 }, error: null,
      });
    }
    return Response.json({ items: [], next_cursor: null });
  }));
  render(<MemoryRouter initialEntries={['/checks/ambiguous-scan']}>
    <Routes>
      <Route path="/checks/:id" element={<CheckDetail view="table" />} />
      <Route path="/checks/new" element={<RunPackEditor />} />
    </Routes>
  </MemoryRouter>);
  fireEvent.click(await screen.findByRole('link', { name: 'Выбрать строку КФЗ вручную' }));
  const fields = await screen.findByRole('group', { name: 'Строка КФЗ' });
  expect(screen.getByText('КФЗ.pdf')).toBeVisible();
  expect(screen.getByText('Акт.docx')).toBeVisible();
  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
  expect(submit).toBeDisabled();
  for (const [label, value] of [
    ['Номер договора', ' СИНТ-31 '],
    ['Начало периода', '2031-02-01'],
    ['Конец периода', '2031-02-28'],
    ['Этап', '2'],
    ['Страница', '3'],
  ]) {
    expect(prepareTransfer).not.toHaveBeenCalled();
    fireEvent.change(within(fields).getByLabelText(label), { target: { value } });
  }
  await waitFor(() => expect(submit).toBeEnabled());
  expect(prepareTransfer.mock.calls[0][0]).toEqual({
    sourceRunId: 'ambiguous-scan', retainedDocumentIds: ['report', 'act'], report: undefined, documents: [],
    scanScope: {
      contractNumber: 'СИНТ-31', periodStart: '2031-02-01', periodEnd: '2031-02-28', stage: 2, page: 3,
    },
  });
  fireEvent.click(submit);
  expect(startRun).toHaveBeenCalledExactlyOnceWith('manual-upload', expect.any(AbortSignal));
  expect(await screen.findByRole('heading', { name: 'Новая проверка' })).toBeVisible();
  expect(screen.queryByText('КФЗ.pdf')).not.toBeInTheDocument();
  selectPacket();
  expect(screen.queryByRole('group', { name: 'Строка КФЗ' })).not.toBeInTheDocument();
});

it('повторяет передачу того же пакета, а смена файлов освобождает сохранённый комплект', async () => {
  const send = vi.fn<ReturnType<typeof prepareRunTransfer>>()
    .mockRejectedValueOnce(new TypeError('network'))
    .mockResolvedValueOnce({ upload_id: 'first-upload' });
  prepareTransfer.mockReturnValueOnce(send)
    .mockReturnValueOnce(vi.fn().mockResolvedValue({ upload_id: 'new-upload' }));
  renderWizard();
  selectPacket();

  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось подтвердить приём пакета');
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }));
  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
  await waitFor(() => expect(submit).toBeEnabled());
  expect(prepareTransfer).toHaveBeenCalledTimes(1);
  expect(send).toHaveBeenCalledTimes(2);

  fireEvent.click(screen.getByRole('button', { name: 'Удалить B.xlsx' }));
  await waitFor(() => expect(prepareTransfer).toHaveBeenCalledTimes(2));
  expect(discard).toHaveBeenCalledWith('first-upload', expect.any(AbortSignal));
  expect(prepareTransfer.mock.calls[1][0].documents.map((file) => file.name)).toEqual(['A.docx']);
  expect(prepareTransfer.mock.calls[1][1]).not.toBe(prepareTransfer.mock.calls[0][1]);
});

it('не использует запоздалое подтверждение отменённой передачи', async () => {
  const previous = defer<{ upload_id: string }>();
  const current = defer<{ upload_id: string }>();
  const sendFirst = vi.fn<ReturnType<typeof prepareRunTransfer>>().mockReturnValue(previous.promise);
  prepareTransfer.mockReturnValueOnce(sendFirst).mockReturnValueOnce(vi.fn().mockReturnValue(current.promise));
  renderWizard();
  selectPacket();
  await waitFor(() => expect(sendFirst).toHaveBeenCalledTimes(1));
  const signal = sendFirst.mock.calls[0][0];

  pick('Выберите КФЗ', [new File(['replacement'], 'new.pdf')]);
  await waitFor(() => expect(prepareTransfer).toHaveBeenCalledTimes(2));
  expect(signal?.aborted).toBe(true);

  previous.resolve({ upload_id: 'stale-upload' });
  await waitFor(() => expect(discard).toHaveBeenCalledWith('stale-upload', expect.any(AbortSignal)));
  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
  expect(submit).toBeDisabled();

  current.resolve({ upload_id: 'new-upload' });
  await waitFor(() => expect(submit).toBeEnabled());
});

it('повторяет запуск с тем же сохранённым пакетом, если его подтверждение потерялось', async () => {
  prepareTransfer.mockReturnValue(vi.fn().mockResolvedValue({ upload_id: 'uploaded' }));
  startRun.mockRejectedValueOnce(new TypeError('network')).mockResolvedValueOnce(accepted('saved-run'));
  renderWizard();
  selectPacket();

  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось подтвердить запуск');
  fireEvent.click(submit);
  expect(await screen.findByRole('heading', { name: 'Проверка КФЗ №saved-run' })).toBeVisible();
  expect(startRun.mock.calls.map(([id]) => id)).toEqual(['uploaded', 'uploaded']);
  expect(prepareTransfer).toHaveBeenCalledTimes(1);
  expect(discard).not.toHaveBeenCalled();
});

it('перезагружает выбранные файлы после истечения сохранённого пакета', async () => {
  prepareTransfer.mockReturnValueOnce(vi.fn().mockResolvedValue({ upload_id: 'expired' }))
    .mockReturnValueOnce(vi.fn().mockResolvedValue({ upload_id: 'renewed' }));
  startRun.mockRejectedValueOnce(new RunUploadHttpError(410, null)).mockResolvedValueOnce(accepted('saved-run'));
  renderWizard();
  selectPacket();

  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  await waitFor(() => expect(prepareTransfer).toHaveBeenCalledTimes(2));
  expect(prepareTransfer.mock.calls[1][1]).not.toBe(prepareTransfer.mock.calls[0][1]);
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  expect(await screen.findByRole('heading', { name: 'Проверка КФЗ №saved-run' })).toBeVisible();
  expect(startRun.mock.calls.map(([id]) => id)).toEqual(['expired', 'renewed']);
});

it('переиспользует выбранные серверные документы при редактировании и возвращается в очередь', async () => {
  prepareTransfer.mockReturnValue(vi.fn().mockResolvedValue({ upload_id: 'uploaded-edit' }));
  startRun.mockResolvedValue(accepted('edited-run'));
  renderWizard({
    runId: 'saved-run',
    documents: [
      { id: 'report', name: 'КФЗ.pdf', size: 512, role: 'report' },
      { id: 'existing-one', name: 'Акт.xlsx', size: 512, role: 'supporting' },
      { id: 'existing-two', name: 'Акт.docx', size: 512, role: 'supporting' },
    ],
  });

  expect(screen.getByRole('heading', { name: 'Изменить комплект' })).toBeVisible();
  expect(screen.getByRole('link', { name: 'К результату' })).toHaveAttribute('href', '/checks/saved-run');
  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Удалить Акт.xlsx' }));
  await waitFor(() => expect(prepareTransfer).toHaveBeenCalledTimes(2));
  expect(prepareTransfer.mock.calls[1][0]).toEqual({
    report: undefined, documents: [], sourceRunId: 'saved-run', retainedDocumentIds: ['report', 'existing-two'],
  });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  expect(await screen.findByRole('heading', { name: 'Новая проверка' })).toBeVisible();
  expect(screen.getByRole('region', { name: 'Последние проверки' })).toHaveAttribute('id', 'queue');
});

it('принимает первичные документы до отчёта и показывает ошибки отдельно', async () => {
  prepareTransfer.mockReturnValue(vi.fn().mockResolvedValue({ upload_id: 'uploaded' }));
  renderWizard();
  const report = screen.getByRole('region', { name: 'КФЗ' });
  const documents = screen.getByRole('region', { name: 'Первичные документы' });
  const submit = screen.getByRole('button', { name: 'Запустить проверку' });

  pick('Выберите КФЗ', [new File([], 'empty.pdf')]);
  pick('Выберите первичные документы', [new File(['support'], 'support.xlsx')]);
  expect(within(documents).getByText('support.xlsx')).toBeVisible();
  expect(within(report).getByRole('alert')).toBeVisible();
  expect(submit).toBeDisabled();
  expect(prepareTransfer).not.toHaveBeenCalled();

  pick('Выберите КФЗ', [new File(['synthetic report'], 'report.docx')]);
  expect(within(report).queryByRole('alert')).not.toBeInTheDocument();
  await waitFor(() => expect(submit).toBeEnabled());
});
