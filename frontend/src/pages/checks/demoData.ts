import demoJob from '../../../../contracts/check-result.v1.synthetic.json';
import demoPackage from '../../../../docs/synthetic/nrt-89/inputs.json';

export { demoJob };
export const demoFiles = demoPackage.files;
export const demoRunPath = '/checks/' + demoJob.run_id;
export const demoTitle = 'Синтетическая сверка';

export const demoUploadFiles = ['report.xlsx', 'act.docx'] as const;

export async function loadDemoUpload(signal: AbortSignal) {
  const [report, act] = await Promise.all(demoUploadFiles.map(async (name) => {
    const response = await fetch(`${import.meta.env.BASE_URL}demo/${name}`, { signal });
    if (!response.ok) throw new Error('Файл синтетического примера недоступен.');
    const blob = await response.blob();
    if (blob.size === 0) throw new Error('Файл синтетического примера пуст.');
    return new File([blob], name, { type: blob.type });
  }));
  return { report, documents: [act], synthetic: true };
}
