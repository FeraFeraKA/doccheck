import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode, RefObject } from 'react';
import { getOfficePreview } from './documentPreviewApi';
import type { OfficePreview } from './documentPreviewApi';
import { getSourceFragmentPreview } from './sourceApi';
import type { SourceEvidence } from './sourceApi';
import { strongestTone } from './sourceHighlights';
import type { SourceHighlight, SourceTone } from './sourceHighlights';
import { ReaderArrow } from './ReaderArrow';
import './document-reader.css';

type Locator = SourceEvidence['locator'];
type Fragment = Awaited<ReturnType<typeof getSourceFragmentPreview>>;
type Window = { sheet?: string; row: number; column: number };
type Sheet = Extract<OfficePreview, { sheets: string[] }>;

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

function rangeBounds(range: string) {
  const [first, last = first] = range.split(':');
  return { first: cellPosition(first), last: cellPosition(last) };
}

function sheetTones(preview: Sheet, highlights: readonly SourceHighlight[]) {
  const tones = preview.rows.map((cells) => new Array<SourceTone | undefined>(cells.length));
  for (const { locator, tone } of highlights) {
    if (!('sheet' in locator) || locator.sheet !== preview.sheet) continue;
    const { first, last } = rangeBounds(locator.range);
    const lastRow = Math.min(tones.length - 1, last.row - preview.row);
    for (let row = Math.max(0, first.row - preview.row); row <= lastRow; row++) {
      const lastColumn = Math.min(tones[row].length - 1, last.column - preview.column);
      for (let column = Math.max(0, first.column - preview.column); column <= lastColumn; column++) {
        tones[row][column] = strongestTone(tones[row][column], tone);
      }
    }
  }
  return tones;
}

function wordTones(highlights: readonly SourceHighlight[]) {
  const paragraphs = new Map<number, SourceTone>();
  const tables = new Map<string, Map<number, SourceTone>>();
  for (const { locator, tone } of highlights) {
    if ('paragraph' in locator) {
      const preferred = strongestTone(paragraphs.get(locator.paragraph), tone);
      if (preferred) paragraphs.set(locator.paragraph, preferred);
    } else if ('table' in locator) {
      const id = locator.table + ':' + locator.row;
      const row = tables.get(id) ?? new Map<number, SourceTone>();
      const preferred = strongestTone(row.get(locator.cell), tone);
      if (preferred) row.set(locator.cell, preferred);
      tables.set(id, row);
    }
  }
  return { paragraphs, tables };
}

function cellTone(tones: ReadonlyMap<number, SourceTone> | undefined, column: number, span: number) {
  if (span === 1 || !tones) return tones?.get(column);
  let preferred: SourceTone | undefined;
  for (const [address, tone] of tones) {
    if (address >= column && address < column + span) preferred = strongestTone(preferred, tone);
  }
  return preferred;
}

function centerCell(scroller: RefObject<HTMLDivElement | null>, focus: RefObject<HTMLElement | null>,
  preview: OfficePreview | undefined | null, locator: Locator | undefined, active: boolean) {
  const target = focus.current;
  const container = scroller.current;
  if (!preview || !active || !target || !container) return;
  const from = container.getBoundingClientRect();
  const to = target.getBoundingClientRect();
  if (container.clientWidth === 0 || container.clientHeight === 0) return;
  container.scrollTop += to.top + to.height / 2 - from.top - container.clientHeight / 2;
  container.scrollLeft += to.left + to.width / 2 - from.left - container.clientWidth / 2;
  return { locator, preview };
}

