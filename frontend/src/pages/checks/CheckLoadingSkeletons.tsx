import type { CheckView } from './ResultHeader';
import './check-loading-skeletons.css';

export function CheckResultSkeleton({ view }: { view: CheckView }) {
  const documents = view === 'documents' || view === 'exceptions';
  return <>
    <p role="status" className="sr-only">Загрузка проверки…</p>
    <section className="check-loading" aria-label={documents ? 'Документы' : 'Результат проверки'} aria-busy="true">
      <div aria-hidden="true">
        <header className="check-result-header">
          <div className="check-skeleton-block check-skeleton-title w-56" />
          <div className="check-skeleton-block mt-1 h-5 w-80" />
          <div className="check-header-controls mt-6 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <div className="check-result-tabs flex gap-6">
                <span className="check-skeleton-block check-skeleton-tab w-24" />
                <span className="check-skeleton-block check-skeleton-tab w-28" />
              </div>
              {documents && <div className="flex flex-wrap gap-1">
                <span className="check-skeleton-block h-7 w-14" />
                <span className="check-skeleton-block h-7 w-20" />
                <span className="check-skeleton-block h-7 w-24" />
              </div>}
            </div>
            <span className="check-skeleton-block h-8 w-28" />
          </div>
        </header>
        {(view === 'table' || view === 'conclusion') && <div className="result-summary">
          <div className="check-skeleton-block mb-1 h-4 w-28" />
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <span className="check-skeleton-block h-8 w-40" />
            <span className="check-skeleton-block h-4 w-28" />
            <span className="check-skeleton-block h-4 w-28" />
            <span className="check-skeleton-block h-4 w-28" />
          </div>
          <div className="mt-3 max-w-[930px] space-y-2">
            <div className="check-skeleton-block h-4 w-4/5" />
            <div className="check-skeleton-block h-4 w-3/5" />
            <div className="check-skeleton-block h-4 w-2/3" />
          </div>
        </div>}
        {view === 'table' && <div className="result-reconciliation mt-4">
          <div className="result-table-pane">
            <div className="grid h-[52px] content-center">
              <div className="check-skeleton-block h-5 w-44" />
            </div>
            <div className="reconcile-filters">
              {[50, 100, 90, 105].map((width) => <span key={width} style={{ width }}
                className="check-skeleton-block h-8 shrink-0" />)}
            </div>
            <div className="reconcile-search"><span className="check-skeleton-block h-4 w-52" /></div>
            <SkeletonTable />
          </div>
        </div>}
        {documents && <div className="result-documents">
          <SkeletonTable documents />
        </div>}
        {view === 'log' && <div className="checks-card mt-4">
          <span className="check-skeleton-block mb-3 h-5 w-36" />
          <span className="check-skeleton-block h-4 w-60" />
        </div>}
      </div>
    </section>
  </>;
}

function SkeletonTable({ documents = false }: { documents?: boolean }) {
  const columns = Array.from({ length: documents ? 8 : 6 }, (_, index) => index);
  return <div className="check-skeleton-table">
    <table className={documents ? 'result-document-table' : 'reconcile-table kfz-result-table'}>
      <thead><tr>{columns.map((column) => <th key={column}>
        <span className="check-skeleton-block h-3 w-3/4 max-w-24" />
      </th>)}</tr></thead>
      <tbody>{[0, 1, 2].map((row) => <tr key={row}>{columns.map((column) => <td key={column}>
        <span className="check-skeleton-block h-3.5 w-4/5 max-w-36" />
      </td>)}</tr>)}</tbody>
    </table>
  </div>;
}

export function RunPackSkeleton() {
  return <>
    <p role="status" className="sr-only">Загружаем список документов…</p>
    <section aria-label="Комплект документов" aria-busy="true">
      <div aria-hidden="true">
        <div className="mt-6 grid grid-cols-1 items-start gap-5 md:grid-cols-2">
          {['КФЗ', 'Первичные документы'].map((label) => <div key={label} className="upload-card min-w-0">
            <header className="upload-card-header"><div>
              <h2>{label}</h2>
              <div className="check-skeleton-block mt-2.5 h-5 w-40" />
            </div></header>
            <div className="upload-file-row">
              <span className="check-skeleton-block size-8 shrink-0" />
              <span className="check-skeleton-block h-4 w-1/2" />
            </div>
            <span className="check-skeleton-block mt-3 h-7 w-36" />
          </div>)}
        </div>
        <span className="check-skeleton-block mt-5 h-10 w-44" />
      </div>
    </section>
  </>;
}
