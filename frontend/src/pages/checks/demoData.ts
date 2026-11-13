import demoJob from '../../../../contracts/check-result.v1.synthetic.json';
import demoPackage from '../../../../docs/synthetic/nrt-89/inputs.json';

export { demoJob };
export const demoFiles = demoPackage.files;
export const demoRunPath = '/checks/' + demoJob.run_id;
export const demoTitle = 'Синтетическая сверка';
