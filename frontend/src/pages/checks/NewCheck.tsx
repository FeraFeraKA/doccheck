import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { Button } from '../../shared/ui/Button';
import type { CheckHistory } from './checkData';
import { prepareRunTransfer, RunUploadHttpError, startPreparedRun } from './createRun';
import type { ScanScope } from './createRun';
import { RunProgressBar } from './RunProgressBar';
import { RunQueue } from './RunQueue';
import type { QueueReceipt } from './RunQueue';
import { runQueuePath } from './runTitle';
import { uploadFileInfo, UploadFileList, UploadSpinner } from './UploadFiles';
import type { UploadFile } from './UploadFiles';
import { usePreparedRun } from './usePreparedRun';
import { useRunHistory } from './useRunHistory';
import { formats, useRunUploadFiles } from './useRunUploadFiles';
import type { FileGroup, InitialRunPack } from './useRunUploadFiles';
import { WorkspaceIcon } from './WorkspaceIcon';

export type { RetainedDocument } from './createRun';
export type { InitialRunPack } from './useRunUploadFiles';

const initialScanScope: ScanScope = {
  contractNumber: '', periodStart: '', periodEnd: '', page: NaN, stage: NaN,
};

function validScanScope(scope: ScanScope) {
  return scope.contractNumber.trim().length > 0
    && /^\d{4}-\d{2}-\d{2}$/.test(scope.periodStart)
    && /^\d{4}-\d{2}-\d{2}$/.test(scope.periodEnd)
    && scope.periodStart <= scope.periodEnd
    && scope.periodStart.slice(0, 4) === scope.periodEnd.slice(0, 4)
    && Number.isInteger(scope.page) && scope.page >= 1 && scope.page <= 12
    && Number.isSafeInteger(scope.stage) && scope.stage >= 1;
}

function uploadErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof RunUploadHttpError) {
    if (error.status === 413) return 'Пакет превышает предел загрузки.';
    if (error.status < 500 && error.details) return error.details.message;
  }
  return fallback;
}

function readyPacket(
  report: UploadFile[], documents: UploadFile[], initialPack?: InitialRunPack, scanScope?: ScanScope,
): Parameters<typeof prepareRunTransfer>[0] | null {
  if (report.length !== 1 || documents.length === 0) return null;
  const items = [...report, ...documents];
  if (items.some((item) => 'file' in item && item.state !== 'ready')) return null;
  const reportFile = 'file' in report[0] ? report[0].file : undefined;
  const documentFiles = documents.flatMap((item) => 'file' in item ? [item.file] : []);
  const scope = scanScope ? { scanScope: { ...scanScope, contractNumber: scanScope.contractNumber.trim() } } : {};
  if (!initialPack) return reportFile ? { report: reportFile, documents: documentFiles, ...scope } : null;
  const retainedDocumentIds = items.flatMap((item) => 'retained' in item ? [item.retained.id] : []);
  if (retainedDocumentIds.length === initialPack.documents.length && !reportFile && !documentFiles.length && !scanScope) return null;
  return {
    report: reportFile,
    documents: documentFiles,
    sourceRunId: initialPack.runId,
    retainedDocumentIds,
    ...scope,
  };
}

function transferLabel(reading: boolean, percent: number | undefined, starting: boolean) {
  if (starting) return 'Запуск проверки…';
  if (percent !== undefined) return percent === 100 ? 'Ожидаем подтверждения загрузки…' : 'Загрузка файлов…';
  if (reading) return 'Чтение файлов…';
  return '';
}

const publicDemo = import.meta.env.VITE_DOCCHECK_PUBLIC_DEMO === '1';

export function RunPackHeading({ runId, reportName }: { runId: string; reportName?: string }) {
  return <>
    <Link to={'/checks/' + encodeURIComponent(runId)}>К результату</Link>
    <h1 className="wrap-anywhere">Изменение комплекта{reportName && ' · ' + reportName}</h1>
    <p className="upload-intro">Замените КФЗ или обновите первичные документы. Исходная проверка сохранится.</p>
  </>;
}

