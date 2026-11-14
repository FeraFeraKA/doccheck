import { useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { loadFollowedRun, runStatusLabels } from './checkData';
import type { HistoryEntry, RunStatus } from './checkData';
import { WorkspaceIcon } from './WorkspaceIcon';
import { runTitle } from './runTitle';
import { RunProgressBar } from './RunProgressBar';
import { useCheckData } from './useCheckData';
import { isRunId } from './runStatusApi';
import './run-queue.css';

export interface QueueReceipt {
  id: string;
  documentCount: number;
  reportName?: string;
}

interface RunQueueProps {
  entries?: HistoryEntry[];
  receipts: QueueReceipt[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}

type QueueTone = 'mint' | 'peach' | 'neutral';
const tones: Record<RunStatus, QueueTone> = {
  queued: 'neutral',
  processing: 'neutral',
  completed: 'mint',
  completed_with_issues: 'peach',
  failed: 'peach',
};
const dateFormat = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' });

export function RunQueue({ entries = [], receipts, loading, error, onRetry }: RunQueueProps) {
  const location = useLocation();
  const queue = useRef<HTMLElement>(null);
  const selectedId = new URLSearchParams(location.search).get('run');
  const followedId = isRunId(selectedId) ? selectedId : undefined;

  useEffect(() => {
    if (location.hash !== '#queue') return;
    queue.current?.scrollIntoView?.();
  }, [location.hash, location.key]);

  const listedIds = new Set(entries.map(({ id }) => id));
  const pendingReceipts = receipts.filter(({ id }) => !listedIds.has(id));
  const items: RunQueueItemProps[] = [
    ...pendingReceipts.filter(({ id }) => id !== followedId).map((receipt): RunQueueItemProps => ({
      ...receipt,
      title: runTitle(undefined, receipt.reportName),
      label: 'В очереди',
      tone: 'neutral',
      progress: null,
    })),
    ...entries.filter(({ id }) => id !== followedId).map(toQueueItem),
  ];
  return (
    <section ref={queue} id="queue" className="upload-card queue-card" aria-label="Последние проверки" aria-busy={loading}>
      <header className="upload-card-header">
        <h2>Очередь проверок</h2>
      </header>
      {error && <p className="upload-validation" role="alert">Не удалось обновить историю.
        {' '}<button type="button" onClick={onRetry} className="underline">Повторить</button>
      </p>}
      {loading && <p className="queue-message">Загрузка истории…</p>}
      {(items.length > 0 || followedId) && <ul className="queue-list">
        {followedId && <FollowedRun key={followedId} id={followedId}
          listed={entries.find(({ id }) => id === followedId)} />}
        {items.map((item) => <RunQueueItem key={item.id} {...item} />)}
      </ul>}
      {!loading && !error && !followedId && items.length === 0 &&
        <p className="queue-message">В очереди пока нет проверок.</p>}
    </section>
  );
}

function FollowedRun({ id, listed }: { id: string; listed?: HistoryEntry }) {
  const { state, retry } = useCheckData(id, loadFollowedRun);
  if (state.phase === 'loading') {
    return listed ? <RunQueueItem {...toQueueItem(listed)} />
      : <li className="queue-message" role="status">Загрузка состояния проверки…</li>;
  }
  if (state.phase === 'failed') {
    return <li className="queue-message" role="alert">Не удалось обновить состояние проверки.
      {' '}<button type="button" onClick={retry} className="underline">Повторить</button>
    </li>;
  }
  if (!state.data) return <li className="queue-message">Проверка не найдена.</li>;
  const entry = {
    ...listed, ...state.data,
    title: runTitle(state.data.reportNumber ?? listed?.reportNumber, state.data.reportName ?? listed?.reportName),
    documentCount: state.data.documentCount ?? listed?.documentCount,
    synthetic: state.data.synthetic ?? listed?.synthetic,
  };
  return <RunQueueItem {...toQueueItem(entry)} />;
}

function toQueueItem(entry: HistoryEntry): RunQueueItemProps {
  const { id, title, createdAt, status, synthetic, documentCount, error, progress } = entry;
  const percent = status === 'processing' && progress && progress.total > 0
    ? Math.floor(progress.processed * 100 / progress.total)
    : queueProgress(status);
  return {
    id, title, label: runStatusLabels[status], tone: tones[status], createdAt, synthetic,
    documentCount, error, progress: percent,
    openResult: status === 'completed' || status === 'completed_with_issues',
  };
}

function queueProgress(status: RunStatus) {
  if (status === 'queued' || status === 'processing') return null;
  if (status === 'completed' || status === 'completed_with_issues') return 100;
  return undefined;
}

interface RunQueueItemProps {
  id: string;
  title: string;
  label: string;
  tone: QueueTone;
  createdAt?: string;
  synthetic?: boolean;
  error?: string;
  documentCount?: number;
  progress?: number | null;
  openResult?: boolean;
}

function RunQueueItem({
  id, title, label, tone, createdAt, synthetic, error, documentCount, progress, openResult,
}: RunQueueItemProps) {
  const content = <>
    <div className="queue-job-heading">
      <div className="queue-job-title">
        <span className="queue-file-symbol"><WorkspaceIcon name="fileSearch" size={21} /></span>
        <div className="min-w-0">
          <h3>{title}</h3>
          {(createdAt || synthetic || documentCount !== undefined) && <div className="queue-job-meta">
            {documentCount !== undefined && <span>Файлов: {documentCount}</span>}
            {createdAt && <time dateTime={createdAt}>{dateFormat.format(new Date(createdAt))}</time>}
            {synthetic && <span>Тестовые данные</span>}
          </div>}
        </div>
      </div>
      <div className="queue-job-state">
        <span className={classes('queue-status-chip', tone)}>{label}</span>
        {typeof progress === 'number' && <span className="tabular-nums">{progress}%</span>}
      </div>
    </div>
    {progress !== undefined && <RunProgressBar
      label={title} value={progress} valueText={label} complete={progress === 100} />}
    {error && <p className="upload-validation">{error}</p>}
  </>;
  return <li>{openResult
    ? <Link className="queue-job" aria-label={title} to={'/checks/' + encodeURIComponent(id)}>{content}</Link>
    : <div className="queue-job">{content}</div>}
  </li>;
}
