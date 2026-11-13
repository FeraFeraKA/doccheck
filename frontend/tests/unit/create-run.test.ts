// @vitest-environment node
import { afterEach, expect, it, vi } from 'vitest';
import {
  InvalidRunUploadResponse,
  prepareRunUpload,
  RunUploadHttpError,
} from '../../src/pages/checks/createRun';
import type { RunUpload } from '../../src/pages/checks/createRun';

const key = '71c5c2f0-83d3-43bf-9237-da388101e51f';
const nextKey = 'b50a4ef0-8ea0-4cc1-b940-0ff17fba1d64';
const runId = 'run_123-test';
const location = '/api/v0/runs/' + runId;

function upload(): RunUpload {
  return {
    report: new File(['synthetic report'], 'report.pdf', { type: 'application/pdf' }),
    documents: [
      new File(['synthetic second'], 'B.xlsx'),
      new File(['synthetic first'], 'A.docx'),
    ],
    contract_number: 'КФЗ-2',
    period_start: '2025-01-01',
    period_end: '2025-02-28',
    report_row_locator: { kind: 'page', page: 2, table_row: 8, table_column: 1 },
  };
}

function accepted(id = runId) {
  return Response.json({ run_id: id, status: 'queued' }, {
    status: 202,
    headers: { Location: '/api/v0/runs/' + id },
  });
}

function stubFetch() {
  const fetchMock = vi.fn<(path: string, init: RequestInit) => Promise<Response>>();
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

it('отправляет multipart с файлами в заданном порядке и читает подтверждение 202', async () => {
  const fetchMock = stubFetch().mockResolvedValueOnce(accepted());
  const input = upload();
  const signal = new AbortController().signal;

  await expect(prepareRunUpload(input, key)(signal)).resolves.toEqual({
    run_id: runId,
    status: 'queued',
    location,
  });

  const [path, init] = fetchMock.mock.calls[0];
  expect(path).toBe('/api/v0/runs');
  expect(init).toMatchObject({ method: 'POST', signal, redirect: 'error' });
  const request = new Request('http://localhost' + path, init);
  expect(request.headers.get('Content-Type')).toMatch(/^multipart\/form-data; boundary=/);
  expect(request.headers.get('Idempotency-Key')).toBe(key);
  const form = await request.formData();
  expect(Array.from(form.keys())).toEqual([
    'report', 'documents', 'documents',
    'contract_number', 'period_start', 'period_end', 'report_row_locator',
  ]);
  expect(form.get('report')).toMatchObject({ name: 'report.pdf', type: 'application/pdf' });
  expect(form.getAll('documents')).toMatchObject([{ name: 'B.xlsx' }, { name: 'A.docx' }]);
  const firstDocument = form.getAll('documents')[0];
  if (!(firstDocument instanceof File)) throw new Error('Отсутствует первый файл');
  expect(await firstDocument.text()).toBe('synthetic second');
  expect(form.get('contract_number')).toBe(input.contract_number);
  expect(form.get('period_start')).toBe(input.period_start);
  expect(form.get('period_end')).toBe(input.period_end);
  expect(form.get('report_row_locator')).toBe(JSON.stringify(input.report_row_locator));
});

it('сохраняет исходный ключ и пакет при явном повторе после сетевого сбоя', async () => {
  const networkError = new TypeError('network unavailable');
  const fetchMock = stubFetch()
    .mockRejectedValueOnce(networkError)
    .mockResolvedValueOnce(accepted())
    .mockResolvedValueOnce(accepted('new-run'));
  const input = upload();
  const attempt = prepareRunUpload(input, key);

  await expect(attempt()).rejects.toBe(networkError);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  input.contract_number = 'Новый договор';
  input.documents = [...input.documents].reverse();

  await expect(attempt()).resolves.toMatchObject({ run_id: runId });
  await expect(prepareRunUpload(input, nextKey)()).resolves.toMatchObject({ run_id: 'new-run' });

  const first = fetchMock.mock.calls[0][1];
  const retry = fetchMock.mock.calls[1][1];
  const next = fetchMock.mock.calls[2][1];
  expect(first.headers).toEqual({ 'Idempotency-Key': key });
  expect(retry.headers).toEqual(first.headers);
  expect(next.headers).toEqual({ 'Idempotency-Key': nextKey });
  expect(retry.body).toBeInstanceOf(FormData);
  expect(next.body).toBeInstanceOf(FormData);
  if (!(retry.body instanceof FormData) || !(next.body instanceof FormData)) throw new Error('Ожидался multipart');
  expect(retry.body.get('contract_number')).toBe('КФЗ-2');
  expect(retry.body.getAll('documents')).toMatchObject([{ name: 'B.xlsx' }, { name: 'A.docx' }]);
  expect(next.body.get('contract_number')).toBe('Новый договор');
  expect(next.body.getAll('documents')).toMatchObject([{ name: 'A.docx' }, { name: 'B.xlsx' }]);
});

it.each([
  [409, { code: 'idempotency_conflict', message: 'Изменён пакет' }],
  [422, { code: 'invalid_input', message: 'Некорректный файл', field: 'documents', file_index: 0 }],
])('возвращает структурированную ошибку HTTP %s без повторной отправки', async (status, details) => {
  const fetchMock = stubFetch().mockResolvedValueOnce(Response.json(details, { status }));
  const promise = prepareRunUpload(upload(), key)();

  await expect(promise).rejects.toBeInstanceOf(RunUploadHttpError);
  await expect(promise).rejects.toMatchObject({ status, details });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('сохраняет статус HTTP для ответа прокси без JSON', async () => {
  stubFetch().mockResolvedValueOnce(new Response('<html>Request too large</html>', { status: 413 }));

  await expect(prepareRunUpload(upload(), key)()).rejects.toMatchObject({
    name: 'RunUploadHttpError',
    status: 413,
    details: null,
  });
});

it.each([
  [200, { run_id: runId, status: 'queued' }, location],
  [202, { run_id: runId, status: 'completed' }, location],
  [202, { run_id: '../other', status: 'queued' }, '/api/v0/runs/../other'],
  [202, { run_id: runId, status: 'queued' }, '/api/v0/runs/other'],
  [202, { run_id: runId, status: 'queued' }, 'https://example.com'],
  [202, { run_id: runId, status: 'queued' }, undefined],
])('не принимает ответ с HTTP %s и несогласованным телом или Location', async (status, value, header) => {
  stubFetch().mockResolvedValueOnce(Response.json(value, {
    status,
    headers: header === undefined ? undefined : { Location: header },
  }));

  await expect(prepareRunUpload(upload(), key)()).rejects.toBeInstanceOf(InvalidRunUploadResponse);
});

it('передаёт отмену потребителю', async () => {
  const controller = new AbortController();
  controller.abort();
  const fetchMock = stubFetch().mockRejectedValueOnce(controller.signal.reason);

  await expect(prepareRunUpload(upload(), key)(controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
  expect(fetchMock).toHaveBeenCalledWith('/api/v0/runs', expect.objectContaining({ signal: controller.signal }));
});
