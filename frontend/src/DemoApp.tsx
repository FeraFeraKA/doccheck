import { useEffect, useRef, useState } from 'react';
import type { ReactNode, KeyboardEvent } from 'react';
import { ArrowRight, Check, CheckCircle2, ChevronRight, CircleAlert, CircleHelp, Copy, Download, ExternalLink, FileCheck2, FileJson, FileText, Files, LoaderCircle, Minus, Moon, Plus, Printer, Sun, X } from 'lucide-react';
import { demoFindings, scope } from './demo/fixture';
import { demoHtml, demoJson, downloadFile } from './demo/export';
import { filterFindings, money, statusLabels } from './presentation';
import type { DemoRun, Finding, FindingStatus, SourcePreview } from './presentation';

const statusIcons = { verified: CheckCircle2, discrepancy: CircleAlert, unverified: CircleHelp };
const initialRun: DemoRun = { id: 'DEMO-001', createdAt: '2026-11-11T19:00:00Z', status: 'completed_with_issues' };

function Badge({ status }: { status: FindingStatus }) {
  const Icon = statusIcons[status];
  return <span className={`badge badge--${status}`}><Icon aria-hidden="true" />{statusLabels[status]}</span>;
}

function Dialog({ open, onClose, title, children, drawer = false }: { open: boolean; onClose: () => void; title: string; children: ReactNode; drawer?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (open && !dialog?.open) dialog?.showModal();
    if (!open && dialog?.open) dialog.close();
  }, [open]);
  return <dialog ref={ref} className={drawer ? 'drawer' : 'modal'} aria-label={title} onCancel={onClose} onClose={onClose} onClick={event => { if (event.target === event.currentTarget) { const box = event.currentTarget.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) onClose(); } }}>
    <div className={drawer ? 'drawer-header' : 'modal-header'}><h2>{title}</h2><button className="icon-btn" onClick={onClose} aria-label="Закрыть"><X /></button></div>
    {children}
  </dialog>;
}

function Viewer({ source }: { source: SourcePreview | undefined }) {
  const [zoom, setZoom] = useState(100);
  useEffect(() => { setZoom(100); }, [source?.id]);
  return <section className="panel viewer-panel" aria-label="Источник">
    <div className="viewer-heading"><h2>Источник</h2></div>
    {source ? <>
      <div className="viewer-toolbar"><span className="file-chip"><FileText aria-hidden="true" />{source.filename}</span><div className="flex items-center gap-2"><span className="muted text-xs">Стр. {source.page} / 1</span><button className="icon-btn" aria-label="Уменьшить документ" disabled={zoom <= 75} onClick={() => setZoom(z => Math.max(75, z - 25))}><Minus /></button><output className="text-xs tabular-nums min-w-9 text-center" aria-live="polite">{zoom}%</output><button className="icon-btn" aria-label="Увеличить документ" disabled={zoom >= 175} onClick={() => setZoom(z => Math.min(175, z + 25))}><Plus /></button></div></div>
      <div className="viewer-canvas" tabIndex={0} aria-label="Превью страницы документа; прокрутка при увеличении">
        <div className="document-page" style={{ width: `${zoom}%`, maxWidth: `${420 * zoom / 100}px` }}>
          <img src={source.previewUrl} alt={`Синтетический документ ${source.filename}. Итог ${money(source.amount)} рублей.`} />
          <div className="evidence-box" role="img" aria-label={`Выделенный источник: ${money(source.amount)} рублей`} style={{ left: `${source.bbox[0] * 100}%`, top: `${source.bbox[1] * 100}%`, width: `${(source.bbox[2] - source.bbox[0]) * 100}%`, height: `${(source.bbox[3] - source.bbox[1]) * 100}%` }} />
        </div>
      </div>
      <div className="viewer-footer"><p>Выделен фрагмент, использованный в расчёте</p><a href={source.originalUrl} target="_blank" rel="noreferrer">Открыть оригинал <ExternalLink size={14} aria-hidden="true" /></a></div>
    </> : <div className="empty-state"><FileText size={36} aria-hidden="true" /><h3>Источник отсутствует</h3><p>Для этой строки нет подтверждающего документа.<br />Сумма остаётся непроверенной.</p></div>}
  </section>;
}

