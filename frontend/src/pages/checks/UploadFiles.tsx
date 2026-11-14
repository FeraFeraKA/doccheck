import { FileTypeIcon } from './FileTypeIcon';
import { WorkspaceIcon } from './WorkspaceIcon';
import type { RetainedDocument } from './createRun';
import './upload-files.css';

export type UploadFile =
  | { id: string; file: File; state: 'reading' | 'ready' | 'failed' }
  | { id: string; retained: RetainedDocument };

export function uploadFileInfo(item: UploadFile) {
  return 'file' in item ? item.file : item.retained;
}

const fileExtension = (name: string) => name.split('.').pop()?.toUpperCase() ?? '';
const sizeLabel = (bytes: number) =>
  bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1).replace('.', ',')} МБ`
    : `${Math.max(1, Math.round(bytes / 1024))} КБ`;

export function UploadSpinner() {
  return <span className="upload-spinner" aria-hidden="true" />;
}

export function UploadFileList({ files, onRemove, onReplace, disabled, transferring }: {
  files: UploadFile[];
  onRemove: (id: string) => void;
  onReplace?: (id: string) => void;
  disabled: boolean;
  transferring: boolean;
}) {
  if (!files.length) return null;
  return (
    <ul className="upload-file-list" aria-label="Добавленные файлы">
      {files.map((item) => {
        const { name, size } = uploadFileInfo(item);
        const reading = 'file' in item && item.state === 'reading';
        const failed = 'file' in item && item.state === 'failed';
        const uploading = transferring && 'file' in item;
        return (
          <li className="upload-file-row" data-replaceable={onReplace ? 'true' : undefined} key={item.id}>
            <FileTypeIcon extension={fileExtension(name)} />
            <div className="upload-file-info">
              <strong title={name}>{name}</strong>
              <span>{sizeLabel(size)}</span>
              {failed && <span className="upload-file-error" role="alert">Не удалось прочитать файл. Выберите его заново.</span>}
            </div>
            <span className="upload-file-status">
              {(reading || uploading) && <>
                <UploadSpinner />
                <span className="sr-only">{reading ? 'Чтение файла' : 'Передача файла'}</span>
              </>}
              {!failed && !reading && !uploading && <span aria-hidden="true"><WorkspaceIcon name="check" size={20} /></span>}
            </span>
            {onReplace && <button className="upload-replace" type="button" disabled={disabled}
              onClick={() => onReplace(item.id)} aria-label={`Заменить ${name}`} title="Заменить файл">
              <WorkspaceIcon name="pencil" size={16} />
            </button>}
            <button className="upload-remove" type="button" disabled={disabled} onClick={() => onRemove(item.id)}
              aria-label={`Удалить ${name}`} title="Убрать файл">
              <WorkspaceIcon name="close" size={18} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
