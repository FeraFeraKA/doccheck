# NRT-107 — постоянная навигация

[NRT-107](https://linear.app/andreiakimov/issue/NRT-107/sinhronizirovat-izmeneniya-interfejsa-andreya-s-doccheck)
· База `7dbddb769bb02670baf2a101e2309230e89afa49` ·
[Изменения источника](https://github.com/ananakimov/project-placeholder/compare/839b98196917c10e055e431ae02de33ef0191665...5a854c837f1f999b9d6769deeca751e146b4f96d)

Навигация из `src/components/layout/Sidebar.tsx` и правила из
`src/styles/workspace.css` перенесены в `Sidebar.tsx` и
`accountant-workspace.css`. Ссылки видны постоянно. До 700 px меню
занимает верхнюю часть страницы, при 701–1250 px панель занимает 210 px,
на более широких экранах — 240 px. Пункт «Проверка системы» сохранён.
Архив остаётся частью отдельного жизненного цикла проверок.

Chromium проверил 320, 700, 701, 768, 1250, 1251 и 1650 px, геометрию
панели, доступность ссылок и переход с клавиатуры. Проверка использовала
синтетические ответы HTTP. Прошли lint, typecheck, сборка, 146 Vitest,
44 Playwright и `git diff --check`.
