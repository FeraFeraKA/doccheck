import { Link } from 'react-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  checkHealth, connectionError, createSyntheticJob, getSyntheticJob, isApiUnavailable,
  type JobStatus, type SyntheticJob,
} from './scaffoldApi';

const statusLabels: Record<JobStatus, string> = {
  queued: 'В очереди',
  processing: 'Обрабатывается',
  completed: 'Завершено',
  failed: 'Ошибка обработки',
};

const buttonClass = 'rounded border px-4 py-2 disabled:cursor-not-allowed disabled:opacity-50';
const checkingHealth = import.meta.env.VITE_DOCCHECK_PUBLIC_DEMO === '1'
  ? 'Проверяем связь с API. После простоя запуск сервера может занять около минуты.'
  : 'Проверяем связь с API…';

export function HomePage() {
  const [health, setHealth] = useState<'loading' | 'ready' | 'error'>('loading');
  const [healthError, setHealthError] = useState<string | null>(null);
  const [healthAttempt, setHealthAttempt] = useState(0);
  const [job, setJob] = useState<SyntheticJob | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [pollAttempt, setPollAttempt] = useState(0);
  const healthController = useRef<AbortController | null>(null);
  const creationController = useRef<AbortController | null>(null);
  const activeJobId = job?.status === 'queued' || job?.status === 'processing' ? job.id : null;

  const markApiUnavailable = useCallback((error: unknown) => {
    if (isApiUnavailable(error)) {
      // A health response started before the failed request is now stale.
      healthController.current?.abort();
      setHealth('error');
      setHealthError(connectionError(error));
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    healthController.current = controller;
    checkHealth(controller.signal).then(() => {
      if (!controller.signal.aborted) setHealth('ready');
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setHealth('error');
        setHealthError(connectionError(error));
      }
    });
    return () => {
      controller.abort();
      if (healthController.current === controller) healthController.current = null;
    };
  }, [healthAttempt]);

  useEffect(() => () => creationController.current?.abort(), []);

  useEffect(() => {
    if (!activeJobId || health !== 'ready') return;
    const id = activeJobId;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await getSyntheticJob(id, controller.signal);
        if (controller.signal.aborted) return;
        setJob(next);
        setJobError(null);
        if (next.status === 'queued' || next.status === 'processing') {
          timer = setTimeout(poll, 500);
        }
      } catch (error: unknown) {
        if (!controller.signal.aborted) {
          setJobError(connectionError(error));
          markApiUnavailable(error);
        }
      }
    }
    timer = setTimeout(poll, 500);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [activeJobId, health, markApiUnavailable, pollAttempt]);

  async function createJob() {
    if (health !== 'ready' || creating || activeJobId) return;
    const controller = new AbortController();
    creationController.current = controller;
    setCreating(true);
    setJob(null);
    setJobError(null);
    try {
      const created = await createSyntheticJob(controller.signal);
      if (!controller.signal.aborted) setJob(created);
    } catch (error: unknown) {
      if (!controller.signal.aborted) {
        if (isApiUnavailable(error)) {
          setJobError('Не удалось подтвердить создание задания.');
          markApiUnavailable(error);
        } else {
          setJobError(`Не удалось подтвердить создание задания. ${connectionError(error)}`);
        }
      }
    } finally {
      if (!controller.signal.aborted) setCreating(false);
      if (creationController.current === controller) creationController.current = null;
    }
  }

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-semibold">Проверка системы</h1>
      <p className="mt-4">Синтетический режим: проверка работы приложения без документов.</p>
      <p className="mt-2">OCR и настоящая финансовая сверка здесь не выполняются.</p>

      <Link className="mt-4 inline-block underline" to="/checks">Открыть интерфейс сверки</Link>

      <section className="mt-8" aria-labelledby="api-heading">
        <h2 id="api-heading" className="text-xl font-medium">Состояние API</h2>
        <p role="status" className="mt-2">
          {health === 'loading' && checkingHealth}
          {health === 'ready' && 'API и PostgreSQL доступны.'}
          {health === 'error' && 'API недоступен.'}
        </p>
        {healthError && <p role="alert" className="mt-2">{healthError}</p>}
        <button className={`${buttonClass} mt-3`} disabled={health === 'loading'}
          onClick={() => {
            setHealth('loading');
            setHealthError(null);
            setHealthAttempt((attempt) => attempt + 1);
          }}>
          Проверить связь
        </button>
      </section>

      <section className="mt-8" aria-labelledby="job-heading">
        <h2 id="job-heading" className="text-xl font-medium">Синтетическое задание</h2>
        <button className={`${buttonClass} mt-3`}
          disabled={health !== 'ready' || creating || activeJobId !== null}
          onClick={() => void createJob()}>
          {creating ? 'Создаём задание…' : 'Создать синтетическое задание'}
        </button>
        {job && (
          <div className="mt-4">
            <p className="break-all">Задание: {job.id}</p>
            <p role="status" className="mt-2">Статус: {statusLabels[job.status]}</p>
            {job.status === 'completed' && job.result && (
              <p className="mt-2">Тестовый результат: {job.result.message}</p>
            )}
            {job.status === 'failed' && <p role="alert" className="mt-2">Синтетическое задание завершилось с ошибкой.</p>}
          </div>
        )}
        {jobError && (
          <div className="mt-3">
            {(!healthError || !activeJobId) && <p role="alert">{jobError}</p>}
            {activeJobId && <>
              <p className="mt-2">Показан последний известный статус. Обновление приостановлено.</p>
              {health === 'ready' && <button className={`${buttonClass} mt-2`} onClick={() => {
                setJobError(null);
                setPollAttempt((attempt) => attempt + 1);
              }}>Обновить статус задания</button>}
            </>}
          </div>
        )}
      </section>
    </main>
  );
}