export default function DemoApp() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
  const [view, setView] = useState<'result' | 'history'>('result');
  const [filter, setFilter] = useState<FindingStatus | 'all'>('all');
  const [selectedId, setSelectedId] = useState('materials');
  const [tab, setTab] = useState<'sources' | 'excluded'>('sources');
  const [newOpen, setNewOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [runs, setRuns] = useState<DemoRun[]>([initialRun]);
  const [activeRunId, setActiveRunId] = useState(initialRun.id);
  const [announcement, setAnnouncement] = useState('');
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const run = runs.find(item => item.id === activeRunId)!;
  const busy = run.status !== 'completed_with_issues';
  const running = runs.some(item => item.status !== 'completed_with_issues');
  const visibleFindings = filterFindings(demoFindings, filter);
  const selected = demoFindings.find(item => item.id === selectedId)!;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0F172A' : '#F4F7F6');
    try { localStorage.setItem('doccheck-theme', theme); } catch { /* The UI works when storage is unavailable. */ }
  }, [theme]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  function handleTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'sources' : event.key === 'End' ? 'excluded' : tab === 'sources' ? 'excluded' : 'sources';
    setTab(next);
    document.getElementById(`${next}-tab`)?.focus();
  }
  function selectFinding(finding: Finding) { setSelectedId(finding.id); setTab('sources'); }
  function changeFilter(value: FindingStatus | 'all') {
    setFilter(value);
    const next = filterFindings(demoFindings, value);
    if (!next.some(item => item.id === selectedId) && next[0]) selectFinding(next[0]);
  }
  function openRun(item: DemoRun) { setActiveRunId(item.id); setView('result'); setFilter('all'); setSelectedId('materials'); setTab('sources'); }
  function startDemo() {
    if (running) return;
    const item: DemoRun = { id: `DEMO-${String(runs.length + 1).padStart(3, '0')}`, createdAt: new Date().toISOString(), status: 'queued' };
    setRuns(current => [item, ...current]); openRun(item); setNewOpen(false);
    setAnnouncement('Демонстрационная проверка в очереди.');
    timers.current.push(setTimeout(() => { setRuns(current => current.map(r => r.id === item.id ? { ...r, status: 'processing' } : r)); setAnnouncement('Демонстрация обработки документов.'); }, 650));
    timers.current.push(setTimeout(() => { setRuns(current => current.map(r => r.id === item.id ? { ...r, status: 'completed_with_issues' } : r)); setAnnouncement('Демонстрация завершена: одно расхождение, один непроверенный показатель.'); }, 2100));
  }
  function exportRun(format: 'json' | 'html') {
    downloadFile(`doccheck-${run.id}-demo.${format}`, format === 'json' ? demoJson(run, demoFindings) : demoHtml(run, demoFindings), format === 'json' ? 'application/json;charset=utf-8' : 'text/html;charset=utf-8');
    setExportOpen(false); setAnnouncement(`Синтетический отчёт ${format.toUpperCase()} подготовлен для скачивания.`);
  }

  return <>
    <a href="#main" className="sr-only focus:not-sr-only">К результатам проверки</a>
    <header className="app-header"><div className="header-inner">
      <button className="brand" onClick={() => setView('history')} aria-label="DocCheck — список проверок"><FileCheck2 className="brand-icon" aria-hidden="true" /><span>DocCheck</span></button>
      <span className="header-divider" /><button className="nav-link" aria-current={view === 'history' ? 'page' : undefined} onClick={() => setView('history')}>Проверки</button>
      <div className="ml-auto flex items-center gap-4"><div className="theme-toggle" role="group" aria-label="Тема интерфейса"><button aria-label="Светлая тема" aria-pressed={theme === 'light'} onClick={() => setTheme('light')}><Sun /></button><button aria-label="Тёмная тема" aria-pressed={theme === 'dark'} onClick={() => setTheme('dark')}><Moon /></button></div><button className="btn btn-primary" onClick={() => setNewOpen(true)}><Plus size={16} aria-hidden="true" /><span>Новая проверка</span></button></div>
    </div></header>
    <main id="main" className="page-shell">
      {view === 'history' ? <>
        <div className="page-titlebar"><div className="title-group"><h1>Проверки</h1><span className="demo-label">Демо · синтетические данные</span></div></div>
        <p className="muted mb-6">Демонстрационные запуски текущей сессии. После обновления страницы останется исходный пример.</p>
        <section className="panel history-list" aria-label="История проверок">{runs.map(item => <button className="history-item" key={item.id} onClick={() => openRun(item)}><FileCheck2 aria-hidden="true" /><span><strong>{item.id}</strong><span className="muted block text-sm">{scope.contract} · 01.11.2026 — 30.11.2026</span></span><span className="run-state ml-auto">{item.status === 'queued' ? 'В очереди' : item.status === 'processing' ? 'Обработка' : 'С замечаниями'}</span><ChevronRight size={18} aria-hidden="true" /></button>)}</section>
      </> : <>
        <nav className="breadcrumbs" aria-label="Навигация"><button onClick={() => setView('history')}>Проверки</button><span aria-hidden="true">/</span><span>{run.id}</span></nav>
        <div className="page-titlebar"><div className="title-group"><h1>Сверка затрат</h1><span className="run-state">{run.status === 'queued' ? 'В очереди' : run.status === 'processing' ? 'Обработка' : 'Завершено с замечаниями'}</span><span className="demo-label">Демо · синтетические данные</span></div><button className="btn btn-secondary" disabled={busy} onClick={() => setExportOpen(true)}><Download size={17} aria-hidden="true" />Экспорт</button></div>
        <section className="context-card" aria-label="Область проверки"><dl className="context-grid"><div className="meta-field"><dt>Договор</dt><dd>{scope.contract}</dd></div><div className="meta-field"><dt>Период</dt><dd>01.11.2026 — 30.11.2026</dd></div><div className="meta-field"><dt>Строка КФЗ</dt><dd>{scope.row}</dd></div></dl><div className="file-strip"><span className="file-chip"><FileText aria-hidden="true" />Отчёт: КФЗ_demo <span className="muted text-xs">(данные примера)</span></span><button className="file-chip" onClick={() => setFilesOpen(true)}><Files aria-hidden="true" />Первичные документы: 3 файла<ChevronRight size={14} /></button></div></section>
        {busy ? <section className="panel status-progress" aria-live="polite"><LoaderCircle className="animate-spin" size={32} aria-hidden="true" /><h2>{run.status === 'queued' ? 'Демонстрационная проверка в очереди' : 'Показываем процесс сверки'}</h2><p className="muted">Встроенный пример. Реальные документы не обрабатываются.</p><progress max={100} value={run.status === 'queued' ? 15 : 65} aria-label="Ход демонстрации" /></section> : <>
          <div className="summary-bar" aria-label="Сводка результатов"><strong className="summary-label">3 показателя</strong><span className="summary-item tone-verified"><CheckCircle2 size={17} aria-hidden="true" />1 подтверждён</span><span className="summary-item tone-discrepancy"><CircleAlert size={17} aria-hidden="true" />1 расхождение</span><span className="summary-item tone-unverified"><CircleHelp size={17} aria-hidden="true" />1 не проверен</span></div>
          <div className="workspace-grid">
            <section className="panel" aria-label="Результаты сверки">
              <div className="panel-heading"><h2>Результаты сверки</h2><select className="filter-select" aria-label="Фильтр статусов" value={filter} onChange={event => changeFilter(event.target.value as FindingStatus | 'all')}><option value="all">Все статусы</option><option value="discrepancy">Расхождения</option><option value="verified">Подтверждённые</option><option value="unverified">Не проверенные</option></select></div>
              <div className="table-scroll"><table className="results-table"><caption className="sr-only">Суммы по статьям, сравнение с документами и статус</caption><thead><tr><th scope="col">Статья</th><th scope="col" className="number">В отчёте, ₽</th><th scope="col" className="number">По документам, ₽</th><th scope="col" className="number">Разница, ₽</th><th scope="col">Статус</th></tr></thead><tbody>{visibleFindings.map(finding => <tr key={finding.id} className={selectedId === finding.id ? 'row-selected' : ''} onClick={() => selectFinding(finding)}><th scope="row"><button className="row-select" aria-pressed={selectedId === finding.id} onClick={() => selectFinding(finding)}>{finding.article}</button></th><td className="number">{money(finding.reported)}</td><td className="number">{money(finding.expected)}</td><td className={`number ${finding.status === 'discrepancy' ? 'tone-discrepancy' : ''}`}>{money(finding.delta, true)}</td><td><Badge status={finding.status} /></td></tr>)}</tbody></table></div>
              <p className="table-footnote">— нет данных, а не ноль</p>
              <div className="finding" aria-live="polite"><h3 className="finding-title">{selected.article}: {selected.status === 'discrepancy' ? <>расхождение <span className="tone-discrepancy">{money(selected.delta)} ₽</span></> : selected.status === 'verified' ? 'сумма подтверждена' : 'не хватает данных'}</h3><p className="finding-reason">{selected.explanation}</p>
                {selected.formula ? <div className="formula"><span className="formula-label">Расчёт</span><span className="formula-value">{selected.formula}</span></div> : <div className="notice"><CircleHelp size={18} aria-hidden="true" /><p>Нет документа — нет основания для сравнения. Пустые значения не заменяются нулём.</p></div>}
                <div className="tabs" role="tablist" aria-label="Документы выбранной строки"><button className="tab" id="sources-tab" role="tab" tabIndex={tab === 'sources' ? 0 : -1} onKeyDown={handleTabKey} aria-selected={tab === 'sources'} aria-controls="finding-documents" onClick={() => setTab('sources')}>Источники</button><button className="tab" id="excluded-tab" role="tab" tabIndex={tab === 'excluded' ? 0 : -1} onKeyDown={handleTabKey} aria-selected={tab === 'excluded'} aria-controls="finding-documents" onClick={() => setTab('excluded')}>Исключённые документы</button></div>
                <div id="finding-documents" role="tabpanel" aria-labelledby={tab === 'sources' ? 'sources-tab' : 'excluded-tab'} className="source-list">
                  {tab === 'sources' ? selected.sources.length ? selected.sources.map(source => <button className="source-link" key={source.id} onClick={() => document.querySelector('.viewer-panel')?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'nearest' })}><FileText size={19} aria-hidden="true" /><span className="source-name">{source.filename}</span><span className="muted">Стр. {source.page} · {money(source.amount)} ₽</span><ArrowRight size={18} aria-hidden="true" /></button>) : <p className="muted py-4">Подтверждающие документы не предоставлены.</p> : selected.id === 'materials' ? <div className="demo-file"><Copy size={18} aria-hidden="true" /><div><strong>Демо-акт № 01 (копия).pdf</strong><p className="muted">Дубликат первого акта. Сумма повторно не учтена.</p></div></div> : <p className="muted py-4">Для этой статьи нет исключённых документов.</p>}
                </div><p className="muted text-xs mt-4">Основание полноты: демо-манифест{selected.status === 'unverified' ? ' · комплект неполный' : ''}</p>
              </div>
            </section><Viewer source={selected.sources[0]} />
          </div>
        </>}
        <p className="page-footnote">Результат требует проверки человеком. Непроверенные показатели не считаются подтверждёнными.</p>
      </>}
      <div className="sr-only" role="status">{announcement}</div>
    </main>
    <Dialog open={newOpen} onClose={() => setNewOpen(false)} title="Новая проверка" drawer>
      <form onSubmit={event => { event.preventDefault(); startDemo(); }} className="flex flex-col min-h-0 flex-1">
        <div className="drawer-body"><span className="demo-label">Демонстрационный запуск</span><p className="muted mt-4 mb-6">Используется встроенный синтетический комплект. Ваши файлы не загружаются и не обрабатываются.</p>
          <label className="field">Договор<input value={scope.contract} readOnly /></label><div className="field-row"><label className="field">Начало периода<input type="date" value={scope.periodStart} readOnly /></label><label className="field">Конец периода<input type="date" value={scope.periodEnd} readOnly /></label></div><label className="field">Строка КФЗ<input value={scope.row} readOnly /></label>
          <h3 className="mt-8 mb-3 font-semibold">Отчёт КФЗ</h3><div className="demo-file"><FileText aria-hidden="true" /><div><strong>КФЗ_demo</strong><p className="muted">Значения из утверждённого макета</p></div><Check size={16} className="ml-auto tone-verified" /></div>
          <h3 className="mt-6 mb-3 font-semibold">Первичные документы</h3><div className="demo-file"><Files aria-hidden="true" /><div><strong>Два акта и одна копия</strong><p className="muted">Синтетические PDF, без реальных данных</p></div></div>
          <p className="notice mt-6">Параметры фиксированы для демо-комплекта. Загрузка своих документов появится после подключения обработки.</p>
        </div><div className="drawer-footer"><button type="button" className="btn btn-secondary" onClick={() => setNewOpen(false)}>Отмена</button><button type="submit" className="btn btn-primary" disabled={running}>{running ? 'Демо уже выполняется' : 'Запустить демо'}<ArrowRight size={16} /></button></div>
      </form>
    </Dialog>
    <Dialog open={exportOpen} onClose={() => setExportOpen(false)} title="Экспорт результата"><div className="modal-body"><p className="muted mb-6">Синтетический отчёт текущего демо-запуска. Экспорт включает все три показателя, независимо от фильтра.</p><div className="export-options"><button className="source-link" onClick={() => exportRun('json')}><FileJson aria-hidden="true" /><span><strong>JSON</strong><span className="muted block text-sm">Данные демо-интерфейса</span></span><Download size={18} /></button><button className="source-link" onClick={() => exportRun('html')}><Printer aria-hidden="true" /><span><strong>Печатный HTML</strong><span className="muted block text-sm">Открыть файл и распечатать из браузера</span></span><Download size={18} /></button></div></div></Dialog>
    <Dialog open={filesOpen} onClose={() => setFilesOpen(false)} title="Документы комплекта"><div className="modal-body"><p className="muted mb-6">Синтетические источники демонстрации.</p>{demoFindings.flatMap(f => f.sources).map(source => <a className="source-link mb-3" key={source.id} href={source.originalUrl} target="_blank" rel="noreferrer"><FileText size={18} /><span>{source.filename}</span><ExternalLink size={15} /></a>)}<div className="demo-file"><Copy size={18} /><div><strong>Демо-акт № 01 (копия).pdf</strong><p className="muted">Исключён: дубликат первого акта.</p></div></div><div className="notice mt-4"><CircleHelp size={18} /><p>Документ для статьи «Прочее» отсутствует.</p></div></div></Dialog>
  </>;
}
