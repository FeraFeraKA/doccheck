import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { Button } from '../../shared/ui/Button';
import { UploadFileList } from './UploadFiles';
import { WorkspaceIcon } from './WorkspaceIcon';
import { prepareRunUpload, RunUploadHttpError } from './createRun';
import type { ScanScope } from './createRun';
import { demoRunPath } from './demoData';
import { isRunId } from './runStatusApi';

type FileGroup = 'report' | 'documents';

const formats = ['.pdf', '.docx', '.xlsx', '.png'];
const mib = 1024 ** 2;
const maxFileSize = 50 * mib;
const maxPackageMiB = import.meta.env.VITE_DOCCHECK_PUBLIC_TUNNEL === '1' ? 90 : 250;
const maxPackageSize = maxPackageMiB * mib;
const maxDocuments = 100;

interface SelectedFile {
  id: number;
  file: File;
}

function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();

  // Random bytes remain available when randomUUID requires a secure context.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
}

function uploadErrorMessage(error: unknown): string {
  if (error instanceof RunUploadHttpError) {
    if (error.status === 413) return 'Пакет превышает предел загрузки.';
    if (error.status === 409) return 'Этот ключ уже использован для другого пакета. Измените выбор файлов перед отправкой.';
    if (error.status < 500 && error.details) return error.details.message;
  }
  return 'Не удалось подтвердить приём пакета. Повторите отправку с теми же файлами.';
}

const publicTrial = import.meta.env.VITE_DOCCHECK_PUBLIC_TRIAL === '1';
const publicDemo = publicTrial || import.meta.env.VITE_DOCCHECK_PUBLIC_DEMO === '1';

