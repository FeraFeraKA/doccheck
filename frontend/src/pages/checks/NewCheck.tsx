import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { classes } from '../../shared/lib/classes';
import { Button } from '../../shared/ui/Button';
import { UploadFileList } from './UploadFiles';
import { WorkspaceIcon } from './WorkspaceIcon';
import { prepareRunUpload, RunUploadHttpError } from './createRun';
import { demoRunPath } from './demoData';

const steps = ['Отчёт (КФЗ)', 'Первичные документы'];
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
  const navigate = useNavigate();
  const nextFileId = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const active = useRef<AbortController | null>(null);
  const attempt = useRef<ReturnType<typeof prepareRunUpload> | null>(null);
  const [step, setStep] = useState(0);
  const [report, setReport] = useState<SelectedFile[]>([]);
  const [documents, setDocuments] = useState<SelectedFile[]>([]);
  const [over, setOver] = useState(false);
  const [error, setError] = useState('');
  const [isSending, setIsSending] = useState(false);
  const isReport = step === 0;
  const files = isReport ? report : documents;
  const setFiles = isReport ? setReport : setDocuments;

  useEffect(() => () => active.current?.abort(), []);

  function changeStep(next: number) {
    if (active.current) return;
    setStep(next);
    setError('');
  }

  function changeFiles(next: SelectedFile[]) {
    attempt.current = null;
    setFiles(next);
    setError('');
  }

  function takeFiles(incoming: FileList) {
    if (publicDemo || active.current || incoming.length === 0) return;
    const selected = Array.from(incoming);
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
    changeFiles(isReport ? items : [...documents, ...items]);
  }

  async function submit() {
    if (publicDemo || active.current || report.length !== 1 || documents.length === 0) return;
    const controller = new AbortController();
    active.current = controller;
    setIsSending(true);
    setError('');
    try {
      attempt.current ??= prepareRunUpload({
        report: report[0].file,
        documents: documents.map(({ file }) => file),
      }, newIdempotencyKey());
      const accepted = await attempt.current(controller.signal);
      if (controller.signal.aborted) return;
      void navigate('/checks/' + encodeURIComponent(accepted.run_id));
    } catch (error) {
      if (!controller.signal.aborted) setError(uploadErrorMessage(error));
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setIsSending(false);
    }
  }

  return (
    <div className="upload-page">
      <h1>Новая проверка</h1>
      <p className="upload-intro">Добавьте отчёт и подтверждающие документы для сверки.</p>
      <ol className="upload-steps" aria-label="Шаги">
        {steps.map((label, index) => (
          <li key={label}>
            <button type="button" onClick={() => changeStep(index)} aria-current={index === step ? 'step' : undefined}
              disabled={isSending || (index === 1 && !publicDemo && report.length === 0)}>
              <span>{(index === 0 ? report.length : documents.length) > 0 && index !== step
                ? <WorkspaceIcon name="check" size={16} /> : index + 1}</span>
              {label}
            </button>
            {index === 0 && <WorkspaceIcon name="arrow" size={16} />}
          </li>
        ))}
      </ol>
      <section className={classes('upload-card', over && 'is-dragging')}
        onDragOver={(event) => {
          event.preventDefault();
          if (!publicDemo && !active.current) setOver(true);
        }}
        onDragLeave={(event) => {
          if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
            setOver(false);
          }
        }}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          takeFiles(event.dataTransfer.files);
        }}>
        <header className="upload-card-header">
          <div>
            <h2>Загрузка документов</h2>
            <p>{isReport ? 'Отчёт КФЗ · один файл PDF, DOCX, XLSX или PNG' : 'Первичные документы · PDF, DOCX, XLSX, PNG'}</p>
          </div>
          <Link className="upload-example" to={demoRunPath}>Открыть готовый синтетический результат</Link>
        </header>
        {publicDemo ? <div className="upload-empty">
          <div className="upload-empty-icon"><WorkspaceIcon name="file" size={32} /></div>
          <h3>Загрузка доступна в локальной установке</h3>
          <p>В публичном демо можно открыть готовый синтетический результат.</p>
        </div> : <>
          <input key={step} ref={input} type="file" hidden
            aria-label={isReport ? 'Выберите КФЗ' : 'Выберите первичные документы'}
            accept={formats.join(',')} multiple={!isReport} disabled={isSending}
            onChange={(event) => {
              if (event.currentTarget.files) takeFiles(event.currentTarget.files);
              event.currentTarget.value = '';
            }} />
          {files.length === 0 ? <div className="upload-empty">
            <div className="upload-empty-icon"><WorkspaceIcon name="file" size={32} /></div>
            <h3>{isReport ? 'Перетащите отчёт сюда' : 'Перетащите документы сюда'}</h3>
            <p>или выберите {isReport ? 'файл' : 'файлы'} на компьютере</p>
            <Button variant="outline" disabled={isSending} onClick={() => input.current?.click()}>
              {isReport ? 'Выбрать файл' : 'Выбрать файлы'}
            </Button>
          </div> : <>
            <UploadFileList files={files} disabled={isSending} onRemove={(id) => {
              if (!active.current) changeFiles(files.filter((item) => item.id !== id));
            }} />
            <div className="upload-list-actions">
              <button type="button" disabled={isSending} onClick={() => input.current?.click()}>
                <WorkspaceIcon name="plus" size={18} />
                {isReport ? 'Заменить отчёт' : 'Добавить документы'}
              </button>
              <span>Файлов: {files.length}</span>
            </div>
          </>}
          {error && <p className="upload-validation" role="alert">{error}</p>}
        </>}
      </section>
      <div className="upload-navigation">
        <Button variant="outline" disabled={isReport || isSending} onClick={() => changeStep(0)}>Назад</Button>
        {isReport ? (
          <Button disabled={isSending || (!publicDemo && report.length === 0)}
            onClick={() => changeStep(1)}>
            Первичные документы <WorkspaceIcon name="arrow" size={17} />
          </Button>
        ) : !publicDemo && <div>
          <Button disabled={isSending || report.length === 0 || documents.length === 0}
            onClick={() => { void submit(); }}>
            Отправить на проверку <WorkspaceIcon name="arrow" size={17} />
          </Button>
        </div>}
      </div>
      {isSending && <p role="status">Отправляем пакет…</p>}
    </div>
  );
}
