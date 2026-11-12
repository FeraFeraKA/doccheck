import { formatAmount } from './formatAmount';

export function HomePage() {
  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-semibold">DocCheck</h1>
      <p className="mt-4">Интерфейс проверки документов находится в разработке.</p>
      <p className="mt-4">Синтетический пример: ожидаемая сумма — {formatAmount(null)} ₽</p>
    </main>
  );
}