export function NewCheck() {
  const navigate = useNavigate();
  const nextFileId = useRef(0);
  const active = useRef<AbortController | null>(null);
  const attempt = useRef<ReturnType<typeof prepareRunUpload> | null>(null);
  const [report, setReport] = useState<SelectedFile[]>([]);
  const [documents, setDocuments] = useState<SelectedFile[]>([]);
  const [errors, setErrors] = useState({ report: '', documents: '' });
  const [submitError, setSubmitError] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [useScanScope, setUseScanScope] = useState(false);
  const [scanScope, setScanScope] = useState<ScanScope>({
    contractNumber: '', periodStart: '', periodEnd: '', page: 1, stage: 1,
  });
  const isScan = /\.(pdf|png)$/i.test(report[0]?.file.name ?? '');
  const validScanScope = scanScope.contractNumber.trim().length > 0
    && /^\d{4}-\d{2}-\d{2}$/.test(scanScope.periodStart)
    && /^\d{4}-\d{2}-\d{2}$/.test(scanScope.periodEnd)
    && scanScope.periodStart <= scanScope.periodEnd
    && scanScope.periodStart.slice(0, 4) === scanScope.periodEnd.slice(0, 4)
    && Number.isInteger(scanScope.page) && scanScope.page >= 1 && scanScope.page <= 12
    && Number.isSafeInteger(scanScope.stage) && scanScope.stage >= 1;
  const canStart = report.length === 1 && documents.length > 0
    && (!isScan || !useScanScope || validScanScope);

  useEffect(() => () => active.current?.abort(), []);

  function changeFiles(group: FileGroup, next: SelectedFile[]) {
    attempt.current = null;
    const setFiles = group === 'report' ? setReport : setDocuments;
    setFiles(next);
    setErrors((previous) => ({ ...previous, [group]: '' }));
    setSubmitError('');
  }

  function updateScope(values: Partial<ScanScope>) {
    attempt.current = null;
    setSubmitError('');
    setScanScope((previous) => ({ ...previous, ...values }));
  }

  function removeFile(group: FileGroup, id: number) {
    if (active.current) return;
    const files = group === 'report' ? report : documents;
    changeFiles(group, files.filter((item) => item.id !== id));
  }

  function takeFiles(incoming: FileList, group: FileGroup) {
    if (publicDemo || active.current || incoming.length === 0) return;
    const selected = Array.from(incoming);
    const isReport = group === 'report';
    const setError = (message: string) => setErrors((previous) => ({ ...previous, [group]: message }));
    if (isReport && selected.length > 1) {
      setError('Выберите один файл КФЗ.');
      return;
    }
    if (!selected.every((file) => file.size > 0 && formats.some(
      (extension) => file.name.toLowerCase().endsWith(extension),
    ))) {
      setError('Добавьте непустые PDF, DOCX, XLSX или PNG.');
      return;
    }
    if (selected.some((file) => file.size > maxFileSize)) {
      setError('Размер одного файла не должен превышать 50 МиБ.');
      return;
    }
    if (!isReport && documents.length + selected.length > maxDocuments) {
      setError('Можно добавить до 100 первичных документов.');
      return;
    }

    const retainedFiles = isReport ? documents : [...report, ...documents];
    const size = selected.reduce((total, file) => total + file.size, 0)
      + retainedFiles.reduce((total, item) => total + item.file.size, 0);
    if (size > maxPackageSize) {
      setError('Размер пакета не должен превышать ' + maxPackageMiB + ' МиБ.');
      return;
    }

    const items = selected.map((file) => ({ id: nextFileId.current++, file }));
    changeFiles(group, isReport ? items : [...documents, ...items]);
  }

  async function submit() {
    if (publicDemo || active.current || !canStart) return;
    const controller = new AbortController();
    active.current = controller;
    setIsSending(true);
    setSubmitError('');
    try {
      attempt.current ??= prepareRunUpload({
        report: report[0].file,
        documents: documents.map(({ file }) => file),
        scanScope: isScan && useScanScope
          ? { ...scanScope, contractNumber: scanScope.contractNumber.trim() }
          : undefined,
      }, newIdempotencyKey());
      const accepted = await attempt.current(controller.signal);
      if (controller.signal.aborted) return;
      void navigate('/checks/' + encodeURIComponent(accepted.run_id));
    } catch (error) {
      if (!controller.signal.aborted) setSubmitError(uploadErrorMessage(error));
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setIsSending(false);
    }
  }

  async function startTrial() {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setIsSending(true);
    setSubmitError('');
    try {
      const response = await fetch('/api/v0/trial', { method: 'POST', signal: controller.signal });
      if (response.status !== 202) throw new Error('Trial request failed');
      const accepted = await response.json() as { run_id?: unknown };
      if (!isRunId(accepted.run_id)) {
        throw new Error('Invalid trial run ID');
      }
      if (!controller.signal.aborted) void navigate('/checks/' + accepted.run_id);
    } catch {
      if (!controller.signal.aborted) setSubmitError('Не удалось запустить пробную проверку.');
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setIsSending(false);
    }
  }

  return (
    <div className="upload-page">
      <h1>Новая проверка</h1>
      <p className="upload-intro">{publicTrial
        ? 'Проверьте учебную КФЗ и 22 первичных документа из готового комплекта.'
        : 'Добавьте КФЗ и первичные документы.'}</p>
      {publicDemo ? (
        <section className="upload-card upload-public-notice mt-6">
          <h2>{publicTrial ? 'Синтетический комплект' : 'Загрузка доступна в локальной установке'}</h2>
          {publicTrial && <p>Откройте результат, проверьте источники и скачайте XLSX.</p>}
        </section>
      ) : (
        <div className="mt-6 grid grid-cols-1 items-start gap-5 md:grid-cols-2">
          <UploadBlock group="report" files={report} error={errors.report} disabled={isSending}
            onFiles={takeFiles} onRemove={(id) => removeFile('report', id)} />
          <UploadBlock group="documents" files={documents} error={errors.documents} disabled={isSending}
            onFiles={takeFiles} onRemove={(id) => removeFile('documents', id)} />
        </div>
      )}
      {!publicDemo && isScan && <fieldset className="upload-card mt-6" disabled={isSending}>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={useScanScope} onChange={(event) => {
            attempt.current = null;
            setSubmitError('');
            setUseScanScope(event.currentTarget.checked);
          }} />
          Указать строку КФЗ
        </label>
        {useScanScope && <>
          <p className="checks-caption">Укажите договор, период в пределах одного года и этап со скана.</p>
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
        </>}
      </fieldset>}
      <div className="upload-navigation mt-5 flex flex-wrap items-center gap-3">
        {publicTrial && <Button disabled={isSending} onClick={() => { void startTrial(); }}>
          Проверить учебный комплект <WorkspaceIcon name="arrow" size={17} />
        </Button>}
        {!publicDemo && <Button disabled={isSending || !canStart} onClick={() => { void submit(); }}>
          Отправить на проверку <WorkspaceIcon name="arrow" size={17} />
        </Button>}
        <Link className="workspace-button workspace-button-outline upload-example" to={demoRunPath}>
          Открыть готовый синтетический результат
        </Link>
      </div>
      {submitError && <p className="upload-validation" role="alert">{submitError}</p>}
      {isSending && <p role="status">{publicTrial ? 'Запускаем проверку…' : 'Отправляем пакет…'}</p>}
    </div>
  );
}

function UploadBlock({ group, files, error, disabled, onFiles, onRemove }: {
  group: FileGroup;
  files: SelectedFile[];
  error: string;
  disabled: boolean;
  onFiles: (files: FileList, group: FileGroup) => void;
  onRemove: (id: number) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
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
      {files.length === 0 ? <div className="upload-empty">
        <WorkspaceIcon name="file" size={28} />
        <p>{report ? 'Перетащите КФЗ сюда' : 'Перетащите документы сюда'}</p>
        <Button variant="outline" disabled={disabled} onClick={() => input.current?.click()}>
          {report ? 'Выбрать файл' : 'Выбрать файлы'}
        </Button>
      </div> : <>
        <UploadFileList files={files} disabled={disabled} onRemove={onRemove} />
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
