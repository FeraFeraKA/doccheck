import { afterEach, describe, expect, it, vi } from 'vitest';
import { HttpError, requestJson } from '../../src/shared/api/requestJson';

afterEach(() => vi.unstubAllGlobals());

describe('requestJson', () => {
  it('передаёт параметры запроса и возвращает JSON-ответ', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"status":"queued"}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const init: RequestInit = { method: 'POST', body: 'example' };

    await expect(requestJson('/runs', init)).resolves.toEqual({ status: 'queued' });
    expect(fetchMock).toHaveBeenCalledWith('/runs', init);
  });

  it('передаёт ошибку HTTP вместо чтения её как успешного ответа', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
    await expect(requestJson('/runs')).rejects.toBeInstanceOf(HttpError);
    await expect(requestJson('/runs')).rejects.toMatchObject({ status: 503 });
  });

  it('не скрывает сетевую ошибку', async () => {
    const error = new TypeError('network unavailable');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(error));
    await expect(requestJson('/runs')).rejects.toBe(error);
  });
});
