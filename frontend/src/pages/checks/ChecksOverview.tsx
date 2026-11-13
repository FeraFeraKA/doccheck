import { useState } from 'react';
import { Link } from 'react-router';
import { demoResult, demoRunPath } from './demoData';

export function ChecksOverview() {
  const [query, setQuery] = useState('');
  const { scope, summary, documents } = demoResult;
  const title = 'Синтетическая сверка';
  const matches = (title + ' ' + scope.contract_number).toLowerCase().includes(query.trim().toLowerCase());

  return (
    <>
      <div className="checks-heading">
        <div><h1>Проверки</h1><p>Отчёты и результаты сверки</p></div>
        <Link className="checks-button checks-primary" to="/checks/new">Новая проверка</Link>
      </div>
      <div className="checks-stats">
        <div><span>Подтверждено</span><strong>{summary.counts.verified}</strong></div>
        <div><span>Расхождения</span><strong>{summary.counts.discrepancy}</strong></div>
        <div><span>Не проверено</span><strong>{summary.counts.unverified}</strong></div>
      </div>
      <section className="checks-card">
        <div className="checks-heading">
          <h2>Все проверки</h2>
          <label>Поиск <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        </div>
        {matches ? (
          <div className="checks-table-scroll">
            <table>
              <thead><tr><th>Проверка</th><th>Договор</th><th>Период</th><th>Документы</th><th>Результат</th></tr></thead>
              <tbody><tr>
                <td><Link to={demoRunPath}>{title}</Link></td>
                <td>{scope.contract_number}</td>
                <td>{scope.period_start} — {scope.period_end}</td>
                <td>{documents.length}</td>
                <td>Завершена с замечаниями</td>
              </tr></tbody>
            </table>
          </div>
        ) : <p>Проверки не найдены.</p>}
      </section>
    </>
  );
}
