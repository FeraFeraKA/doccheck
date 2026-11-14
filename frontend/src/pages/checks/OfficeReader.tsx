import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { getOfficePreview } from './documentPreviewApi';
import type { OfficePreview } from './documentPreviewApi';
import { getSourceFragmentPreview } from './sourceApi';
import type { SourceEvidence } from './sourceApi';
import { WorkspaceIcon } from './WorkspaceIcon';
import './document-reader.css';

type Locator = SourceEvidence['locator'];
type Fragment = Awaited<ReturnType<typeof getSourceFragmentPreview>>;
export type SourceTone = 'discrepancy' | 'unverified' | 'verified';
type Window = { sheet?: string; row: number; column: number };

function cellPosition(address: string) {
  const [, letters, digits] = /^([A-Z]+)(\d+)$/.exec(address) ?? [];
  const column = [...(letters ?? 'A')].reduce((total, letter) => total * 26 + letter.charCodeAt(0) - 64, 0);
  return { column, row: Number(digits ?? 1) };
}

function columnName(index: number) {
  let name = '';
  for (let column = index; column > 0; column = Math.floor((column - 1) / 26)) {
    name = String.fromCharCode(65 + (column - 1) % 26) + name;
  }
  return name;
}

function addressWindow(locator: Locator | undefined): Window {
  if (locator?.kind !== 'sheet') return { row: 1, column: 1 };
  const cell = cellPosition(locator.range.split(':')[0]);
  return { sheet: locator.sheet, row: Math.max(1, cell.row - 5), column: Math.max(1, cell.column - 3) };
}

function rangeBounds(locator: Locator | undefined, sheet: string) {
  if (locator?.kind !== 'sheet' || locator.sheet !== sheet) return;
  const [first, last = first] = locator.range.split(':');
  return { first: cellPosition(first), last: cellPosition(last) };
}

