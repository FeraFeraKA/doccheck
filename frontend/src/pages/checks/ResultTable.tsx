import { Fragment } from 'react';
import type { Ref } from 'react';
import { formatDecimal, formatMeasure, rowExplanation, statusLabels } from './reviewResult';
import type { ReviewResult } from './reviewResult';
import { WorkspaceIcon } from './WorkspaceIcon';
import './result-table.css';

type Row = ReviewResult['rows'][number];
type Evidence = ReviewResult['evidence'][number];
type Document = ReviewResult['documents'][number];
type EvidenceField = 'amount_refs' | 'contract_refs' | 'period_refs' | 'article_refs' | 'identity_refs';

interface ResultTableProps {
  rows: Row[];
  total: number;
  filters: readonly (readonly [string, string, number])[];
  filter: string;
  query: string;
  selectedId?: string;
  activeSourceRowId?: string;
  selectedEvidenceId?: string;
  expanded: ReadonlySet<string>;
  tableScroll: Ref<HTMLDivElement>;
  selectedRow: Ref<HTMLTableRowElement>;
  evidenceFields: readonly (readonly [EvidenceField, string])[];
  evidenceById: ReadonlyMap<string, Evidence>;
  documentsById: ReadonlyMap<string, Document>;
  formatAddress: (locator: Evidence['locator']) => string;
  onFilterChange: (value: string) => void;
  onQueryChange: (value: string) => void;
  onReset: () => void;
  onToggle: (id: string) => void;
  onSelectSource: (rowId: string, evidenceId: string, trigger: HTMLElement) => void;
}

