import { useEffect, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';

import { Sources } from './Sources';
import './preview.css';

const api = '/api/preview/v1';
const runStatuses: Record<string, string> = {
  queued: 'В очереди',
  processing: 'Обработка',
  completed: 'Готово',
  completed_with_issues: 'Готово с замечаниями',
  failed: 'Ошибка',
};

type Run = { run_id: string; status: string };

function isRun(value: unknown): value is Run {
  return typeof value === 'object' && value !== null
    && 'run_id' in value && typeof value.run_id === 'string'
    && 'status' in value && typeof value.status === 'string'
    && Object.hasOwn(runStatuses, value.status);
}

function Preview() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [sessionRequired, setSessionRequired] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [openRun, setOpenRun] = useState<string | null>(null);

  async function reload(signal?: AbortSignal) {
    try {
      const response = await fetch(api + '/runs', { signal, cache: 'no-store', redirect: 'error' });
      if (response.status === 401) {
        setSessionRequired(true);
        setRuns(null);
        return;
      }
      if (!response.ok) throw new Error();
      const payload: unknown = await response.json();
      if (!Array.isArray(payload) || !payload.every(isRun)) throw new Error();
      setSessionRequired(false);
      setRuns(payload);
    } catch {
      if (!signal?.aborted) setError('Не удалось получить список проверок.');
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(() => {
      if (!controller.signal.aborted) void reload(controller.signal);
    });
    return () => controller.abort();
  }, []);

  async function enter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const token = new FormData(form).get('token');
    form.reset();
    setBusy(true);
    setError('');
    try {
      const response = await fetch(api + '/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
        cache: 'no-store',
        redirect: 'error',
      });
      if (!response.ok) {
        setError(response.status === 401 ? 'Приглашение недействительно.' : 'Не удалось войти.');
        return;
      }
      await reload();
    } catch {
      setError('Не удалось войти.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>DocCheck</h1>
      <p>Закрытое демо на синтетических документах</p>
      {sessionRequired && (
        <form onSubmit={(event) => void enter(event)}>
          <label htmlFor="preview-token">Код приглашения</label>
          <input id="preview-token" name="token" type="password" required minLength={32} maxLength={256} />
          <button type="submit" disabled={busy}>Войти</button>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
      {!sessionRequired && (
        <>
          <button type="button" onClick={() => { setError(''); void reload(); }}>Обновить</button>
          {runs?.length === 0 && <p>Нет допущенных проверок.</p>}
          {runs?.length ? (
            <ul aria-label="Доступные проверки">
              {runs.map(({ run_id: id, status }) => {
                const resultPath = api + '/runs/' + encodeURIComponent(id);
                const ready = status === 'completed' || status === 'completed_with_issues';
                return (
                  <li key={id}>
                    <code>{id}</code><br />
                    <span>{runStatuses[status]}</span>
                    {ready && (
                      <div>
                        <a href={resultPath + '/findings'}>Результат JSON</a>
                        {' · '}
                        <a href={resultPath + '/exports/xlsx'}>Выгрузка XLSX</a>
                        {' · '}
                        <button type="button" aria-expanded={openRun === id} onClick={() => {
                          setOpenRun(openRun === id ? null : id);
                        }}>Источники</button>
                        {openRun === id && <Sources key={id} runPath={resultPath} />}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </>
      )}
    </main>
  );
}

const root = document.getElementById('root');
if (root) createRoot(root).render(<Preview />);
