import { useCallback, useState } from 'react';
import { Link } from 'react-router';
import { loadDemoHistory, runStatusLabels } from './checkData';
import type { CheckHistory, HistoryEntry } from './checkData';
import { useCheckData } from './useCheckData';

interface OverviewProps {
  loadHistory?: (signal: AbortSignal) => Promise<CheckHistory>;
}

export function ChecksOverview({ loadHistory = loadDemoHistory }: OverviewProps = {}) {
  const [query, setQuery] = useState('');
  const load = useCallback((_key: string, signal: AbortSignal) => loadHistory(signal), [loadHistory]);
  const { state, retry } = useCheckData('history', load);
  const search = query.trim().toLowerCase();
  const counts = state.phase === 'ready' ? state.data.indicatorCounts : undefined;

  return (
    <>
      <div className="checks-heading">
        <div><h1>Проверки</h1><p>Отчёты и результаты сверки</p></div>
        <Link className="checks-button checks-primary" to="/checks/new">Новая проверка</Link>
      </div>
      {counts && <div className="checks-stats">
        <div><span>Подтверждено</span><strong>{counts.verified}</strong></div>
        <div><span>Расхождения</span><strong>{counts.discrepancy}</strong></div>
        <div><span>Не проверено</span><strong>{counts.unverified}</strong></div>
      </div>}
      <section className="checks-card" aria-busy={state.phase === 'loading'}>
        <div className="checks-heading">
          <h2>Все проверки</h2>
          <label>Поиск <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        </div>
        {state.phase === 'loading' && <p role="status">Загрузка проверок…</p>}
        {state.phase === 'failed' && <>
          <p role="alert">Не удалось загрузить проверки.</p>
          <button type="button" onClick={retry}>Повторить</button>
        </>}
        {state.phase === 'ready' && <HistoryTable entries={state.data.entries} search={search} />}
      </section>
    </>
  );
}

function HistoryTable({ entries, search }: { entries: HistoryEntry[]; search: string }) {
  if (entries.length === 0) return <p>Проверок пока нет.</p>;

  const matches = entries.filter(({ title, contractNumber, id }) =>
    [title, contractNumber, id].some((value) => value?.toLowerCase().includes(search)),
  );
  if (matches.length === 0) return <p>Проверки не найдены.</p>;

  return (
    <div className="checks-table-scroll">
      <table>
        <thead><tr><th>Проверка</th><th>Договор</th><th>Период</th><th>Документы</th><th>Состояние</th></tr></thead>
        <tbody>{matches.map((entry) => (
          <tr key={entry.id}>
            <td><Link to={'/checks/' + encodeURIComponent(entry.id)}>{entry.title}</Link></td>
            <td>{entry.contractNumber ?? '—'}</td>
            <td>{entry.period ?? '—'}</td>
            <td>{entry.documentCount ?? '—'}</td>
            <td>{runStatusLabels[entry.status]}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}