export function OfficeReader({ runId, documentId, format, locator, evidenceId, tone, active, fallback }: {
  runId: string;
  documentId: string;
  format: 'xlsx' | 'docx';
  locator?: Locator;
  evidenceId: string | null;
  tone?: SourceTone;
  active: boolean;
  fallback: ReactNode;
}) {
  const [attempt, setAttempt] = useState(0);
  const [manualWindow, setWindow] = useState<Window>();
  const [documentState, setDocumentState] = useState<{ request: string; preview: OfficePreview | null }>();
  const [textState, setTextState] = useState<{ id: string; fragment: Fragment }>();
  const viewing = manualWindow ?? addressWindow(locator);
  const params = new URLSearchParams();
  if (format === 'xlsx') {
    if (viewing.sheet) params.set('sheet', viewing.sheet);
    if (viewing.row > 1) params.set('row', String(viewing.row));
    if (viewing.column > 1) params.set('column', String(viewing.column));
  }
  const query = params.toString();
  const request = query + '#' + attempt;
  const preview = documentState?.request === request ? documentState.preview : undefined;
  const fragment = textState?.id === evidenceId ? textState.fragment : null;
  const focus = useRef<HTMLElement | null>(null);
  function trackFocus(node: HTMLElement | null) { focus.current = node; }
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const abort = new AbortController();
    void getOfficePreview(runId, documentId, new URLSearchParams(query), abort.signal).then(
      (value) => {
        if (!abort.signal.aborted) setDocumentState({ request, preview: value });
      },
      () => {
        if (!abort.signal.aborted) setDocumentState({ request, preview: null });
      },
    );
    return () => abort.abort();
  }, [runId, documentId, query, request]);

  useEffect(() => {
    if (!evidenceId) return;
    const abort = new AbortController();
    void getSourceFragmentPreview(runId, documentId, evidenceId, abort.signal).then(
      (value) => {
        if (!abort.signal.aborted) setTextState({ id: evidenceId, fragment: value });
      },
      () => {},
    );
    return () => abort.abort();
  }, [runId, documentId, evidenceId]);

  useLayoutEffect(() => {
    const target = focus.current;
    const container = scroller.current;
    if (!preview || !active || !target || !container) return;
    const from = container.getBoundingClientRect();
    const to = target.getBoundingClientRect();
    container.scrollTop += to.top + to.height / 2 - from.top - container.clientHeight / 2;
    container.scrollLeft += to.left + to.width / 2 - from.left - container.clientWidth / 2;
  }, [active, locator, preview]);

  const matchingPreview = preview && (format === 'xlsx' ? 'sheets' in preview : 'blocks' in preview) ? preview : null;
  if (preview === undefined) return <div className="source-viewer-placeholder"><p role="status">Чтение документа…</p></div>;
  if (!matchingPreview) return <div className="source-viewer-placeholder">
    <p role="alert">Не удалось открыть предпросмотр. Оригинал можно скачать.</p>
    <button type="button" onClick={() => setAttempt((current) => current + 1)}>Повторить предпросмотр</button>
    {fallback}
  </div>;

  function highlight(text: string) {
    if (fragment?.text !== text || !fragment.match) return text;
    const [before, match, after] = fragment.match;
    return <>{before}<mark>{match}</mark>{after}</>;
  }

  const mode = tone ?? 'source';
  if ('sheets' in matchingPreview) {
    const { sheet, sheets, row, column, last_row, last_column, rows } = matchingPreview;
    const columns = rows[0].length;
    const bounds = rangeBounds(locator, sheet);
    return <div className="document-reader">
      <div className="document-reader-controls">
        <label>Лист <select aria-label="Лист XLSX" value={sheet}
          onChange={(event) => setWindow({ sheet: event.currentTarget.value, row: 1, column: 1 })}>
          {sheets.map((title) => <option key={title}>{title}</option>)}
        </select></label>
        <div className="document-reader-paging" aria-label="Область листа">
          <button type="button" title="Предыдущие строки" aria-label="Предыдущие строки" disabled={row === 1}
            onClick={() => setWindow({ sheet, row: Math.max(1, row - rows.length), column })}><WorkspaceIcon name="chevron" size={15} /></button>
          <span>{row}–{row + rows.length - 1} / {last_row}</span>
          <button type="button" title="Следующие строки" aria-label="Следующие строки" disabled={row + rows.length > last_row}
            onClick={() => setWindow({ sheet, row: row + rows.length, column })}><WorkspaceIcon name="chevron" size={15} /></button>
          <button type="button" title="Предыдущие столбцы" aria-label="Предыдущие столбцы" disabled={column === 1}
            onClick={() => setWindow({ sheet, row, column: Math.max(1, column - columns) })}><WorkspaceIcon name="chevron" size={15} /></button>
          <span>{columnName(column)}–{columnName(column + columns - 1)}</span>
          <button type="button" title="Следующие столбцы" aria-label="Следующие столбцы" disabled={column + columns > last_column}
            onClick={() => setWindow({ sheet, row, column: column + columns })}><WorkspaceIcon name="chevron" size={15} /></button>
        </div>
        {manualWindow && locator?.kind === 'sheet' && <button type="button" onClick={() => setWindow(undefined)}>К источнику</button>}
      </div>
      <div ref={scroller} className="document-reader-scroll" tabIndex={0} aria-label={'Лист «' + sheet + '»'} role="region">
        <table className="document-reader-grid">
          <thead><tr><th aria-label="Строка" />{rows[0].map((_, index) =>
            <th key={column + index} scope="col">{columnName(column + index)}</th>,
          )}</tr></thead>
          <tbody>{rows.map((cells, index) => {
            const number = row + index;
            return <tr key={number}><th scope="row">{number}</th>{cells.map((text, offset) => {
              const current = column + offset;
              const address = columnName(current) + number;
              const selected = bounds && number >= bounds.first.row && number <= bounds.last.row
                && current >= bounds.first.column && current <= bounds.last.column;
              const first = selected && number === Math.max(row, bounds.first.row)
                && current === Math.max(column, bounds.first.column);
              return <td key={current} title={address} data-source-address={address}
                ref={first ? trackFocus : undefined}
                data-source-tone={selected ? mode : undefined}>{selected ? highlight(text) : text}</td>;
            })}</tr>;
          })}</tbody>
        </table>
      </div>
    </div>;
  }

  return <div className="document-reader">
    <div ref={scroller} className="document-reader-scroll" tabIndex={0} aria-label="Содержимое DOCX" role="region">
      <article className="document-reader-word">
        {matchingPreview.blocks.map((block) => {
          if ('paragraph' in block) {
            const selected = locator?.kind === 'paragraph' && locator.paragraph === block.paragraph;
            return <p key={'p' + block.paragraph} data-source-address={'paragraph-' + block.paragraph}
              data-word-heading={block.heading} data-source-tone={selected ? mode : undefined}
              ref={selected ? trackFocus : undefined}>
              {selected ? highlight(block.text) : block.text || '\u00a0'}
            </p>;
          }
          return <table key={'t' + block.table} aria-label={'Таблица ' + block.table}><tbody>
            {block.rows.map((cells, index) => <tr key={index}>{cells.map((cell) => {
              const selected = locator?.kind === 'table_cell' && locator.table === block.table
                && locator.row === index + 1 && locator.cell >= cell.column && locator.cell < cell.column + cell.span;
              return <td key={cell.column} colSpan={cell.span}
                data-source-address={`table-${block.table}-${index + 1}-${cell.column}`}
                data-source-tone={selected ? mode : undefined}
                ref={selected ? trackFocus : undefined}>
                {selected ? highlight(cell.text) : cell.text}
              </td>;
            })}</tr>)}
          </tbody></table>;
        })}
        {!matchingPreview.blocks.length && <p>В документе нет читаемого текста или таблиц.</p>}
        {matchingPreview.truncated && <p>Показана часть документа. Полный файл доступен для скачивания.</p>}
      </article>
    </div>
  </div>;
}