export function OfficeReader({ runId, documentId, format, locator, evidenceId, tone, highlights, active, fallback }: {
  runId: string;
  documentId: string;
  format: 'xlsx' | 'docx';
  locator?: Locator;
  evidenceId: string | null;
  tone?: SourceTone;
  highlights: readonly SourceHighlight[];
  active: boolean;
  fallback: ReactNode;
}) {
  const [attempt, setAttempt] = useState(0);
  const [windowChoice, setWindowChoice] = useState<Window>();
  const [documentState, setDocumentState] = useState<{
    request: string; preview: OfficePreview | null; lastSheet?: Sheet;
  }>();
  const [textState, setTextState] = useState<{ id: string; fragment: Fragment }>();
  const [selectedId, setSelectedId] = useState(evidenceId);
  if (selectedId !== evidenceId) {
    setSelectedId(evidenceId);
    setWindowChoice(undefined);
  }
  const manualWindow = selectedId === evidenceId ? windowChoice : undefined;
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
  const visibleSheetData = documentState?.lastSheet;
  const sheetEvidence = useMemo(() => visibleSheetData && sheetTones(visibleSheetData, highlights),
    [visibleSheetData, highlights]);
  const wordEvidence = useMemo(() => format === 'docx' ? wordTones(highlights) : undefined,
    [format, highlights]);
  const focus = useRef<HTMLElement | null>(null);
  function trackFocus(node: HTMLElement | null) { focus.current = node; }
  const scroller = useRef<HTMLDivElement>(null);
  const centered = useRef<{ locator?: Locator; preview: OfficePreview }>(undefined);

  useEffect(() => {
    const abort = new AbortController();
    void getOfficePreview(runId, documentId, new URLSearchParams(query), abort.signal).then(
      (value) => {
        if (!abort.signal.aborted) setDocumentState({
          request, preview: value, lastSheet: 'sheets' in value ? value : undefined,
        });
      },
      () => {
        if (!abort.signal.aborted) setDocumentState((last) => ({
          request, preview: null, lastSheet: last?.lastSheet,
        }));
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
    if (manualWindow || (centered.current?.preview === preview && centered.current?.locator === locator)) return;
    if (!locator) {
      if (scroller.current && centered.current?.locator) {
        scroller.current.scrollTop = 0;
        scroller.current.scrollLeft = 0;
      }
      centered.current = undefined;
      return;
    }
    const centeredView = centerCell(scroller, focus, preview, locator, active);
    if (centeredView) centered.current = centeredView;
  }, [active, locator, manualWindow, preview]);

  const matchingPreview = preview && (format === 'xlsx' ? 'sheets' in preview : 'blocks' in preview) ? preview : null;
  const pending = <div className="source-viewer-placeholder"><p role="status">Чтение документа…</p></div>;
  const failure = <div className="source-viewer-placeholder">
    <p role="alert">Не удалось открыть предпросмотр. Оригинал можно скачать.</p>
    <button type="button" onClick={() => setAttempt((current) => current + 1)}>Повторить предпросмотр</button>
    {fallback}
  </div>;

  function highlight(text: string, singleSheetCell = false) {
    // Exact single-cell evidence preserves the original text (for example, 60.250).
    if (!fragment?.match || (fragment.text !== text && !singleSheetCell)) return text;
    const [before, match, after] = fragment.match;
    return <>{before}<mark>{match}</mark>{after}</>;
  }

  if (format === 'xlsx' && visibleSheetData) {
    const { sheet, sheets, row, column, last_row, last_column, rows } = visibleSheetData;
    const columns = rows[0].length;
    const bounds = locator?.kind === 'sheet' && locator.sheet === sheet ? rangeBounds(locator.range) : undefined;
    const singleCell = !!bounds && bounds.first.row === bounds.last.row
      && bounds.first.column === bounds.last.column;
    const visibleSheet = viewing.sheet && sheets.includes(viewing.sheet) ? viewing.sheet : sheet;
    function pageRow(delta: number) {
      const next = row + delta;
      if (matchingPreview && next <= last_row && (delta > 0 || row > 1)) {
        setWindowChoice({ sheet, row: Math.max(1, next), column });
      }
    }
    function pageColumn(delta: number) {
      const next = column + delta;
      if (matchingPreview && next <= last_column && (delta > 0 || column > 1)) {
        setWindowChoice({ sheet, row, column: Math.max(1, next) });
      }
    }
    return <div className="document-reader">
      <div className="document-reader-controls">
        <label>Лист <select aria-label="Лист XLSX" value={visibleSheet}
          onChange={(event) => setWindowChoice({ sheet: event.currentTarget.value, row: 1, column: 1 })}>
          {sheets.map((title) => <option key={title}>{title}</option>)}
        </select></label>
        <div className="document-reader-paging" role="group" aria-label="Область листа">
          <div className="reader-range">
            <ReaderArrow label="Предыдущие строки" direction="left" edge={row === 1}
              unavailable={!matchingPreview || row === 1} onNavigate={() => pageRow(-rows.length)} />
            <span aria-live="polite">Строки {row}–{row + rows.length - 1} из {last_row}</span>
            <ReaderArrow label="Следующие строки" direction="right" edge={row + rows.length > last_row}
              unavailable={!matchingPreview || row + rows.length > last_row}
              onNavigate={() => pageRow(rows.length)} />
          </div>
          <div className="reader-range">
            <ReaderArrow label="Предыдущие столбцы" direction="left" edge={column === 1}
              unavailable={!matchingPreview || column === 1} onNavigate={() => pageColumn(-columns)} />
            <span>Столбцы {columnName(column)}–{columnName(column + columns - 1)}</span>
            <ReaderArrow label="Следующие столбцы" direction="right" edge={column + columns > last_column}
              unavailable={!matchingPreview || column + columns > last_column}
              onNavigate={() => pageColumn(columns)} />
          </div>
        </div>
        {locator?.kind === 'sheet' && <button className="reader-source-jump" type="button"
          tabIndex={manualWindow ? undefined : -1}
          aria-disabled={!manualWindow} onClick={() => {
            if (!manualWindow) return;
            centered.current = undefined;
            setWindowChoice(undefined);
          }}>К источнику</button>}
      </div>
      {matchingPreview
        ? <div ref={scroller} className="document-reader-scroll" tabIndex={0} aria-label={'Лист «' + sheet + '»'} role="region">
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
              const background = sheetEvidence?.[index]?.[offset];
              const markTone = selected ? strongestTone(background, tone) ?? 'source' : background;
              return <td key={current} title={address} data-source-address={address}
                ref={first ? trackFocus : undefined}
                data-source-active={selected ? 'true' : undefined} data-source-tone={markTone}>
                {selected ? highlight(text, singleCell) : text}
              </td>;
            })}</tr>;
          })}</tbody>
        </table>
        </div>
        : preview === undefined ? pending : failure}
    </div>;
  }

  if (preview === undefined) return pending;
  if (!matchingPreview || !('blocks' in matchingPreview)) return failure;

  return <div className="document-reader">
    <div ref={scroller} className="document-reader-scroll" tabIndex={0} aria-label="Содержимое DOCX" role="region">
      <article className="document-reader-word">
        {matchingPreview.blocks.map((block) => {
          if ('paragraph' in block) {
            const selected = locator?.kind === 'paragraph' && locator.paragraph === block.paragraph;
            const background = wordEvidence?.paragraphs.get(block.paragraph);
            return <p key={'p' + block.paragraph} data-source-address={'paragraph-' + block.paragraph}
              data-word-heading={block.heading} data-source-active={selected ? 'true' : undefined}
              data-source-tone={selected ? strongestTone(background, tone) ?? 'source' : background}
              ref={selected ? trackFocus : undefined}>
              {selected ? highlight(block.text) : block.text || '\u00a0'}
            </p>;
          }
          return <table key={'t' + block.table} aria-label={'Таблица ' + block.table}><tbody>
            {block.rows.map((cells, index) => <tr key={index}>{cells.map((cell) => {
              const selected = locator?.kind === 'table_cell' && locator.table === block.table
                && locator.row === index + 1 && locator.cell >= cell.column && locator.cell < cell.column + cell.span;
              const background = cellTone(wordEvidence?.tables.get(block.table + ':' + (index + 1)), cell.column, cell.span);
              return <td key={cell.column} colSpan={cell.span}
                data-source-address={`table-${block.table}-${index + 1}-${cell.column}`}
                data-source-active={selected ? 'true' : undefined}
                data-source-tone={selected ? strongestTone(background, tone) ?? 'source' : background}
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
