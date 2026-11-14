export function runTitle(id: string, reportNumber?: string) {
  const number = reportNumber?.trim();
  return number ? `КФЗ №${number}` : `Проверка КФЗ №${id}`;
}