export function ResultTable({
  rows, total, filters, filter, query, selectedId, activeSourceRowId, selectedEvidenceId, expanded,
  tableScroll, selectedRow, evidenceFields, evidenceById, documentsById,
  formatAddress, onFilterChange, onQueryChange, onReset, onToggle, onSelectSource,
}: ResultTableProps) {
  return (
    <section className="reconcile-left result-table-pane">
      <div className="reconcile-filters" role="group" aria-label="Статус показателя">
        {filters.map(([value, label, count]) => (
          <button type="button" key={value} aria-pressed={filter === value} onClick={() => onFilterChange(value)}>
            {label} <span>{count}</span>
          </button>
        ))}
      </div>
      <div className="reconcile-search">
        <WorkspaceIcon name="search" size={15} />
        <input
          type="search" aria-label="Поиск показателя или документа"
          placeholder="Показатель или номер документа…" value={query}
          onChange={(event) => onQueryChange(event.target.value)}
        />
        {query && <button type="button" aria-label="Очистить поиск" onClick={() => onQueryChange('')}><WorkspaceIcon name="close" size={14} /></button>}
      </div>
      <div ref={tableScroll} className="reconcile-table-scroll" role="region" aria-label="Таблица показателей" tabIndex={0}>
        <table className="reconcile-table kfz-result-table" aria-label="Показатели КФЗ">
          <thead><tr>
            <th scope="col">Показатель КФЗ</th><th scope="col">В КФЗ</th>
            <th scope="col">Ожидаемо</th><th scope="col">Разница Δ</th><th scope="col">Статус</th>
            <th scope="col">Пояснение</th>
          </tr></thead>
          <tbody>{rows.map((row) => {
            const selected = row.id === selectedId;
            const isExpanded = expanded.has(row.id);
            const detailsId = `details-${row.id}`;
            const components = row.calculation?.components ?? [];
            const sourceDocuments = new Set(components.flatMap((component) =>
              component.amount_refs.flatMap((id) => {
                const item = evidenceById.get(id);
                return item && documentsById.has(item.document_id) ? [item.document_id] : [];
              }),
            ));
            return (
              <Fragment key={row.id}>
                <tr ref={selected ? selectedRow : undefined} data-selected={row.id === activeSourceRowId} data-status={row.status}
                  onClick={(event) => {
                    if (event.target instanceof Element && !event.target.closest('a, button, .row-status, details')) onToggle(row.id);
                  }}>
                  <td>
                    <button
                      id={`indicator-${row.id}`} className="row-name-button indicator-name"
                      type="button" aria-pressed={selected} aria-expanded={isExpanded}
                      aria-controls={isExpanded ? detailsId : undefined}
                      onClick={() => onToggle(row.id)}
                    >
                      <span className="indicator-chevron"><WorkspaceIcon name="chevron" size={14} /></span>
                      <span>{row.label}{row.unit !== 'RUB' && <small className="ml-1">({row.unit})</small>}</span>
                    </button>
                    <span className="indicator-meta">
                      {sourceDocuments.size ? `${sourceDocuments.size} док.` : 'Нет источника'}
                    </span>
                  </td>
                  <td><Measure value={row.reported_value} unit={row.unit} /></td>
                  <td className="expected-cell">
                    <Measure value={row.expected_value} unit={row.unit} />
                    {row.expected_value === null && row.observed_evidence_sum !== null && (
                      <small className="checks-caption">Частичная сумма: {formatMeasure(row.observed_evidence_sum, row.unit)}</small>
                    )}
                  </td>
                  <td className="difference-cell"><Measure value={row.delta} unit={row.unit} /></td>
                  <td className="indicator-status-cell"><span className="row-status" data-status={row.status}
                    role="img" aria-label={statusLabels[row.status]} tabIndex={0} title={statusLabels[row.status]}>
                    <WorkspaceIcon name={row.status === 'verified' ? 'check' : row.status === 'discrepancy' ? 'warning' : 'help'} size={14} />
                    <span className="indicator-status-label" aria-hidden="true">{statusLabels[row.status]}</span>
                  </span></td>
                  <td className="indicator-explanation">
                    <p>{rowExplanation(row)}</p>
                    {(components.length > 0 || row.reasons.length > 1 || row.completeness.reason !== rowExplanation(row)) &&
                      <button type="button" aria-expanded={isExpanded} aria-controls={isExpanded ? detailsId : undefined}
                        onClick={() => onToggle(row.id)}>
                        {components.length ? 'Как рассчитано' : 'Основание проверки'}
                      </button>}
                  </td>
                </tr>
                {isExpanded && <tr className="source-subrow"><td colSpan={6}>
                  <div id={detailsId} role="region" aria-label={`Подробности: ${row.label}`} className="indicator-details">
                    {row.calculation?.formula && <p>{row.calculation.formula}</p>}
                    <p><strong>{statusLabels[row.status]}.</strong>{' '}
                      {[...new Set([rowExplanation(row), ...row.reasons.map(({ message }) => message),
                        row.completeness.reason])].join(' ')}
                    </p>
                    {components.length === 0 ? <p>Нет подтверждённых слагаемых.</p> :
                      <ol className="indicator-documents" aria-label={`Слагаемые показателя: ${row.label}`}>
                        {components.map((component) => <li key={component.amount_refs[0]}>
                          <div className="indicator-amount">
                            {component.amount_refs[0] && <button type="button" className="indicator-component-document"
                              onClick={(event) => onSelectSource(row.id, component.amount_refs[0], event.currentTarget)}>
                              {documentsById.get(evidenceById.get(component.amount_refs[0])?.document_id ?? '')?.name
                                ?? 'Источник суммы'}
                            </button>}
                            <strong>{formatMeasure(component.amount, row.unit)}</strong>
                          </div>
                          <details className="indicator-component-details">
                            <summary>Адреса и основание</summary>
                            <p>{component.relation_reason}</p>
                            <ul className="indicator-addresses">
                              {evidenceFields.flatMap(([field, role]) => (component[field] ?? []).map((id) => {
                                const item = evidenceById.get(id);
                                const document = item && documentsById.get(item.document_id);
                                return <li key={`${field}:${id}`}>
                                  {item && document ? <button
                                    type="button" aria-pressed={selected && selectedEvidenceId === id}
                                    onClick={(event) => onSelectSource(row.id, id, event.currentTarget)}
                                  >
                                    <span>{role} · {document.name} · {formatAddress(item.locator)}</span>
                                    <span aria-hidden="true">›</span>
                                  </button> : <span>{role} · Адрес источника недоступен.</span>}
                                </li>;
                              }))}
                            </ul>
                          </details>
                        </li>)}
                      </ol>}
                  </div>
                </td></tr>}
              </Fragment>
            );
          })}</tbody>
        </table>
      </div>
      {rows.length === 0 && <div className="reconcile-empty">
        <p role="status">Показатели не найдены.</p>
        <button type="button" onClick={onReset}>Сбросить фильтры</button>
      </div>}
      <p className="sr-only">Показателей: {rows.length} из {total}. Прочерк означает, что значение отсутствует.</p>
    </section>
  );
}

function Measure({ value, unit }: { value: string | null; unit: string }) {
  if (value === null) return '—';
  return <>{formatDecimal(value)} <small className="measure-unit">{unit === 'RUB' ? '₽' : unit}</small></>;
}
