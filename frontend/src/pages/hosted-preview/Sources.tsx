import { useEffect, useState } from 'react';

import { formatLocation } from '../checks/reviewResult';

type Source = { id: string; document_id: string; locator?: unknown };
type Original = { id: string; name: string };
type SourcePreview =
  | { status: 'available'; path: string; text: string | null; highlight: unknown }
  | { status: 'missing' }
  | { status: 'failed' };
type OpenSource = { name: string; preview: SourcePreview };

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function index(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

function bbox(value: unknown): value is [number, number, number, number] {
  return Array.isArray(value) && value.length === 4
    && value.every((coordinate: unknown) => typeof coordinate === 'number'
      && coordinate >= 0 && coordinate <= 1)
    && value[0] < value[2] && value[1] < value[3];
}

function SourceAddress({ locator }: { locator: unknown }) {
  if (!record(locator) || locator.kind !== 'page' || !index(locator.page)) return null;
  const { page, bbox: box, line, table_row, table_column, fragment_id } = locator;
  if ((box != null && !bbox(box)) || (line != null && !index(line))
      || (table_row == null ? table_column != null : !index(table_row) || !index(table_column))
      || (fragment_id != null && (typeof fragment_id !== 'string' || !fragment_id.trim()))
      || (box == null && line == null && table_row == null && fragment_id == null)) return null;
  const address = formatLocation({
    page,
    line: index(line) ? line : null,
    table_row: index(table_row) ? table_row : null,
    table_column: index(table_column) ? table_column : null,
    fragment_id: typeof fragment_id === 'string' ? fragment_id : null,
  });
  return (
    <p>
      <strong>Адрес источника</strong>{' '}{address}
      {bbox(box) && <> · Координаты фрагмента: {box.join(', ')}</>}
    </p>
  );
}

function resultSources(value: unknown): { evidence: Source[]; documents: Original[] } {
  if (!record(value) || value.synthetic !== true || !Array.isArray(value.evidence)
      || !Array.isArray(value.documents)) throw new Error();
  const evidence = value.evidence.filter((item: unknown): item is Source =>
    record(item) && typeof item.id === 'string' && typeof item.document_id === 'string');
  const documents = value.documents.filter((item: unknown): item is Original =>
    record(item) && typeof item.id === 'string' && typeof item.name === 'string');
  return { evidence, documents };
}

function PreviewText({ text, highlight }: { text: string; highlight: unknown }) {
  if (!record(highlight) || typeof highlight.start_byte !== 'number'
      || typeof highlight.end_byte !== 'number') return <p>{text}</p>;
  const { start_byte: start, end_byte: end } = highlight;
  const bytes = new TextEncoder().encode(text);
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end)
      || start < 0 || start >= end || end > bytes.length) return <p>{text}</p>;
  const decoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });
  let before: string;
  let inside: string;
  let after: string;
  try {
    before = decoder.decode(bytes.slice(0, start));
    inside = decoder.decode(bytes.slice(start, end));
    after = decoder.decode(bytes.slice(end));
  } catch {
    return <p>{text}</p>;
  }
  return <p>{before}<mark>{inside}</mark>{after}</p>;
}

async function read(path: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(path, { signal, cache: 'no-store', redirect: 'error' });
  if (!response.ok) throw new Error();
  return response.json();
}

async function readPreview(path: string, evidenceId: string, signal: AbortSignal): Promise<SourcePreview> {
  const query = new URLSearchParams({ evidence_id: evidenceId });
  const response = await fetch(path + '/fragment-preview?' + query, {
    signal, cache: 'no-store', redirect: 'error',
  });
  if (!response.ok && response.status !== 404) return { status: 'failed' };
  const payload: unknown = await response.json();
  if (!record(payload)) return { status: 'failed' };
  if (response.status === 404) {
    return { status: payload.code === 'document_not_found' ? 'missing' : 'failed' };
  }
  if ((payload.text !== null && typeof payload.text !== 'string')
      || !Object.hasOwn(payload, 'highlight')) return { status: 'failed' };
  return { status: 'available', path, text: payload.text, highlight: payload.highlight };
}

export function Sources({ runPath }: { runPath: string }) {
  const [sources, setSources] = useState<ReturnType<typeof resultSources> | null>(null);
  const [selection, setSelection] = useState<{ source: Source } | null>(null);
  const [opened, setOpened] = useState<OpenSource | null>(null);
  const [failure, setFailure] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void read(runPath + '/findings', controller.signal)
      .then(resultSources)
      .then((value) => { if (!controller.signal.aborted) setSources(value); })
      .catch(() => { if (!controller.signal.aborted) setFailure(true); });
    return () => controller.abort();
  }, [runPath]);

  useEffect(() => {
    if (!selection || !sources) return;
    const { source } = selection;
    const document = sources.documents.find(({ id }) => id === source.document_id);
    if (!document) return;
    const controller = new AbortController();
    const path = runPath + '/documents/' + encodeURIComponent(document.id);
    void readPreview(path, source.id, controller.signal)
      .then((preview) => {
        if (!controller.signal.aborted) setOpened({ name: document.name, preview });
      })
      .catch(() => {
        if (!controller.signal.aborted) setOpened({ name: document.name, preview: { status: 'failed' } });
      });
    return () => controller.abort();
  }, [runPath, selection, sources]);

  if (failure) return <p role="alert">Не удалось открыть источники этой проверки.</p>;
  if (!sources) return <p role="status">Загружаем источники…</p>;
  return (
    <section className="preview-sources" aria-label="Источники проверки">
      {sources.evidence.length === 0 && <p>Адресных доказательств нет.</p>}
      {sources.evidence.map((source, index) => {
        const document = sources.documents.find(({ id }) => id === source.document_id);
        if (!document) return null;
        return (
          <button type="button" key={source.id} aria-pressed={selection?.source.id === source.id} onClick={() => {
            setOpened(null);
            setSelection({ source });
          }}>
            {document.name} · фрагмент {index + 1}
          </button>
        );
      })}
      {selection && !opened && <p role="status">Загружаем фрагмент…</p>}
      {opened && (
        <section aria-label={opened.name}>
          {opened.preview.status === 'missing' && <p role="status">Оригинал недоступен.</p>}
          {opened.preview.status === 'failed' && (
            <p role="alert">Не удалось загрузить фрагмент. Выберите его ещё раз.</p>
          )}
          {opened.preview.status === 'available' && (
            <>
              {opened.preview.text === null
                ? <p role="status">У оригинала нет доступного текстового фрагмента.</p>
                : <PreviewText text={opened.preview.text} highlight={opened.preview.highlight} />}
              <SourceAddress locator={selection?.source.locator} />
              <a href={opened.preview.path}>Скачать оригинал</a>
            </>
          )}
        </section>
      )}
    </section>
  );
}
