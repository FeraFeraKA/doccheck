import demoJob from '../../../../contracts/check-result.v1.synthetic.json';
import demoPackage from '../../../../docs/synthetic/nrt-89/inputs.json';

export const { result: demoResult } = demoJob;
export const demoFiles = demoPackage.files;
export const demoRunPath = '/checks/' + demoResult.run_id;

export const statusLabels: Record<string, string> = {
  verified: 'Подтверждён',
  discrepancy: 'Расхождение',
  unverified: 'Не проверен',
};

export function formatMoney(value: string | null) {
  if (value === null) return '—';
  const [integer, decimals] = value.split('.');
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0') + ',' + decimals;
}

export function formatLocation(locator: (typeof demoResult.evidence)[number]['locator']) {
  if (locator.kind === 'sheet') return `Лист «${locator.sheet}», ${locator.range}`;
  if (locator.table_row !== undefined) {
    return `Страница ${locator.page}, строка ${locator.table_row}, столбец ${locator.table_column}`;
  }
  return `Страница ${locator.page}`;
}
