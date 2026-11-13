import { useCallback, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { loadRunHistory, runStatusLabels } from './checkData';
import type { CheckHistory, HistoryEntry } from './checkData';
import { demoRunPath, demoTitle } from './demoData';
import { useCheckData } from './useCheckData';

interface OverviewProps {
  loadHistory?: (signal: AbortSignal, cursor?: string) => Promise<CheckHistory>;
}

const dateFormat = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' });

export function ChecksOverview({ loadHistory = loadRunHistory }: OverviewProps = {}) {
  const [query, setQuery] = useState('');
  const [params] = useSearchParams();
  const cursor = params.get('cursor') ?? '';
  const load = useCallback((key: string, signal: AbortSignal) => loadHistory(signal, key || undefined), [loadHistory]);
  const { state, retry } = useCheckData(cursor, load);
  const search = query.trim().toLowerCase();

  return (
    <>
      <div className="checks-heading">
        <div><h1>Проверки</h1><p>Отчёты и результаты сверки</p></div>
        <Link className="checks-button checks-primary" to="/checks/new">Новая проверка</Link>
      </div>
      <section className="checks-card" aria-busy={state.phase === 'loading'}>
        <div className="checks-heading">
          <h2>История запусков</h2>
          <label>Поиск на странице <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        </div>
        {state.phase === 'loading' && <p role="status">Загрузка проверок…</p>}
        {state.phase === 'failed' && <>
          <p role="alert">Не удалось загрузить проверки.</p>
          <button type="button" onClick={retry}>Повторить</button>
        </>}
        {state.phase === 'ready' && <HistoryTable entries={state.data.entries} search={search} />}
        {cursor && <Link className="checks-button" to="/checks">К новым проверкам</Link>}
        {state.phase === 'ready' && state.data.nextCursor && <Link className="checks-button" to={{
          pathname: '/checks', search: '?' + new URLSearchParams({ cursor: state.data.nextCursor }),
        }}>Более ранние проверки</Link>}
      </section>
      <section className="checks-card">
        <h2>Готовый пример</h2>
        <Link to={demoRunPath}>{demoTitle}</Link>
      </section>
    </>
  );
}

function HistoryTable({ entries, search }: { entries: HistoryEntry[]; search: string }) {
  if (entries.length === 0) return <p>Проверок пока нет.</p>;

  const matches = entries.filter(({ title }) => title.toLowerCase().includes(search));
  if (matches.length === 0) return <p>Проверки не найдены.</p>;

  return (
    <div className="checks-table-scroll">
      <table>
        <thead><tr><th>Проверка</th><th>Создана</th><th>Состояние</th></tr></thead>
        <tbody>{matches.map((entry) => (
          <tr key={entry.id}>
            <td><Link to={'/checks/' + encodeURIComponent(entry.id)}>{entry.title}</Link></td>
            <td><time dateTime={entry.createdAt}>{dateFormat.format(new Date(entry.createdAt))}</time></td>
            <td>{runStatusLabels[entry.status]}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}
