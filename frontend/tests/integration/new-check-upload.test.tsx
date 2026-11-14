import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { NewCheck } from '../../src/pages/checks/NewCheck';
import type { InitialRunPack } from '../../src/pages/checks/NewCheck';
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
  let updateProgress: ((percent: number) => void) | undefined;
  const send = vi.fn<ReturnType<typeof prepareRunTransfer>>().mockImplementation((_signal, progress) => {
    updateProgress = progress;
    return pendingUpload.promise;
  });
  const reading = vi.spyOn(FileReader.prototype, 'readAsArrayBuffer');
  prepareTransfer.mockReturnValue(send);
  startRun.mockReturnValue(pendingStart.promise);

  renderWizard();
  selectPacket();
  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
  expect(screen.getByRole('status')).toHaveTextContent('Чтение файлов');
  expect(submit).toBeDisabled();
  expect(prepareTransfer).not.toHaveBeenCalled();

  const bar = await screen.findByRole('progressbar', { name: 'Загрузка пакета' });
  expect(bar).toHaveAttribute('aria-valuenow', '0');
  expect(screen.getByText('0%', { exact: true })).toBeVisible();
  act(() => updateProgress?.(37));
  expect(bar).toHaveAttribute('aria-valuenow', '37');
  expect(screen.getByText('37%', { exact: true })).toBeVisible();
  expect(submit).toBeDisabled();
  act(() => updateProgress?.(100));
  expect(screen.getByText('Ожидаем подтверждения загрузки…')).toBeVisible();
  expect(screen.getByText('100%', { exact: true })).toBeVisible();
  expect(reading).toHaveBeenCalledTimes(3);
  expect(send).toHaveBeenCalledTimes(1);
  expect(bar).toHaveAttribute('aria-valuenow', '100');
  expect(submit).toBeDisabled();
  expect(startRun).not.toHaveBeenCalled();

  const [packet, key] = prepareTransfer.mock.calls[0];
  expect(key).toMatch(/^[a-f0-9-]{36}$/);
  expect(packet.report?.name).toBe('report.pdf');
  expect(packet.documents.map((file) => file.name)).toEqual(['B.xlsx', 'A.docx']);
  pendingUpload.resolve({ upload_id: 'first-upload' });
  await waitFor(() => expect(submit).toBeEnabled());
  expect(bar).not.toBeInTheDocument();

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

it('повторяет передачу того же пакета, а смена файлов освобождает сохранённый комплект', async () => {
  const retry = defer<{ upload_id: string }>();
  const send = vi.fn<ReturnType<typeof prepareRunTransfer>>()
    .mockImplementationOnce((_signal, progress) => {
      progress?.(55);
      return Promise.reject(new TypeError('network'));
    })
    .mockReturnValueOnce(retry.promise);
  prepareTransfer.mockReturnValueOnce(send)
    .mockReturnValueOnce(vi.fn().mockResolvedValue({ upload_id: 'new-upload' }));
  renderWizard();
  selectPacket();

  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось подтвердить приём пакета');
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }));
  const submit = screen.getByRole('button', { name: 'Запустить проверку' });
  expect(screen.getByRole('progressbar', { name: 'Загрузка пакета' })).toHaveAttribute('aria-valuenow', '0');
  expect(submit).toBeDisabled();
  retry.resolve({ upload_id: 'first-upload' });
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

  expect(screen.getByRole('heading', { name: 'Изменение комплекта · КФЗ.pdf' })).toBeVisible();
  expect(screen.getByRole('link', { name: 'К результату' })).toHaveAttribute('href', '/checks/saved-run');
  expect(screen.queryByRole('region', { name: 'Последние проверки' })).not.toBeInTheDocument();
  const submit = screen.getByRole('button', { name: 'Запустить повторную проверку' });
  expect(submit).toBeDisabled();
  expect(prepareTransfer).not.toHaveBeenCalled();

  const pending = defer<{ upload_id: string }>();
  prepareTransfer.mockReturnValueOnce(vi.fn().mockReturnValue(pending.promise));
  const replace = screen.getByRole('button', { name: 'Заменить Акт.xlsx' });
  fireEvent.click(replace);
  pick('Выберите замену первичного документа', [new File(['invalid selection'], 'bad.txt')]);
  expect(screen.getByText('Акт.xlsx')).toBeVisible();
  expect(screen.getByRole('alert')).toHaveTextContent('Добавьте непустые PDF, DOCX, XLSX или PNG.');
  expect(prepareTransfer).not.toHaveBeenCalled();

  const replacement = new File(['new synthetic workbook'], 'Акт-замена.xlsx');
  fireEvent.click(replace);
  pick('Выберите замену первичного документа', [replacement]);
  expect(screen.queryByText('Акт.xlsx')).not.toBeInTheDocument();
  expect(screen.getByText('Акт.docx')).toBeVisible();
  expect(screen.getByText('Акт-замена.xlsx')).toBeVisible();
  await waitFor(() => expect(prepareTransfer).toHaveBeenCalledTimes(1));
  expect(prepareTransfer.mock.calls[0][0]).toEqual({
    report: undefined, documents: [replacement], sourceRunId: 'saved-run', retainedDocumentIds: ['report', 'existing-two'],
  });
  expect(submit).toBeDisabled();
  pending.resolve({ upload_id: 'uploaded-edit' });
  await waitFor(() => expect(submit).toBeEnabled());

  fireEvent.click(screen.getByRole('button', { name: 'Удалить Акт-замена.xlsx' }));
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