export function NewCheck({ initialPack }: { initialPack?: InitialRunPack } = {}) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const manualScope = initialPack !== undefined && params.get('scope') === 'manual';
  const submitButton = useRef<HTMLButtonElement>(null);
  const chooseReport = useRef<HTMLButtonElement>(null);
  const restoreUploadFocus = useRef(false);
  const [announceAccepted, setAnnounceAccepted] = useState(false);
  const [receipts, setReceipts] = useState<QueueReceipt[]>([]);
  const clearListedReceipts = useCallback(({ entries }: CheckHistory) => {
    const listed = new Set(entries.map(({ id }) => id));
    setReceipts((previous) => previous.filter(({ id }) => !listed.has(id)));
  }, []);
  const history = useRunHistory({ enabled: !publicDemo && !initialPack, onPage: clearListedReceipts });
  const active = useRef<AbortController | null>(null);
  const { report, documents, errors, withinLimits, takeFiles, removeFile, clearFiles } = useRunUploadFiles(initialPack);
  const [submitError, setSubmitError] = useState('');
  const [starting, setStarting] = useState(false);
  const [scanScope, setScanScope] = useState(initialScanScope);
  const requireScanScope = manualScope && report.length === 1 && /\.(pdf|png)$/i.test(uploadFileInfo(report[0]).name);
  const packet = useMemo(() => {
    if (publicDemo || !withinLimits || (requireScanScope && !validScanScope(scanScope))) return null;
    return readyPacket(report, documents, initialPack, requireScanScope ? scanScope : undefined);
  }, [report, documents, initialPack, withinLimits, requireScanScope, scanScope]);
  const prepared = usePreparedRun(packet);
  const transfer = prepared.state?.phase === 'uploading' ? prepared.state : null;
  const ready = prepared.state?.phase === 'ready';
  const reading = [...report, ...documents].some((item) => 'file' in item && item.state === 'reading');
  const status = transferLabel(reading, transfer?.percent, starting);
  const transferError = prepared.state?.phase === 'failed'
    ? uploadErrorMessage(prepared.state.error, 'Не удалось подтвердить приём пакета.') : '';

  useEffect(() => () => active.current?.abort(), []);

  function selectionChanged(group: FileGroup) {
    if (group === 'report') setScanScope(initialScanScope);
    setAnnounceAccepted(false);
    setSubmitError('');
  }

  function updateScope(values: Partial<ScanScope>) {
    setSubmitError('');
    setScanScope((previous) => ({ ...previous, ...values }));
  }

  function chooseFiles(incoming: FileList, group: FileGroup, replaceId?: string) {
    if (active.current) return;
    if (takeFiles(incoming, group, replaceId)) selectionChanged(group);
  }

  function removeSelectedFile(group: FileGroup, id: string) {
    if (active.current) return;
    removeFile(group, id);
    selectionChanged(group);
  }

  useEffect(() => {
    if (starting || !restoreUploadFocus.current) return;
    restoreUploadFocus.current = false;
    if (document.activeElement === document.body) chooseReport.current?.focus({ preventScroll: true });
  }, [starting]);

  async function submit() {
    if (publicDemo || active.current || !ready) return;
    const uploadId = prepared.start();
    if (!uploadId) return;
    const controller = new AbortController();
    active.current = controller;
    setAnnounceAccepted(false);
    setStarting(true);
    setSubmitError('');
    const submitHadFocus = document.activeElement === submitButton.current;
    try {
      const accepted = await startPreparedRun(uploadId, controller.signal);
      if (controller.signal.aborted) return;
      if (initialPack) {
        void navigate(runQueuePath(accepted.run_id), { replace: true });
        return;
      }
      const receipt = {
        id: accepted.run_id,
        documentCount: 1 + documents.length,
        reportName: uploadFileInfo(report[0]).name,
      };
      setReceipts((previous) => [receipt, ...previous.filter(({ id }) => id !== receipt.id)].slice(0, 20));
      history.refresh();
      setAnnounceAccepted(true);
      restoreUploadFocus.current = submitHadFocus;
      clearFiles();
      if (manualScope) {
        setScanScope(initialScanScope);
        void navigate('/checks/new#queue', { replace: true });
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof RunUploadHttpError && (error.status === 404 || error.status === 410)) {
        prepared.replaceExpired(uploadId);
      } else {
        setSubmitError(uploadErrorMessage(error, 'Не удалось подтвердить запуск. Попробуйте ещё раз.'));
      }
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setStarting(false);
    }
  }

  return (
    <div className="upload-page">
      {initialPack ? <RunPackHeading runId={initialPack.runId}
        reportName={initialPack.documents.find((item) => item.role === 'report')?.name} /> : <>
        <h1>Новая проверка</h1>
        {!publicDemo && <p className="upload-intro">Добавьте КФЗ и первичные документы.</p>}
      </>}
      {publicDemo ? (
        <section className="upload-card upload-public-notice mt-6">
          <h2>Загрузка доступна в локальной установке</h2>
        </section>
      ) : (
        <>
          <div className="mt-6 grid grid-cols-1 items-start gap-5 md:grid-cols-2">
            <UploadBlock chooseButton={chooseReport} group="report" files={report} error={errors.report} disabled={starting}
              transferring={Boolean(transfer)} onFiles={chooseFiles} onRemove={(id) => removeSelectedFile('report', id)} />
            <UploadBlock group="documents" files={documents} error={errors.documents} disabled={starting}
              transferring={Boolean(transfer)} onFiles={chooseFiles} onRemove={(id) => removeSelectedFile('documents', id)}
              onReplace={initialPack ? (files, id) => chooseFiles(files, 'documents', id) : undefined} />
          </div>
          {requireScanScope && <fieldset className="upload-card mt-6" disabled={starting}>
            <legend className="px-2">Строка КФЗ</legend>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <label className="grid gap-1">Номер договора
                <input className="rounded border p-2" value={scanScope.contractNumber}
                  onChange={(event) => updateScope({ contractNumber: event.currentTarget.value })} />
              </label>
              <label className="grid gap-1">Начало периода
                <input className="rounded border p-2" type="date" value={scanScope.periodStart}
                  onChange={(event) => updateScope({ periodStart: event.currentTarget.value })} />
              </label>
              <label className="grid gap-1">Конец периода
                <input className="rounded border p-2" type="date" value={scanScope.periodEnd}
                  onChange={(event) => updateScope({ periodEnd: event.currentTarget.value })} />
              </label>
              <label className="grid gap-1">Этап
                <input className="rounded border p-2" type="number" min={1} value={scanScope.stage || ''}
                  onChange={(event) => updateScope({ stage: event.currentTarget.valueAsNumber })} />
              </label>
              <label className="grid gap-1">Страница
                <input className="rounded border p-2" type="number" min={1} max={12}
                  value={scanScope.page || ''}
                  onChange={(event) => updateScope({ page: event.currentTarget.valueAsNumber })} />
              </label>
            </div>
          </fieldset>}
          <div className="upload-navigation mt-5 flex flex-wrap items-center gap-3">
            <Button ref={submitButton} disabled={starting || !ready} onClick={() => { void submit(); }}>
              {initialPack ? 'Запустить повторную проверку' : 'Запустить проверку'} <WorkspaceIcon name="arrow" size={17} />
            </Button>
            <p role="status" className={status || ready ? 'upload-transfer' : 'sr-only'}>
              {status && <UploadSpinner />}
              {status || (ready && 'Пакет загружен') || (announceAccepted && 'Проверка поставлена в очередь.')}
            </p>
          </div>
          {transfer && <div className="upload-transfer-progress">
            <RunProgressBar label="Загрузка пакета" value={transfer.percent} valueText={`${transfer.percent}%. ${status}`} />
            <span aria-hidden="true" className="tabular-nums">{transfer.percent}%</span>
          </div>}
          {transferError && <div className="upload-validation">
            <p role="alert">{transferError}</p>
            <button type="button" onClick={prepared.retry}>Повторить загрузку</button>
          </div>}
          {submitError && !transfer && !transferError && <p className="upload-validation" role="alert">{submitError}</p>}
          {!initialPack && <RunQueue entries={history.page?.entries} receipts={receipts}
            loading={history.loading} error={history.error} onRetry={history.refresh} />}
        </>
      )}
    </div>
  );
}

