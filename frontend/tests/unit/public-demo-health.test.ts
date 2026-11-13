import { afterEach, expect, it, vi } from 'vitest';
import { checkHealth } from '../../src/pages/home/scaffoldApi';

function mockHealth() {
  vi.stubEnv('VITE_DOCCHECK_PUBLIC_DEMO', '1');
  vi.useFakeTimers();
  const fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it('повторяет только проверку доступности при странице запуска и 503', async () => {
  const fetchMock = mockHealth()
    .mockResolvedValueOnce(new Response('<html>Starting</html>'))
    .mockResolvedValueOnce(new Response(null, { status: 503 }))
    .mockResolvedValueOnce(Response.json({ status: 'ok', database: 'ok' }));
  const health = checkHealth(new AbortController().signal);

  await vi.advanceTimersByTimeAsync(20_000);
  await expect(health).resolves.toBeUndefined();
  expect(fetchMock.mock.calls.map(([path, options]) => [path, options?.method])).toEqual([
    ['/health', undefined], ['/health', undefined], ['/health', undefined],
  ]);
});

it('останавливается после восьмой быстрой ошибки', async () => {
  const fetchMock = mockHealth().mockImplementation(async () => new Response(null, { status: 503 }));
  const health = checkHealth(new AbortController().signal);
  const result = expect(health).rejects.toMatchObject({ status: 503 });

  await vi.advanceTimersByTimeAsync(70_000);
  await result;
  expect(fetchMock).toHaveBeenCalledTimes(8);
});

it('снимает ожидание следующей попытки при уходе со страницы', async () => {
  const fetchMock = mockHealth().mockResolvedValue(new Response(null, { status: 503 }));
  const controller = new AbortController();
  const health = checkHealth(controller.signal);
  await vi.advanceTimersByTimeAsync(0);
  controller.abort();

  await expect(health).rejects.toMatchObject({ name: 'AbortError' });
  await vi.advanceTimersByTimeAsync(10_000);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
