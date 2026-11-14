import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { loadRunHistory, runStatusLabels } from './checkData';
import type { CheckHistory, FindingFilter, HistoryEntry, RunStatus } from './checkData';
import { demoJob, demoRunPath, demoTitle } from './demoData';
import { OverviewIcon } from './OverviewIcon';
import { useRunHistory } from './useRunHistory';
import './checks-overview.css';

interface OverviewProps {
  loadHistory?: typeof loadRunHistory;
}

const dateFormat = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
const filters = [
  ['all', 'Все'],
  ['discrepancy', 'Есть расхождения'],
  ['unverified', 'Неполные данные'],
  ['verified', 'Без расхождений'],
] as const;
type Sort = 'recent' | 'name';

function readFinding(value: string | null): FindingFilter | undefined {
  if (value === 'discrepancy' || value === 'unverified' || value === 'verified') return value;
}

const tones: Record<RunStatus, string> = {
  queued: 'neutral',
  processing: 'neutral',
  completed: 'mint',
  completed_with_issues: 'peach',
  failed: 'peach',
};

export function ChecksOverview({ loadHistory = loadRunHistory }: OverviewProps = {}) {
  return import.meta.env.VITE_DOCCHECK_PUBLIC_DEMO === '1'
    ? <OverviewLayout demo />
    : <RunHistory loadHistory={loadHistory} />;
}

function RunHistory({ loadHistory }: Required<OverviewProps>) {
  const [params, setParams] = useSearchParams();
  const cursor = params.get('cursor') ?? undefined;
  const finding = readFinding(params.get('finding'));
  const history = useRunHistory({ cursor, finding, loader: loadHistory });

  function changeFilter(value: string) {
    const next = new URLSearchParams();
    if (value !== 'all') next.set('finding', value);
    setParams(next);
  }

  return <OverviewLayout cursor={cursor} page={history.page} loading={history.loading}
    error={history.error} retry={history.refresh} finding={finding} changeFilter={changeFilter} />;
}

interface LayoutProps {
  demo?: boolean;
  cursor?: string;
  page?: CheckHistory;
  loading?: boolean;
  error?: boolean;
  retry?: () => void;
  finding?: FindingFilter;
  changeFilter?: (value: string) => void;
}

function OverviewLayout({ demo, cursor, page, loading, error, retry, finding, changeFilter }: LayoutProps) {
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<Sort>('recent');
  const entries = page?.entries ?? [];
  const search = query.trim().toLocaleLowerCase('ru');
  const shown = entries.filter((entry) => entry.title.toLocaleLowerCase('ru').includes(search));
  // The default order follows the server cursor. Name sorting applies to this page.
  if (sort === 'name') shown.sort((a, b) => a.title.localeCompare(b.title, 'ru', { numeric: true }));
  function pageLink(key?: string) {
    const params = new URLSearchParams();
    if (finding) params.set('finding', finding);
    if (key) params.set('cursor', key);
    const search = params.toString();
    return search ? '/checks?' + search : '/checks';
  }

  return (
    <div className="checks-overview">
      <div className="overview-heading">
        <div>
          <h1>Проверки</h1>
          <p>Сверяйте отчёты с первичными документами. Разбирайте только то, что требует внимания.</p>
        </div>
      </div>
      <section className="overview-section" aria-label="История запусков" aria-busy={loading}>
        <div className="overview-section-heading">
          <h2>Ваши проверки {page && <span>{entries.length}</span>}</h2>
        </div>
        {!demo && <div className="overview-toolbar">
          <div className="overview-filters flex flex-wrap gap-1.5" role="group" aria-label="Фильтры проверок">
            {filters.map(([value, label]) => (
              <button type="button" key={value} aria-pressed={(finding ?? 'all') === value}
                onClick={() => changeFilter?.(value)}>{label}</button>
            ))}
          </div>
          <div className="overview-inputs flex items-center gap-2.5">
            <label className="overview-search">
              <OverviewIcon name="search" size={16} />
              <input type="search" aria-label="Поиск на странице" placeholder="Название проверки"
                value={query} onChange={(event) => setQuery(event.target.value)} />
            </label>
            <label className="flex items-center gap-2 text-[13px]">
              Сортировка
              <select className="overview-secondary" value={sort}
                onChange={(event) => setSort(event.target.value === 'name' ? 'name' : 'recent')}>
                <option value="recent">Сначала новые</option>
                <option value="name">По названию</option>
              </select>
            </label>
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
          filtered={!!finding || !!search}
          reset={() => { setQuery(''); changeFilter?.('all'); }}
        />}
        {(cursor || page?.nextCursor) && <nav className="overview-footer flex flex-wrap gap-2" aria-label="Страницы проверок">
            {cursor && <Link className="overview-secondary" to={pageLink()}>К новым проверкам</Link>}
            {page?.nextCursor && <Link className="overview-secondary" to={pageLink(page.nextCursor)}>Более ранние проверки</Link>}
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

function HistoryTable({ entries, hasEntries, sort, filtered, reset }: {
  entries: HistoryEntry[];
  hasEntries: boolean;
  sort: Sort;
  filtered: boolean;
  reset: () => void;
}) {
  return (
    <div className="overview-table-wrap">
      <table className="overview-table">
        <thead><tr>
          <th scope="col">Проверка</th><th scope="col">Состояние задания</th>
          <th scope="col">Результат сверки</th>
          <th scope="col" aria-sort={sort === 'recent' ? 'descending' : 'none'}>Дата</th>
          <th scope="col" aria-label="Открыть" />
        </tr></thead>
        <tbody>{entries.map((entry) => {
          const to = '/checks/' + encodeURIComponent(entry.id);
          const tone = tones[entry.status];
          return <tr key={entry.id}>
            <td><CheckTitle to={to} title={entry.title} tone={tone} />
              {entry.synthetic && <small>Синтетика</small>}
            </td>
            <td className="overview-result">
              <span className={classes('overview-chip', tone)}>{runStatusLabels[entry.status]}</span>
              {entry.error && <p className="text-xs">{entry.error}</p>}
            </td>
            <td className="overview-finding">{entry.counts ? <ul className="space-y-1 text-[13px]">
              {entry.counts.verified > 0 && <li>Подтверждено: {entry.counts.verified}</li>}
              {entry.counts.discrepancy > 0 && <li>Расхождения: {entry.counts.discrepancy}</li>}
              {entry.counts.unverified > 0 && <li>Не проверено: {entry.counts.unverified}</li>}
              {Object.values(entry.counts).every((count) => count === 0) && <li>Нет показателей</li>}
            </ul> : '—'}</td>
            <td className="overview-date"><time dateTime={entry.createdAt}>{dateFormat.format(new Date(entry.createdAt))}</time></td>
            <td className="overview-open-cell"><OpenCheck to={to} title={entry.title} /></td>
          </tr>;
        })}</tbody>
      </table>
      {entries.length === 0 && <div className="overview-empty">
        <OverviewIcon name="file" size={32} />
        <h3>{(hasEntries || filtered) ? 'Проверки не найдены.' : 'Проверок пока нет.'}</h3>
        {(hasEntries || filtered) && <button type="button" className="overview-secondary" onClick={reset}>Сбросить фильтры</button>}
      </div>}
    </div>
  );
}
