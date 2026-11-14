export function runTitle(id: string, reportNumber?: string) {
  const number = reportNumber?.trim();
  return number ? `КФЗ №${number}` : `Проверка КФЗ №${id}`;
}

export function runQueuePath(id: string) {
  return '/checks/new?' + new URLSearchParams({ run: id }) + '#queue';
}
