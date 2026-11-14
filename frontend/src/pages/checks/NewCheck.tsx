import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { Button } from '../../shared/ui/Button';
import { UploadFileList } from './UploadFiles';
import { WorkspaceIcon } from './WorkspaceIcon';
import { prepareRunUpload, RunUploadHttpError } from './createRun';
import type { CheckHistory } from './checkData';
import { RunQueue } from './RunQueue';
import { useRunHistory } from './useRunHistory';
import { demoRunPath } from './demoData';

type FileGroup = 'report' | 'documents';

const formats = ['.pdf', '.docx', '.xlsx', '.png'];
const mib = 1024 ** 2;
const maxFileSize = 50 * mib;
const maxPackageSize = 250 * mib;
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

const publicDemo = import.meta.env.VITE_DOCCHECK_PUBLIC_DEMO === '1';

export function NewCheck() {
  const submitButton = useRef<HTMLButtonElement>(null);
  const chooseReport = useRef<HTMLButtonElement>(null);
  const restoreUploadFocus = useRef(false);
  const [receipts, setReceipts] = useState<string[]>([]);
  const clearListedReceipts = useCallback(({ entries }: CheckHistory) => {
    const listed = new Set(entries.map(({ id }) => id));
    setReceipts((previous) => previous.filter((id) => !listed.has(id)));
  }, []);
  const history = useRunHistory({ enabled: !publicDemo, onPage: clearListedReceipts });
  const nextFileId = useRef(0);
  const active = useRef<AbortController | null>(null);
  const attempt = useRef<ReturnType<typeof prepareRunUpload> | null>(null);
  const [report, setReport] = useState<SelectedFile[]>([]);
  const [documents, setDocuments] = useState<SelectedFile[]>([]);
  const [errors, setErrors] = useState({ report: '', documents: '' });
  const [submitError, setSubmitError] = useState('');
  const [isSending, setIsSending] = useState(false);
  const canStart = report.length === 1 && documents.length > 0;

  useEffect(() => () => active.current?.abort(), []);


  function changeFiles(group: FileGroup, next: SelectedFile[]) {
    attempt.current = null;
    const setFiles = group === 'report' ? setReport : setDocuments;
    setFiles(next);
    setErrors((previous) => ({ ...previous, [group]: '' }));
    setSubmitError('');
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
      setError('Размер пакета не должен превышать 250 МиБ.');
      return;
    }

    const items = selected.map((file) => ({ id: nextFileId.current++, file }));
    changeFiles(group, isReport ? items : [...documents, ...items]);
  }

  useEffect(() => {
    if (isSending || !restoreUploadFocus.current) return;
    restoreUploadFocus.current = false;
    if (document.activeElement === document.body) chooseReport.current?.focus({ preventScroll: true });
  }, [isSending]);

  async function submit() {
    if (publicDemo || active.current || !canStart) return;
    const controller = new AbortController();
    active.current = controller;
    setIsSending(true);
    setSubmitError('');
    const submitHadFocus = document.activeElement === submitButton.current;
    try {
      attempt.current ??= prepareRunUpload({
        report: report[0].file,
        documents: documents.map(({ file }) => file),
      }, newIdempotencyKey());
      const accepted = await attempt.current(controller.signal);
      if (controller.signal.aborted) return;
      setReceipts((previous) => [accepted.run_id, ...previous.filter((id) => id !== accepted.run_id)].slice(0, 20));
      restoreUploadFocus.current = submitHadFocus;
      setReport([]);
      setDocuments([]);
      setErrors({ report: '', documents: '' });
      attempt.current = null;
      history.refresh();
    } catch (error) {
      if (!controller.signal.aborted) setSubmitError(uploadErrorMessage(error));
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setIsSending(false);
    }
  }

  return (
    <div className="upload-page">
      <h1>Новая проверка</h1>
      {!publicDemo && <p className="upload-intro">Добавьте КФЗ и первичные документы.</p>}
      {publicDemo ? (
        <section className="upload-card upload-public-notice mt-6">
          <h2>Загрузка доступна в локальной установке</h2>
        </section>
      ) : (
        <div className="mt-6 grid grid-cols-1 items-start gap-5 md:grid-cols-2">
          <UploadBlock chooseButton={chooseReport} group="report" files={report} error={errors.report} disabled={isSending}
            onFiles={takeFiles} onRemove={(id) => removeFile('report', id)} />
          <UploadBlock group="documents" files={documents} error={errors.documents} disabled={isSending}
            onFiles={takeFiles} onRemove={(id) => removeFile('documents', id)} />
        </div>
      )}
      <div className="upload-navigation mt-5 flex flex-wrap items-center gap-3">
        {!publicDemo && <Button ref={submitButton} disabled={isSending || !canStart} onClick={() => { void submit(); }}>
          Отправить на проверку <WorkspaceIcon name="arrow" size={17} />
        </Button>}
        <Link className="workspace-button workspace-button-outline upload-example" to={demoRunPath}>
          Открыть готовый синтетический результат
        </Link>
      </div>
      {submitError && <p className="upload-validation" role="alert">{submitError}</p>}
      {isSending && <p role="status">Загрузка файлов…</p>}
      {!publicDemo && <RunQueue entries={history.page?.entries} receipts={receipts}
        loading={history.loading} error={history.error} onRetry={history.refresh} />}
    </div>
  );
}

function UploadBlock({ group, files, error, disabled, chooseButton, onFiles, onRemove }: {
  group: FileGroup;
  files: SelectedFile[];
  error: string;
  disabled: boolean;
  chooseButton?: React.Ref<HTMLButtonElement>;
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
        <Button ref={chooseButton} variant="outline" disabled={disabled} onClick={() => input.current?.click()}>
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
