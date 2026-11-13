import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  getSourceEvidence, getSourceOriginal, InvalidSourceResponseError, SourceHttpError,
} from '../../src/pages/checks/sourceApi';

const documentUrl = '/api/v0/runs/run-1/documents/report-1';
const evidence = {
  id: 'evidence-1',
  document_id: 'report-1',
  kind: 'amount',
  raw_value: '12 345,67',
  normalized_value: '12345.67',
  unit: 'RUB',
  method: 'synthetic',
  locator: { kind: 'page', page: 1, bbox: [0, 0.1, 0.5, 1], fragment_id: null },
};

function respond(response: Response) {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('source API', () => {
  it('reads original bytes only from the contract endpoint', async () => {
    const fetchMock = respond(new Response(new Uint8Array([1, 2, 3]), {
      headers: { 'Content-Type': 'application/octet-stream' },
    }));
    const signal = new AbortController().signal;
    const original = await getSourceOriginal('run-1', 'report-1', signal);

    expect(new Uint8Array(await original.arrayBuffer())).toEqual(new Uint8Array([1, 2, 3]));
    expect(fetchMock).toHaveBeenCalledWith(documentUrl, { signal });
  });

  it.each([
    new Response('<html>Unexpected page</html>', { headers: { 'Content-Type': 'text/html' } }),
    new Response(null, { headers: { 'Content-Type': 'application/octet-stream' } }),
  ])('rejects an invalid original response', async (response) => {
    respond(response);
    await expect(getSourceOriginal('run-1', 'report-1', new AbortController().signal))
      .rejects.toBeInstanceOf(InvalidSourceResponseError);
  });

  it('rejects a partial original response even with valid binary content', async () => {
    respond(new Response(new Uint8Array([1, 2]), {
      status: 206,
      headers: { 'Content-Type': 'application/octet-stream', 'Content-Range': 'bytes 0-1/3' },
    }));
    await expect(getSourceOriginal('run-1', 'report-1', new AbortController().signal))
      .rejects.toBeInstanceOf(InvalidSourceResponseError);
  });

  it('rejects a partial evidence response even with valid JSON', async () => {
    respond(Response.json(evidence, { status: 206 }));
    await expect(getSourceEvidence('run-1', 'report-1', evidence.id, new AbortController().signal))
      .rejects.toBeInstanceOf(InvalidSourceResponseError);
  });

  it.each(['строка/1 + %2F?#', '..', 'section\\line'])(
    'preserves evidence ID %s in a query parameter', async (id) => {
      const saved = { ...evidence, id };
      const fetchMock = respond(Response.json(saved));
      const signal = new AbortController().signal;
      await expect(getSourceEvidence('run-1', 'report-1', id, signal)).resolves.toEqual(saved);
      const [path, options] = fetchMock.mock.calls[0];

      const url = new URL(String(path), 'http://localhost');
      expect(url.pathname).toBe(`${documentUrl}/fragments`);
      expect(Array.from(url.searchParams)).toEqual([['evidence_id', id]]);
      expect(url.hash).toBe('');
      expect(options?.signal).toBe(signal);
    },
  );

  it.each([
    { kind: 'page', page: 1, line: 2, table_row: null, table_column: null },
    { kind: 'sheet', sheet: 'Синтетика', range: 'C6:D8' },
    { kind: 'table_cell', table: 1, row: 2, cell: 3 },
    { kind: 'paragraph', paragraph: 4 },
  ])('preserves the original $kind locator and Decimal string', async (locator) => {
    const saved = { ...evidence, locator, normalized_value: '9007199254740993.00' };
    respond(Response.json(saved));
    await expect(getSourceEvidence('run-1', 'report-1', saved.id, new AbortController().signal))
      .resolves.toEqual(saved);
  });

  it('accepts a period evidence with a missing start date', async () => {
    const saved = { ...evidence, kind: 'period', normalized_value: { start: null, end: '2026-02-28' } };
    respond(Response.json(saved));
    await expect(getSourceEvidence('run-1', 'report-1', saved.id, new AbortController().signal))
      .resolves.toEqual(saved);
  });

  it.each([
    { ...evidence, id: 'other-evidence' },
    { ...evidence, document_id: 'other-document' },
    { ...evidence, normalized_value: 12345.67 },
    { ...evidence, locator: { kind: 'video', page: 1 } },
    { ...evidence, locator: { kind: 'page', page: 1, bbox: [0.8, 0, 0.2, 1] } },
    { ...evidence, locator: { kind: 'page', page: 1, table_row: 2 } },
    { ...evidence, locator: { kind: 'sheet', sheet: 'Синтетика', range: 'XFE1' } },
    { ...evidence, kind: 'period', normalized_value: { start: '2026-02-30', end: null } },
  ])('rejects a foreign or malformed evidence response', async (value) => {
    respond(Response.json(value));
    await expect(getSourceEvidence('run-1', 'report-1', evidence.id, new AbortController().signal))
      .rejects.toBeInstanceOf(InvalidSourceResponseError);
  });

  it('rejects malformed evidence JSON', async () => {
    respond(new Response('{', { headers: { 'Content-Type': 'application/json' } }));
    await expect(getSourceEvidence('run-1', 'report-1', evidence.id, new AbortController().signal))
      .rejects.toBeInstanceOf(InvalidSourceResponseError);
  });

  it.each([
    [404, 'document_not_found'],
    [404, 'fragment_not_found'],
    [409, 'result_pending'],
    [409, 'run_failed'],
    [503, 'service_unavailable'],
  ])('preserves HTTP %s and the %s contract code', async (status, code) => {
    respond(Response.json({ code, message: 'Synthetic error' }, { status }));
    await expect(getSourceEvidence('run-1', 'report-1', evidence.id, new AbortController().signal))
      .rejects.toMatchObject({ name: 'SourceHttpError', status, code });
  });

  it('preserves the HTTP status when an intermediary returns a non-JSON error', async () => {
    respond(new Response('Bad gateway', { status: 502 }));
    await expect(getSourceOriginal('run-1', 'report-1', new AbortController().signal))
      .rejects.toMatchObject(new SourceHttpError(502, null));
  });

  it('rejects untrusted run and document path segments before making a request', async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
    const signal = new AbortController().signal;

    await expect(getSourceOriginal('..', 'report-1', signal)).rejects.toBeInstanceOf(TypeError);
    await expect(getSourceEvidence('run-1', 'a/b', evidence.id, signal))
      .rejects.toBeInstanceOf(TypeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('propagates network failures', async () => {
    const error = new TypeError('Synthetic network error');
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockRejectedValue(error));
    await expect(getSourceOriginal('run-1', 'report-1', new AbortController().signal))
      .rejects.toBe(error);
  });

  it('propagates cancellation while evidence is loading', async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn<typeof fetch>((_, options) => new Promise((_, reject) => {
      options?.signal?.addEventListener('abort', () => reject(options.signal?.reason), { once: true });
    }));
    vi.stubGlobal('fetch', fetchMock);
    const pending = getSourceEvidence('run-1', 'report-1', evidence.id, controller.signal);
    controller.abort();

    await expect(pending).rejects.toBe(controller.signal.reason);
    expect(fetchMock).toHaveBeenCalledWith(expect.any(String), { signal: controller.signal });
  });

  it('rejects a binary body that finishes after cancellation', async () => {
    const controller = new AbortController();
    const reason = new DOMException('Synthetic request cancelled', 'AbortError');
    const response = new Response('Synthetic bytes', {
      headers: { 'Content-Type': 'application/octet-stream' },
    });
    const original = await response.blob();
    vi.spyOn(response, 'blob').mockImplementation(async () => {
      controller.abort(reason);
      return original;
    });
    respond(response);
    await expect(getSourceOriginal('run-1', 'report-1', controller.signal))
      .rejects.toBe(reason);
  });
});
