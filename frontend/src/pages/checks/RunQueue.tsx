import { Link } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { runStatusLabels } from './checkData';
import type { HistoryEntry, RunStatus } from './checkData';
import { OverviewIcon } from './OverviewIcon';
import { runTitle } from './runTitle';
import './run-queue.css';

interface RunQueueProps {
  entries?: HistoryEntry[];
  receipts: string[];
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
  const listedIds = new Set(entries.map(({ id }) => id));
  const pendingReceipts = receipts.filter((id) => !listedIds.has(id));
  const hasEntries = pendingReceipts.length > 0 || entries.length > 0;
  return (
    <section className="upload-card queue-card" aria-label="Последние проверки" aria-busy={loading}>
      <header className="upload-card-header">
        <h2>Очередь проверок</h2>
        <Link to="/checks" className="queue-history-link">Все проверки</Link>
      </header>
      {error && <p className="upload-validation" role="alert">Не удалось обновить историю.
        {' '}<button type="button" onClick={onRetry} className="underline">Повторить</button>
      </p>}
      {loading && <p className="queue-message">Загрузка истории…</p>}
      {hasEntries && <ul className="queue-list">
        {pendingReceipts.map((id) => (
          <RunQueueItem key={id} id={id} title={runTitle(id)} label="Сервер получил пакет" tone="neutral" />
        ))}
        {entries.map(({ id, title, createdAt, status, synthetic, error: runError }) => (
          <RunQueueItem key={id} id={id} title={title} label={runStatusLabels[status]}
            tone={tones[status]}
            createdAt={createdAt} synthetic={synthetic} error={runError} />
        ))}
      </ul>}
      {!loading && !error && !hasEntries && <p className="queue-message">Проверок пока нет.</p>}
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
}

function RunQueueItem({ id, title, label, tone, createdAt, synthetic, error }: RunQueueItemProps) {
  return <li>
    <Link className="queue-job" aria-label={title} to={'/checks/' + encodeURIComponent(id)}>
      <div className="queue-job-heading">
        <div className="queue-job-title">
          <span className="queue-file-symbol"><OverviewIcon name="file" size={21} /></span>
          <div className="min-w-0">
            <h3>{title}</h3>
            {(createdAt || synthetic) && <div className="queue-job-meta">
              {createdAt && <time dateTime={createdAt}>{dateFormat.format(new Date(createdAt))}</time>}
              {synthetic && <span>Синтетика</span>}
            </div>}
          </div>
        </div>
        <div className="queue-job-state">
          <span className={classes('queue-status-chip', tone)}>{label}</span>
        </div>
      </div>
      {error && <p className="upload-validation">{error}</p>}
    </Link>
  </li>;
}
