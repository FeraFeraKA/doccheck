import { useCallback, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { loadRunHistory, runStatusLabels } from './checkData';
import type { CheckHistory, HistoryEntry, RunStatus } from './checkData';
import { demoJob, demoRunPath, demoTitle } from './demoData';
import { OverviewIcon } from './OverviewIcon';
import { useCheckData } from './useCheckData';
import './checks-overview.css';

interface OverviewProps {
  loadHistory?: (signal: AbortSignal, cursor?: string) => Promise<CheckHistory>;
}

const dateFormat = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
const labels = { all: 'Все проверки', attention: 'Требуют внимания', completed: 'Завершённые' };
type Filter = keyof typeof labels;
type Sort = 'recent' | 'name';
const filters: Filter[] = ['all', 'attention', 'completed'];
const tones: Record<RunStatus, string> = {
  queued: 'neutral',
  processing: 'neutral',
  completed: 'mint',
  completed_with_issues: 'peach',
  failed: 'peach',
};

function isAttention(entry: HistoryEntry) {
  return entry.status === 'completed_with_issues' || entry.status === 'failed';
}

export function ChecksOverview({ loadHistory = loadRunHistory }: OverviewProps = {}) {
  return import.meta.env.VITE_DOCCHECK_PUBLIC_DEMO === '1'
    ? <OverviewLayout demo />
    : <RunHistory loadHistory={loadHistory} />;
}

function RunHistory({ loadHistory }: Required<OverviewProps>) {
  const [params] = useSearchParams();
  const cursor = params.get('cursor') ?? '';
  const load = useCallback(
    (key: string, signal: AbortSignal) => loadHistory(signal, key || undefined), [loadHistory],
  );
  const { state, retry } = useCheckData(cursor, load);
  return <OverviewLayout
    cursor={cursor}
    page={state.phase === 'ready' ? state.data : undefined}
    loading={state.phase === 'loading'}
    error={state.phase === 'failed'}
    retry={retry}
  />;
}

interface LayoutProps {
  demo?: boolean;
  cursor?: string;
  page?: CheckHistory;
  loading?: boolean;
  error?: boolean;
  retry?: () => void;
}

function OverviewLayout({ demo, cursor, page, loading, error, retry }: LayoutProps) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [sort, setSort] = useState<Sort>('recent');
  const entries = page?.entries ?? [];
  const counts = {
    all: entries.length,
    attention: entries.filter(isAttention).length,
    completed: entries.filter(({ status }) => status === 'completed').length,
  };
  const search = query.trim().toLocaleLowerCase('ru');
  const matches = entries.filter((entry) =>
    entry.title.toLocaleLowerCase('ru').includes(search)
    && (filter === 'all' || (filter === 'attention' ? isAttention(entry) : entry.status === 'completed')),
  );
  // The API already sorts the cursor page by creation time and ID.
  if (sort === 'name') matches.sort((a, b) => a.title.localeCompare(b.title, 'ru', { numeric: true }));
  const shown = matches;
  const changeSort = () => setSort((current) => current === 'recent' ? 'name' : 'recent');

  return (
    <div className="checks-overview">
      <div className="overview-heading">
        <div>
          <h1>Проверки</h1>
          <p>Сверяйте отчёты с первичными документами. Разбирайте только то, что требует внимания.</p>
        </div>
        <Link className="overview-primary inline-flex items-center gap-2" to="/checks/new">
          <OverviewIcon name="plus" size={17} />
          Новая проверка
        </Link>
      </div>
      <section className="overview-section" aria-label="История запусков" aria-busy={loading}>
        <div className="overview-section-heading">
          <h2>Ваши проверки {page && <span>{entries.length}</span>}</h2>
          {!demo && <div className="overview-legend">
            <span className="mint">Завершена</span>
            <span className="peach">Требует внимания</span>
            <span className="neutral">В работе</span>
          </div>}
        </div>
        {!demo && <div className="overview-toolbar">
          <div className="overview-filters flex flex-wrap gap-1.5" role="group" aria-label="Фильтры проверок">
            {filters.map((key) => (
              <button type="button" key={key} aria-pressed={filter === key} aria-label={labels[key]}
                onClick={() => setFilter(key)}>
                {labels[key]} {page && <span>{counts[key]}</span>}
              </button>
            ))}
          </div>
          <div className="overview-inputs flex items-center gap-2.5">
            <label className="overview-search">
              <OverviewIcon name="search" size={16} />
              <input type="search" aria-label="Поиск на странице" placeholder="Название проверки"
                value={query} onChange={(event) => setQuery(event.target.value)} />
            </label>
            <button type="button" className="overview-sort" onClick={changeSort}
              aria-label={sort === 'recent' ? 'Сортировать по названию' : 'Сортировать по дате'}>
              <OverviewIcon name="sliders" size={17} />
            </button>
          </div>
        </div>}
        {demo && <p className="overview-notice">История рабочих проверок доступна в локальной установке.</p>}
        {loading && <p className="overview-notice" role="status">Загрузка проверок…</p>}
        {error && <div className="overview-notice">
          <p role="alert">Не удалось загрузить проверки.</p>
          <button type="button" className="overview-secondary" onClick={retry}>Повторить</button>
        </div>}
        {page && <HistoryTable
          entries={shown}
          hasEntries={entries.length > 0}
          sort={sort}
          changeSort={changeSort}
          reset={() => { setQuery(''); setFilter('all'); }}
        />}
        {(cursor || page?.nextCursor) && <nav className="overview-footer flex flex-wrap gap-2" aria-label="Страницы проверок">
            {cursor && <Link className="overview-secondary" to="/checks">К новым проверкам</Link>}
            {page?.nextCursor && <Link className="overview-secondary" to={{
              pathname: '/checks', search: '?' + new URLSearchParams({ cursor: page.nextCursor }),
            }}>Более ранние проверки</Link>}
        </nav>}
      </section>
      <section className="overview-section overview-example" aria-label="Готовый пример">
        <div className="overview-section-heading"><h2>Готовый пример</h2></div>
        <div className="overview-table-wrap">
          <table className="overview-table">
            <thead><tr><th scope="col">Проверка</th><th scope="col">Документы</th>
              <th scope="col">Результат</th><th scope="col" aria-label="Открыть" /></tr></thead>
            <tbody><tr>
              <td><CheckTitle to={demoRunPath} title={demoTitle} tone="neutral" /></td>
              <td><span className="overview-document-count"><OverviewIcon name="files" size={15} />
                {demoJob.result.documents.length} файла</span></td>
              <td className="overview-result"><span className="overview-chip neutral">Синтетический пример</span></td>
              <td className="overview-open-cell"><OpenCheck to={demoRunPath} title={demoTitle} /></td>
            </tr></tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function CheckTitle({ to, title, tone }: { to: string; title: string; tone: string }) {
  return <div className="overview-check-title">
    <span className={classes('overview-file-symbol grid place-items-center', tone)}><OverviewIcon name="file" size={21} /></span>
    <Link to={to}>{title}<OverviewIcon name="arrowUpRight" size={13} /></Link>
  </div>;
}

function OpenCheck({ to, title }: { to: string; title: string }) {
  return <Link to={to} className="overview-open grid place-items-center" aria-label={`Открыть ${title}`}>
    <OverviewIcon name="chevron" />
  </Link>;
}

function HistoryTable({ entries, hasEntries, sort, changeSort, reset }: {
  entries: HistoryEntry[];
  hasEntries: boolean;
  sort: Sort;
  changeSort: () => void;
  reset: () => void;
}) {
  return (
    <div className="overview-table-wrap">
      <table className="overview-table">
        <thead><tr>
          <th scope="col">Проверка</th><th scope="col">Документы</th><th scope="col">Покрытие по сумме</th>
          <th scope="col">Состояние</th>
          <th scope="col" aria-sort={sort === 'recent' ? 'descending' : 'none'}>
            <button type="button" className="inline-flex items-center gap-1.5" onClick={changeSort}>
              Дата <OverviewIcon name="arrowDown" size={12} />
            </button>
          </th>
          <th scope="col" aria-label="Открыть" />
        </tr></thead>
        <tbody>{entries.map((entry) => {
          const to = '/checks/' + encodeURIComponent(entry.id);
          const tone = tones[entry.status];
          return <tr key={entry.id}>
            <td><CheckTitle to={to} title={entry.title} tone={tone} /></td>
            <td className="overview-unavailable" aria-label="Документы: нет данных">—</td>
            <td className="overview-unavailable" aria-label="Покрытие: нет данных">—</td>
            <td className="overview-result"><span className={classes('overview-chip', tone)}>{runStatusLabels[entry.status]}</span></td>
            <td className="overview-date"><time dateTime={entry.createdAt}>{dateFormat.format(new Date(entry.createdAt))}</time></td>
            <td className="overview-open-cell"><OpenCheck to={to} title={entry.title} /></td>
          </tr>;
        })}</tbody>
      </table>
      {entries.length === 0 && <div className="overview-empty">
        <OverviewIcon name="file" size={32} />
        <h3>{hasEntries ? 'Проверки не найдены.' : 'Проверок пока нет.'}</h3>
        {hasEntries && <p>Попробуйте другой запрос или сбросьте фильтры.</p>}
        {hasEntries
          ? <button type="button" className="overview-secondary" onClick={reset}>Сбросить фильтры</button>
          : <Link className="overview-primary" to="/checks/new">Новая проверка</Link>}
      </div>}
    </div>
  );
}
