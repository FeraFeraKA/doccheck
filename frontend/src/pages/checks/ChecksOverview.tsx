import { useState } from 'react';
import type { MouseEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { loadRunHistory, runStatusLabels } from './checkData';
import type { CheckHistory, FindingCounts, FindingFilter, HistoryEntry, RunStatus } from './checkData';
import { OverviewIcon } from './OverviewIcon';
import { runQueuePath } from './runTitle';
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
type Filter = typeof filters[number][0];
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

function findingLabel(counts: FindingCounts) {
  if (counts.discrepancy > 0) return { label: 'Есть расхождения', tone: 'peach' };
  if (counts.unverified > 0) return { label: 'Неполные данные', tone: 'neutral' };
  if (counts.verified > 0) return { label: 'Без расхождений', tone: 'mint' };
  return { label: 'Нет показателей', tone: 'neutral' };
}

const loadArchivedHistory: typeof loadRunHistory = (signal, cursor, finding) =>
  loadRunHistory(signal, cursor, finding, 'archive');

export function ChecksOverview({ loadHistory = loadRunHistory, archive = false }: OverviewProps & { archive?: boolean } = {}) {
  return import.meta.env.VITE_DOCCHECK_PUBLIC_DEMO === '1'
    ? <OverviewLayout demo archive={archive} />
    : <RunHistory loadHistory={archive ? loadArchivedHistory : loadHistory} archive={archive} />;
}

function RunHistory({ loadHistory, archive }: Required<OverviewProps> & { archive: boolean }) {
  const [params, setParams] = useSearchParams();
  const cursor = params.get('cursor') ?? undefined;
  const finding = archive ? undefined : readFinding(params.get('finding'));
  const history = useRunHistory({ cursor, finding, loader: loadHistory });

  function changeFilter(value: Filter) {
    const next = new URLSearchParams();
    if (value !== 'all') next.set('finding', value);
    setParams(next);
  }

  return <OverviewLayout archive={archive} cursor={cursor} page={history.page} loading={history.loading}
    error={history.error} retry={history.refresh} finding={finding} changeFilter={changeFilter} />;
}

interface LayoutProps {
  archive?: boolean;
  demo?: boolean;
  cursor?: string;
  page?: CheckHistory;
  loading?: boolean;
  error?: boolean;
  retry?: () => void;
  finding?: FindingFilter;
  changeFilter?: (value: Filter) => void;
}

function OverviewLayout({ demo, archive, cursor, page, loading, error, retry, finding, changeFilter }: LayoutProps) {
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<Sort>('recent');
  const order = archive ? 'recent' : sort;
  const entries = page?.entries ?? [];
  const search = query.trim().toLocaleLowerCase('ru');
  const shown = entries.filter((entry) =>
    `${entry.title} ${entry.contractNumber ?? ''}`.toLocaleLowerCase('ru').includes(search),
  );
  // The default order follows the server cursor. Name sorting applies to this page.
  if (order === 'name') shown.sort((a, b) => a.title.localeCompare(b.title, 'ru', { numeric: true }));

  function pageLink(key?: string) {
    const params = new URLSearchParams();
    if (finding) params.set('finding', finding);
    if (key) params.set('cursor', key);
    const searchParams = params.toString();
    const path = archive ? '/archive' : '/checks';
    return searchParams ? path + '?' + searchParams : path;
  }

  return (
    <div className="checks-overview">
      <div className="overview-heading">
        <div>
          <h1>{archive ? 'Архив проверок' : 'Проверки'}</h1>
          <p>{archive ? 'Архивные проверки и их документы.' : 'Сверяйте отчёты с первичными документами. Разбирайте только то, что требует внимания.'}</p>
        </div>
      </div>
      <section className="overview-section" aria-label={archive ? "Архив запусков" : "История запусков"} aria-busy={loading}>
        {!demo && <div className="overview-toolbar">
          <label className="overview-search">
            <OverviewIcon name="search" size={16} />
            <input type="search" aria-label="Поиск на странице" placeholder="Название или договор"
              value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          {!archive && <div className="overview-filters" role="group" aria-label="Фильтры проверок">
            {filters.map(([value, label]) => (
              <button type="button" key={value} aria-pressed={(finding ?? 'all') === value}
                onClick={() => changeFilter?.(value)}>{label}</button>
            ))}
          </div>}
          {!archive && <label className="overview-sort">
            <span>Сортировка</span>
            <select className="overview-secondary" value={sort}
              onChange={(event) => setSort(event.target.value === 'name' ? 'name' : 'recent')}>
              <option value="recent">Сначала новые</option>
              <option value="name">По названию</option>
            </select>
          </label>}
        </div>}
        {demo && <p className="overview-notice">История рабочих проверок доступна в локальной установке.</p>}
        {loading && <p className="overview-notice" role="status">Загрузка проверок…</p>}
        {error && <div className="overview-notice">
          <p role="alert">Не удалось загрузить проверки.</p>
          <button type="button" className="overview-secondary" onClick={retry}>Повторить</button>
        </div>}
        {page && <HistoryTable
          entries={shown}
          archive={archive}
          sort={order}
          filtered={!!finding || !!search}
          reset={() => { setQuery(''); changeFilter?.('all'); }}
        />}
        {(cursor || page?.nextCursor) && <nav className="overview-footer flex flex-wrap gap-2" aria-label="Страницы проверок">
          {cursor && <Link className="overview-secondary" to={pageLink()}>К новым проверкам</Link>}
          {page?.nextCursor && <Link className="overview-secondary" to={pageLink(page.nextCursor)}>Более ранние проверки</Link>}
        </nav>}
      </section>
    </div>
  );
}

function CheckTitle({ to, title, tone, synthetic, contractNumber, active }: {
  to: string; title: string; tone: string; synthetic?: boolean; contractNumber?: string; active: boolean;
}) {
  return <div className="overview-check-title">
    <span className={classes('overview-file-symbol', tone)}><OverviewIcon name="file" size={21} /></span>
    <div>
      <Link to={to} title={active ? 'К очереди проверок' : undefined}>{title}</Link>
      {contractNumber && <small>Договор {contractNumber}</small>}
      {synthetic && <small>Синтетика</small>}
    </div>
  </div>;
}

function CheckResult({ entry }: { entry: HistoryEntry }) {
  const { counts, status, error } = entry;
  const finding = counts && (status === 'completed' || status === 'completed_with_issues') ? findingLabel(counts) : undefined;
  return <>
    <span className={classes('overview-chip', finding?.tone ?? tones[status])}>
      {finding?.label ?? runStatusLabels[status]}
    </span>
    {finding && counts && counts.discrepancy > 0 && counts.unverified > 0 &&
      <span className="overview-chip neutral overview-secondary-finding">Неполные данные</span>}
    {finding && <small className="overview-result-detail">{runStatusLabels[status]}</small>}
    {error && <p className="overview-result-detail">{error}</p>}
  </>;
}

function HistoryTable({ entries, archive, sort, filtered, reset }: {
  archive?: boolean;
  entries: HistoryEntry[];
  sort: Sort;
  filtered: boolean;
  reset: () => void;
}) {
  const navigate = useNavigate();
  function openRow(event: MouseEvent<HTMLTableRowElement>, to: string) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey
      || event.shiftKey || event.altKey || (event.target instanceof Element && event.target.closest('a, button'))
      || window.getSelection()?.toString()) return;
    void navigate(to);
  }

  return (
    <div className="overview-table-wrap">
      <table className="overview-table">
        <thead><tr>
          <th scope="col">Проверка</th>
          <th scope="col">Результат</th>
          <th scope="col">Покрытие по сумме</th>
          <th scope="col">Документы</th>
          <th scope="col" aria-sort={sort === 'recent' ? 'descending' : 'none'}>{archive ? 'Дата архивации' : 'Дата'}</th>
        </tr></thead>
        <tbody>{entries.map((entry) => {
          const { id, title, counts, status, synthetic, createdAt } = entry;
          const active = status === 'queued' || status === 'processing';
          const to = active ? runQueuePath(id) : '/checks/' + encodeURIComponent(id);
          const tone = counts ? findingLabel(counts).tone : tones[status];
          const total = counts ? counts.verified + counts.discrepancy + counts.unverified : 0;
          return <tr key={id} className="overview-check-row" onClick={(event) => openRow(event, to)}>
            <td><CheckTitle to={to} title={title} tone={tone} synthetic={synthetic}
              contractNumber={entry.contractNumber} active={active} /></td>
            <td className="overview-result">
              {archive && <span className="overview-chip neutral">В архиве</span>}
              <CheckResult entry={entry} />
            </td>
            <td className="overview-coverage">
              <span aria-label="Покрытие по сумме недоступно">—</span>
              {counts && total > 0 && <small>{counts.verified} из {total} показателей</small>}
            </td>
            <td className="overview-documents">
              {entry.documentCount === undefined ? <span aria-label="Количество документов недоступно">—</span>
                : <span className="overview-document-count"><OverviewIcon name="files" size={15} />{entry.documentCount}</span>}
            </td>
            <td className="overview-date"><time dateTime={entry.archivedAt ?? createdAt}>{dateFormat.format(new Date(entry.archivedAt ?? createdAt))}</time></td>
          </tr>;
        })}</tbody>
      </table>
      {entries.length === 0 && <div className="overview-empty">
        <OverviewIcon name="file" size={32} />
        <h3>{filtered ? 'Проверки не найдены.' : archive ? 'Архив пока пуст.' : 'Проверок пока нет.'}</h3>
        {filtered && <button type="button" className="overview-secondary" onClick={reset}>Сбросить фильтры</button>}
      </div>}
    </div>
  );
}
