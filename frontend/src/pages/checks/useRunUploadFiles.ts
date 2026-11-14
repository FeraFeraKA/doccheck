import { useEffect, useRef, useState } from 'react';
import type { RetainedDocument } from './createRun';
import { uploadFileInfo } from './UploadFiles';
import type { UploadFile } from './UploadFiles';

export type FileGroup = 'report' | 'documents';

export interface InitialRunPack {
  runId: string;
  documents: readonly RetainedDocument[];
}

export const formats = ['.pdf', '.docx', '.xlsx', '.png'];
const mib = 1024 ** 2;
const maxFileSize = 50 * mib;
const maxPackageSize = 250 * mib;
const maxDocuments = 100;
const bytesToCheck = 1024;

interface FileGroups {
  report: UploadFile[];
  documents: UploadFile[];
}

const emptyGroups: FileGroups = { report: [], documents: [] };

function initialFiles(pack?: InitialRunPack): FileGroups {
  const report: UploadFile[] = [];
  const documents: UploadFile[] = [];
  for (const item of pack?.documents ?? []) {
    const group = item.role === 'report' ? report : documents;
    group.push({ id: `existing-${item.id}`, retained: item });
  }
  return { report, documents };
}

function checkLimits(files: FileGroups, changedGroup?: FileGroup) {
  const entries = [...files.report, ...files.documents];
  if (entries.some((item) => uploadFileInfo(item).size > maxFileSize)) {
    const group = files.report.some((item) => uploadFileInfo(item).size > maxFileSize) ? 'report' : 'documents';
    return { group, message: 'Размер одного файла не должен превышать 50 МиБ.' } as const;
  }
  if (files.documents.length > maxDocuments) {
    return { group: 'documents', message: 'Можно добавить до 100 первичных документов.' } as const;
  }
  if (entries.reduce((total, item) => total + uploadFileInfo(item).size, 0) > maxPackageSize) {
    return { group: changedGroup ?? 'documents', message: 'Размер пакета не должен превышать 250 МиБ.' } as const;
  }
  return null;
}

export function useRunUploadFiles(initialPack?: InitialRunPack) {
  const nextFileId = useRef(0);
  const readers = useRef(new Map<string, FileReader>());
  const [groups, setGroups] = useState(() => initialFiles(initialPack));
  const [errors, setErrors] = useState({ report: '', documents: '' });

  useEffect(() => {
    const active = readers.current;
    return () => {
      for (const reader of active.values()) reader.abort();
      active.clear();
    };
  }, []);

  function abortReading(id: string) {
    readers.current.get(id)?.abort();
    readers.current.delete(id);
  }

  function readFile(group: FileGroup, id: string, file: File) {
    const reader = new FileReader();
    const finish = (state: 'ready' | 'failed') => {
      readers.current.delete(id);
      setGroups((previous) => {
        if (!previous[group].some((item) => item.id === id)) return previous;
        const updated = previous[group].map((item) => item.id === id ? { id, file, state } : item);
        return { ...previous, [group]: updated };
      });
    };

    reader.addEventListener('load', () => finish('ready'), { once: true });
    reader.addEventListener('error', () => finish('failed'), { once: true });
    readers.current.set(id, reader);
    try {
      reader.readAsArrayBuffer(file.slice(0, bytesToCheck));
    } catch {
      finish('failed');
    }
  }

  function takeFiles(incoming: FileList, group: FileGroup) {
    if (incoming.length === 0) return false;
    const selected = Array.from(incoming);
    const isReport = group === 'report';
    const setError = (message: string) => setErrors((previous) => ({ ...previous, [group]: message }));
    if (isReport && selected.length > 1) {
      setError('Выберите один файл КФЗ.');
      return false;
    }
    if (!selected.every((file) => file.size > 0 && formats.some(
      (extension) => file.name.toLowerCase().endsWith(extension),
    ))) {
      setError('Добавьте непустые PDF, DOCX, XLSX или PNG.');
      return false;
    }
    const items = selected.map((file) => ({ id: `local-${nextFileId.current++}`, file, state: 'reading' as const }));
    const prospective = { ...groups, [group]: isReport ? items : [...groups.documents, ...items] };
    const limit = checkLimits(prospective, group);
    if (limit) {
      setErrors((previous) => ({ ...previous, [limit.group]: limit.message }));
      return false;
    }

    if (isReport) for (const item of groups.report) abortReading(item.id);
    setGroups((previous) => ({ ...previous, [group]: isReport ? items : [...previous.documents, ...items] }));
    setError('');
    for (const item of items) readFile(group, item.id, item.file);
    return true;
  }

  function removeFile(group: FileGroup, id: string) {
    abortReading(id);
    setGroups((previous) => ({ ...previous, [group]: previous[group].filter((item) => item.id !== id) }));
    setErrors((previous) => ({ ...previous, [group]: '' }));
  }

  function clearFiles() {
    setGroups(emptyGroups);
    setErrors({ report: '', documents: '' });
  }

  const limit = checkLimits(groups);
  return {
    ...groups,
    errors: limit ? { ...errors, [limit.group]: limit.message } : errors,
    withinLimits: limit === null,
    takeFiles,
    removeFile,
    clearFiles,
  };
}
