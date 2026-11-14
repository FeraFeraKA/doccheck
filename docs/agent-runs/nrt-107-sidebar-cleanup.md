# NRT-107 — боковая панель без статического профиля

[NRT-107](https://linear.app/andreiakimov/issue/NRT-107/sinhronizirovat-izmeneniya-interfejsa-andreya-s-doccheck)
прочитана 14 ноября 2026 года. База `f6824f6aa37ecdb5a37aef40a71a064fa6ef96a6`.
Удаление блока профиля из `src/components/layout/Sidebar.tsx` перенесено
в `frontend/src/pages/checks/Sidebar.tsx`. Убраны стили профиля и пустой
контейнер. «Проверка системы» остаётся внизу боковой панели на широком
экране и под основным содержимым на мобильном. [Сравнение исходника](https://github.com/ananakimov/project-placeholder/compare/6c2aaa8bdb8c65b1e6163c61222bef542e1549af...2d0c53c04c73526d9ee246df9f6c8909375a3485)

Chromium на 320, 700, 701 и 1440 px подтвердил переход по единственной
видимой ссылке на `/system-status`. При ширине до 700 px нижняя граница
хедера совпадает с нижней границей навигации с точностью до 1 px.
Прошли lint, typecheck, сборка, 9 Vitest и 3 сценария Playwright.
Браузерные проверки использовали синтетические HTTP-ответы.