function UploadBlock({ group, files, error, disabled, transferring, chooseButton, onFiles, onRemove, onReplace }: {
  group: FileGroup;
  files: UploadFile[];
  error: string;
  disabled: boolean;
  transferring: boolean;
  chooseButton?: React.Ref<HTMLButtonElement>;
  onFiles: (files: FileList, group: FileGroup) => void;
  onRemove: (id: string) => void;
  onReplace?: (files: FileList, id: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const replacement = useRef<HTMLInputElement>(null);
  const replacedId = useRef<string | null>(null);
  const [over, setOver] = useState(false);
  const report = group === 'report';
  const label = report ? 'КФЗ' : 'Первичные документы';

  return (
    <section aria-label={label} className={classes('upload-card min-w-0', over && !disabled && 'is-dragging')}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={(event) => {
        if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
          setOver(false);
        }
      }}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        onFiles(event.dataTransfer.files, group);
      }}>
      <header className="upload-card-header">
        <div>
          <h2>{label}</h2>
          <p>{report ? 'Один файл PDF, DOCX, XLSX или PNG' : 'PDF, DOCX, XLSX, PNG'}</p>
        </div>
      </header>
      <input ref={input} type="file" hidden
        aria-label={report ? 'Выберите КФЗ' : 'Выберите первичные документы'}
        accept={formats.join(',')} multiple={!report} disabled={disabled}
        onChange={(event) => {
          if (event.currentTarget.files) onFiles(event.currentTarget.files, group);
          event.currentTarget.value = '';
        }} />
      {onReplace && <input ref={replacement} type="file" hidden
        aria-label="Выберите замену первичного документа" accept={formats.join(',')} disabled={disabled}
        onChange={(event) => {
          const id = replacedId.current;
          replacedId.current = null;
          if (id && event.currentTarget.files) onReplace(event.currentTarget.files, id);
          event.currentTarget.value = '';
        }} />}
      {files.length === 0 ? <div className="upload-empty">
        <WorkspaceIcon name="file" size={28} />
        <p>{report ? 'Перетащите КФЗ сюда' : 'Перетащите документы сюда'}</p>
        <Button ref={chooseButton} variant="outline" disabled={disabled} onClick={() => input.current?.click()}>
          {report ? 'Выбрать файл' : 'Выбрать файлы'}
        </Button>
      </div> : <>
        <UploadFileList files={files} disabled={disabled} transferring={transferring} onRemove={onRemove}
          onReplace={onReplace ? (id) => {
            replacedId.current = id;
            replacement.current?.click();
          } : undefined} />
        <div className="upload-list-actions mt-3">
          <button type="button" disabled={disabled} onClick={() => input.current?.click()}>
            <WorkspaceIcon name="plus" size={16} />
            {report ? 'Заменить КФЗ' : 'Добавить документы'}
          </button>
          <span>Файлов: {files.length}</span>
        </div>
      </>}
      {error && <p className="upload-validation" role="alert">{error}</p>}
    </section>
  );
}
