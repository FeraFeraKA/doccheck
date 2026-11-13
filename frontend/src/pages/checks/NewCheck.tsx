import { useRef, useState } from 'react';
import { Link } from 'react-router';
import { demoFiles, demoRunPath } from './demoData';

const steps = ['Отчёт (КФЗ)', 'Первичные документы'];
const formats = ['.pdf', '.docx', '.xlsx', '.png'];

interface SelectedFile {
  id: string;
  name: string;
}

export function NewCheck() {
  const nextFileId = useRef(0);
  const [step, setStep] = useState(0);
  const [report, setReport] = useState<SelectedFile[]>([]);
  const [documents, setDocuments] = useState<SelectedFile[]>([]);
  const [error, setError] = useState('');
  const isReport = step === 0;
  const files = isReport ? report : documents;
  const setFiles = isReport ? setReport : setDocuments;

  function changeStep(next: number) {
    setStep(next);
    setError('');
  }

  function takeFiles(incoming: FileList) {
    const selected = Array.from(incoming);
    const accepted = selected.filter((file) => file.size > 0 && formats.some(
      (extension) => file.name.toLowerCase().endsWith(extension),
    ));
    setError(accepted.length < selected.length ? 'Добавьте непустые PDF, DOCX, XLSX или PNG.' : '');
    if (accepted.length === 0) return;
    const items = accepted.map((file) => ({ id: 'local-' + nextFileId.current++, name: file.name }));
    setFiles((previous) => isReport ? items.slice(0, 1) : [...previous, ...items]);
  }

  function loadExample() {
    setFiles(demoFiles.filter((file) => (file.role === 'report') === isReport)
      .map((file) => ({ id: file.id, name: file.file.replace('inputs/', '') })));
    setError('');
  }

  return (
    <div className="checks-upload">
      <h1>Новая проверка</h1>
      <p>Выберите отчёт и подтверждающие документы для предварительного просмотра пакета.</p>
      <ol className="checks-tabs" aria-label="Шаги">
        {steps.map((label, index) => (
          <li key={label}>
            <button type="button" aria-current={index === step ? 'step' : undefined}
              disabled={index === 1 && report.length === 0} onClick={() => changeStep(index)}>
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
          <button type="button" onClick={loadExample}>Загрузить пример</button>
        </div>
        <div className="checks-drop">
          <label htmlFor="check-files">{isReport ? 'Выберите отчёт' : 'Выберите первичные документы'}</label>
          <input id="check-files" key={step} type="file" accept={formats.join(',')} multiple={!isReport}
            onChange={(event) => {
              if (event.currentTarget.files) takeFiles(event.currentTarget.files);
              event.currentTarget.value = '';
            }} />
          <p>Можно также перетащить файлы сюда.</p>
        </div>
        {error && <p role="alert" className="checks-error">{error}</p>}
        {files.length > 0 && <ul className="checks-files">
          {files.map(({ id, name }) => <li key={id}>
            <span>{name}</span>
            <button type="button" aria-label={'Удалить ' + name}
              onClick={() => setFiles(files.filter((file) => file.id !== id))}>Удалить</button>
          </li>)}
        </ul>}
        <div className="checks-actions">
          {isReport ? (
            <button className="checks-primary" type="button" disabled={report.length === 0}
              onClick={() => changeStep(1)}>Далее</button>
          ) : (
            <button type="button" onClick={() => changeStep(0)}>Назад</button>
          )}
          <Link className="checks-button" to={demoRunPath}>Открыть готовый синтетический результат</Link>
        </div>
      </section>
    </div>
  );
}
