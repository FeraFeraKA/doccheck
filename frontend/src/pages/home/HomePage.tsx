export function HomePage() {
  const status = 'unverified';

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-semibold">DocCheck</h1>
      <p className="mt-4">Интерфейс проверки документов находится в разработке.</p>
      <p className="mt-4" data-status={status}>Статус результата: Проверено</p>
    </main>
  );
}
