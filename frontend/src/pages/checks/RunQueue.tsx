import { useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { runStatusLabels } from './checkData';
import type { HistoryEntry, RunStatus } from './checkData';
import { WorkspaceIcon } from './WorkspaceIcon';
import { runTitle } from './runTitle';
import { RunProgressBar } from './RunProgressBar';
import './run-queue.css';

export interface QueueReceipt {
  id: string;
  documentCount: number;
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

  useEffect(() => {
    if (location.hash !== '#queue') return;
    queue.current?.scrollIntoView?.();
  }, [location.hash, location.key]);

  const listedIds = new Set(entries.map(({ id }) => id));
  const pendingReceipts = receipts.filter(({ id }) => !listedIds.has(id));
  const items: RunQueueItemProps[] = [
    ...pendingReceipts.map((receipt): RunQueueItemProps => ({
      ...receipt,
      title: runTitle(receipt.id),
      label: 'В очереди',
      tone: 'neutral',
      progress: null,
    })),
    ...entries.map(({ id, title, createdAt, status, synthetic, documentCount, error }) => ({
      id, title, label: runStatusLabels[status], tone: tones[status], createdAt, synthetic, documentCount, error,
      progress: queueProgress(status),
      openResult: status === 'completed' || status === 'completed_with_issues',
    })),
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
      {items.length > 0 && <ul className="queue-list">
        {items.map((item) => <RunQueueItem key={item.id} {...item} />)}
      </ul>}
      {!loading && !error && items.length === 0 && <p className="queue-message">В очереди пока нет проверок.</p>}
    </section>
  );
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
            {synthetic && <span>Синтетика</span>}
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
