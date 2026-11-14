export function runTitle(reportNumber?: string, reportName?: string) {
  const number = reportNumber?.trim();
  if (number) return `КФЗ №${number}`;
  const name = reportName?.trim();
  return name ? `КФЗ · ${name}` : 'Проверка КФЗ';
}

export function runQueuePath(id: string) {
  return '/checks/new?' + new URLSearchParams({ run: id }) + '#queue';
}
