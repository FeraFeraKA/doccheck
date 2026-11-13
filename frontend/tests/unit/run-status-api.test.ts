import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  getRun, InvalidRunResponseError, listRuns, pollRun,
} from '../../src/pages/checks/runStatusApi';

const runId = 'test_run-1';
const summary = {
  run_id: runId,
  status: 'queued',
  created_at: '2026-11-13T12:00:00Z',
  error: null,
};
const queued = { ...summary, progress: { processed_documents: 0, total_documents: 2 } };
const processing = { ...summary, status: 'processing', progress: null };
const completed = {
  ...summary, status: 'completed', progress: { processed_documents: 2, total_documents: 2 },
};
const failed = {
  ...summary, status: 'failed', error: { code: 'test_failure', message: 'Тестовая ошибка' }, progress: null,
};

function mockFetch() {
  const fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('API истории и состояния запусков', () => {
  it('читает историю в порядке сервера и передаёт курсор следующей страницы', async () => {
    const fetchMock = mockFetch();
    const signal = new AbortController().signal;
    const cursor = 'next+page/=&';
    const earlier = { ...summary, run_id: 'previous', status: 'completed' };
    fetchMock.mockResolvedValueOnce(Response.json({ items: [summary, earlier], next_cursor: cursor }));
    fetchMock.mockResolvedValueOnce(Response.json({ items: [], next_cursor: null }));

    const history = await listRuns(signal);
    expect(history).toEqual({ items: [summary, earlier], next_cursor: cursor });
    expect(await listRuns(signal, { limit: 20, cursor: history.next_cursor ?? undefined }))
      .toEqual({ items: [], next_cursor: null });
    const requestOptions = { cache: 'no-store', signal: expect.any(AbortSignal) };
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/v0/runs', requestOptions);
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/v0/runs?limit=20&cursor=next%2Bpage%2F%3D%26',
      requestOptions);
  });

  it('сохраняет техническую ошибку задания с неизвестным прогрессом', async () => {
    const fetchMock = mockFetch().mockResolvedValue(Response.json(failed));
    await expect(getRun(runId, new AbortController().signal)).resolves.toEqual(failed);
    expect(fetchMock).toHaveBeenCalledWith(`/api/v0/runs/${runId}`, {
      cache: 'no-store', signal: expect.any(AbortSignal),
    });
  });

  it.each([
    { ...queued, run_id: 'another_run' },
    { ...queued, status: 'verified' },
    { ...queued, created_at: '2026-11-13' },
    { ...queued, progress: null },
    { ...queued, progress: { processed_documents: 1, total_documents: 2 } },
    { ...processing, progress: { processed_documents: 3, total_documents: 2 } },
    { ...completed, progress: { processed_documents: 1, total_documents: 2 } },
    { ...failed, error: { code: 'test_failure' } },
  ])('отклоняет некорректное состояние задания %#', async (body) => {
    mockFetch().mockResolvedValue(Response.json(body));
    await expect(getRun(runId, new AbortController().signal)).rejects.toBeInstanceOf(InvalidRunResponseError);
  });

  it('отклоняет страницу истории с некорректным состоянием показателя', async () => {
    mockFetch().mockResolvedValue(Response.json({ items: [{ ...summary, status: 'unverified' }], next_cursor: null }));
    await expect(listRuns(new AbortController().signal)).rejects.toBeInstanceOf(InvalidRunResponseError);
  });

  it('отклоняет ID, который не является допустимым сегментом маршрута', async () => {
    const fetchMock = mockFetch();
    await expect(getRun('..', new AbortController().signal)).rejects.toBeInstanceOf(TypeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('передаёт некорректный JSON как ошибку ответа', async () => {
    mockFetch().mockResolvedValue(new Response('invalid JSON'));
    await expect(listRuns(new AbortController().signal)).rejects.toBeInstanceOf(SyntaxError);
  });

  it.each([
    { name: 'состояние', load: (signal: AbortSignal) => getRun(runId, signal), body: queued },
    { name: 'история', load: listRuns, body: { items: [summary], next_cursor: null } },
  ])('$name отклоняет ответ при отмене между чтением JSON и возвратом результата', async ({ load, body }) => {
    const controller = new AbortController();
    const reason = new DOMException('Тестовая отмена', 'AbortError');
    const response = new Response();
    vi.spyOn(response, 'json').mockImplementation(() => {
      // Два await передают JSON через requestJson и getRunJson, затем продолжает load.
      const parsed = Promise.resolve(body);
      void parsed.then(() => {}).then(() => {}).then(() => controller.abort(reason));
      return parsed;
    });
    mockFetch().mockResolvedValue(response);

    await expect(load(controller.signal)).rejects.toBe(reason);
  });
});

describe('опрос состояния задания', () => {
  it.each([completed, { ...completed, status: 'completed_with_issues' }, failed])(
    'заканчивается на $status и сохраняет ноль отдельно от null',
    async (terminal) => {
      vi.useFakeTimers();
      const fetchMock = mockFetch();
      fetchMock.mockResolvedValueOnce(Response.json(queued));
      fetchMock.mockResolvedValueOnce(Response.json(processing));
      fetchMock.mockResolvedValueOnce(Response.json(terminal));
      const onState = vi.fn();
      const result = pollRun(runId, new AbortController().signal, onState);

      await vi.advanceTimersByTimeAsync(2_000);
      await expect(result).resolves.toEqual(terminal);
      expect(onState.mock.calls).toEqual([[queued], [processing], [terminal]]);
      expect(fetchMock).toHaveBeenCalledTimes(3);
    },
  );

  it.each([404, 503])('заканчивается с HTTP %i без повторного запроса', async (status) => {
    vi.useFakeTimers();
    const fetchMock = mockFetch().mockResolvedValue(new Response(null, { status }));
    const onState = vi.fn();
    await expect(pollRun(runId, new AbortController().signal, onState)).rejects.toMatchObject({ status });
    await vi.advanceTimersByTimeAsync(2_000);
    expect(onState).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('передаёт сетевую ошибку и не ставит следующий запрос в очередь', async () => {
    vi.useFakeTimers();
    const error = new TypeError('network unavailable');
    const fetchMock = mockFetch().mockRejectedValue(error);
    await expect(pollRun(runId, new AbortController().signal, vi.fn())).rejects.toBe(error);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('отмена между запросами снимает ожидание и прекращает опрос', async () => {
    vi.useFakeTimers();
    const fetchMock = mockFetch().mockResolvedValue(Response.json(queued));
    const controller = new AbortController();
    const onState = vi.fn();
    const result = pollRun(runId, controller.signal, onState);

    await vi.advanceTimersByTimeAsync(0);
    expect(onState).toHaveBeenCalledOnce();
    controller.abort();
    await expect(result).rejects.toBe(controller.signal.reason);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('передаёт отмену активному GET-запросу и не публикует поздний ответ', async () => {
    const controller = new AbortController();
    const onState = vi.fn();
    let transportSignal: AbortSignal | null | undefined;
    const fetchMock = mockFetch().mockImplementation(async (_path, init) => {
      transportSignal = init?.signal;
      controller.abort();
      return Response.json(completed);
    });

    await expect(pollRun(runId, controller.signal, onState)).rejects.toBe(controller.signal.reason);
    expect(transportSignal?.aborted).toBe(true);
    expect(onState).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
