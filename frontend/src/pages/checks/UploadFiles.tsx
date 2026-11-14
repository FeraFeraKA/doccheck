import { FileTypeIcon } from './FileTypeIcon';
import { WorkspaceIcon } from './WorkspaceIcon';

interface UploadFile {
  id: number;
  file: File;
}

const fileExtension = (name: string) => name.split('.').pop()?.toUpperCase() ?? '';
const sizeLabel = (bytes: number) =>
  bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1).replace('.', ',')} МБ`
    : `${Math.max(1, Math.round(bytes / 1024))} КБ`;

export function UploadFileList({ files, onRemove, disabled }: {
  files: UploadFile[];
  onRemove: (id: number) => void;
  disabled: boolean;
}) {
  if (!files.length) return null;
  return (
    <ul className="upload-file-list" aria-label="Добавленные файлы">
      {files.map(({ id, file }) => (
        <li className="upload-file-row" key={id}>
          <FileTypeIcon extension={fileExtension(file.name)} />
          <div className="upload-file-info">
            <strong title={file.name}>{file.name}</strong>
            <span>{sizeLabel(file.size)}</span>
          </div>
          <span className="upload-file-status" aria-hidden="true"><WorkspaceIcon name="check" size={20} /></span>
          <button className="upload-remove" type="button" disabled={disabled} onClick={() => onRemove(id)}
            aria-label={`Удалить ${file.name}`} title="Убрать файл">
            <WorkspaceIcon name="close" size={18} />
          </button>
        </li>
      ))}
    </ul>
  );
}
