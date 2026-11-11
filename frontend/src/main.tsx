import { StrictMode, lazy, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import './styles.css';

// No demo module or document assets are imported by a normal production build.
const Screen = import.meta.env.MODE === 'demo' ? lazy(() => import('./DemoApp')) : null;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {Screen ? <Suspense fallback={<main className="empty-state" role="status">Загрузка DocCheck…</main>}><Screen /></Suspense> :
      <main className="page-shell"><section className="panel empty-state">
        <h1>DocCheck</h1><p>Подключение к сервису сверки ещё не настроено.</p>
        <p className="muted">Демонстрационные результаты в рабочем режиме отключены.</p>
      </section></main>}
  </StrictMode>,
);
