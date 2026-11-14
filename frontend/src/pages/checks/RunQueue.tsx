import { Link } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { runStatusLabels } from './checkData';
import type { HistoryEntry, RunStatus } from './checkData';
import { WorkspaceIcon } from './WorkspaceIcon';
import { runTitle } from './runTitle';
import { demoTitle, demoUploadFiles } from './demoData';
import './run-queue.css';

export interface QueueReceipt {
  id: string;
  documentCount: number;
  synthetic?: boolean;
  createdAt?: string;
}

export interface DemoTransfer {
  id: string;
  createdAt: string;
  percent?: number;
  error?: string;
}

interface RunQueueProps {
  entries?: HistoryEntry[];
  receipts: QueueReceipt[];
  demoTransfer?: DemoTransfer;
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

export function RunQueue({ entries = [], receipts, demoTransfer, loading, error, onRetry }: RunQueueProps) {
  const listedIds = new Set(entries.map(({ id }) => id));
  const pendingReceipts = receipts.filter(({ id }) => !listedIds.has(id));
  const items: RunQueueItemProps[] = [
    ...pendingReceipts.map((receipt): RunQueueItemProps => ({
      ...receipt,
      title: receipt.synthetic ? demoTitle : runTitle(receipt.id),
      label: 'Сервер получил пакет',
      tone: 'neutral',
      progress: receipt.synthetic ? null : undefined,
    })),
    ...entries.map(({ id, title, createdAt, status, synthetic, documentCount, error }) => ({
      id, title, label: runStatusLabels[status], tone: tones[status], createdAt, synthetic, documentCount, error,
      progress: synthetic && status !== 'failed'
        ? status === 'completed' || status === 'completed_with_issues' ? 100 : status === 'queued' ? 0 : null
        : undefined,
    })),
  ];
  if (demoTransfer) {
    items.unshift({
      ...demoTransfer,
      title: demoTitle,
      label: demoTransfer.error ? 'Ошибка загрузки' : 'Загрузка файлов',
      tone: demoTransfer.error ? 'peach' : 'neutral',
      synthetic: true,
      documentCount: demoUploadFiles.length,
      progress: demoTransfer.error ? undefined : demoTransfer.percent ?? null,
      pendingUpload: true,
    });
  }
  return (
    <section className="upload-card queue-card" aria-label="Последние проверки" aria-busy={loading}>
      <header className="upload-card-header">
        <div>
          <h2>Очередь проверок</h2>
          <p>Загрузите пример, чтобы запустить проверку синтетического комплекта.</p>
        </div>
        <Link to="/checks" className="queue-history-link">Все проверки</Link>
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
  pendingUpload?: boolean;
}

function RunQueueItem({
  id, title, label, tone, createdAt, synthetic, error, documentCount, progress, pendingUpload,
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
    {progress !== undefined && <div className="queue-progress" role="progressbar"
      aria-label={title} aria-valuenow={progress ?? undefined} aria-valuetext={label}
      data-indeterminate={progress === null} data-complete={progress === 100 && !pendingUpload}>
      <span style={progress === null ? undefined : { width: `${progress}%` }} />
    </div>}
    {error && <p className="upload-validation" role={pendingUpload ? 'alert' : undefined}>{error}</p>}
  </>;
  return <li>{pendingUpload
    ? <div className="queue-job">{content}</div>
    : <Link className="queue-job" aria-label={title} to={'/checks/' + encodeURIComponent(id)}>{content}</Link>}
  </li>;
}
