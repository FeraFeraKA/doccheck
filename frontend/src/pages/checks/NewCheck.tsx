import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { prepareRunUpload, RunUploadHttpError } from './createRun';
import { demoRunPath } from './demoData';

const steps = ['КФЗ', 'Первичные документы'];
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

export function NewCheck() {
  const navigate = useNavigate();
  const nextFileId = useRef(0);
  const active = useRef<AbortController | null>(null);
  const attempt = useRef<ReturnType<typeof prepareRunUpload> | null>(null);
  const [step, setStep] = useState(0);
  const [report, setReport] = useState<SelectedFile[]>([]);
  const [documents, setDocuments] = useState<SelectedFile[]>([]);
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
    if (active.current || incoming.length === 0) return;
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
    if (active.current || report.length !== 1 || documents.length === 0) return;
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
    <div className="checks-upload">
      <h1>Новая проверка</h1>
      <p>Выберите карточку фактических затрат (КФЗ) и первичные документы.</p>
      <p>При отправке приложение сохраняет пакет для проверки. Сводные значения из первичных документов сравниваются с КФЗ.</p>
      <ol className="checks-tabs" aria-label="Шаги">
        {steps.map((label, index) => (
          <li key={label}>
            <button type="button" aria-current={index === step ? 'step' : undefined}
              disabled={isSending || (index === 1 && report.length === 0)} onClick={() => changeStep(index)}>
              {index + 1}. {label}
            </button>
          </li>
        ))}
      </ol>
      <section className="checks-card" onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => { event.preventDefault(); takeFiles(event.dataTransfer.files); }}>
        <div className="checks-heading">
          <div>
            <h2>Загрузка документов</h2>
            <p>{isReport ? 'Один файл КФЗ' : 'Первичные документы'} · PDF, DOCX, XLSX, PNG</p>
          </div>
        </div>
        <div className="checks-drop">
          <label htmlFor="check-files">{isReport ? 'Выберите КФЗ' : 'Выберите первичные документы'}</label>
          <input id="check-files" key={step} type="file" accept={formats.join(',')} multiple={!isReport}
            disabled={isSending} onChange={(event) => {
              if (event.currentTarget.files) takeFiles(event.currentTarget.files);
              event.currentTarget.value = '';
            }} />
          <p>Можно также перетащить файлы сюда.</p>
        </div>
        {error && <p role="alert" className="checks-error">{error}</p>}
        {files.length === 0 ? <p className="checks-caption">
          {isReport ? 'КФЗ пока не выбрана.' : 'Первичные документы пока не выбраны.'}
        </p> : <ul className="checks-files">
          {files.map(({ id, file }) => <li key={id}>
            <span>{file.name}</span>
            <button type="button" disabled={isSending} aria-label={'Удалить ' + file.name}
              onClick={() => {
                if (!active.current) changeFiles(files.filter((item) => item.id !== id));
              }}>Удалить</button>
          </li>)}
        </ul>}
        <div className="checks-actions">
          {isReport ? (
            <button className="checks-primary" type="button" disabled={report.length === 0}
              onClick={() => changeStep(1)}>Далее</button>
          ) : <>
            <button type="button" disabled={isSending} onClick={() => changeStep(0)}>Назад</button>
            <button className="checks-primary" type="button" disabled={isSending || report.length === 0 || documents.length === 0}
              onClick={() => { void submit(); }}>Отправить на проверку</button>
          </>}
        </div>
        {isSending && <p role="status">Отправляем пакет…</p>}
      </section>
      <p className="checks-caption">
        <Link to={demoRunPath}>Открыть готовый синтетический результат</Link>
      </p>
    </div>
  );
}
