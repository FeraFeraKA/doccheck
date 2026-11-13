# NRT-107 — компактный мастер загрузки

[Задача NRT-107](https://linear.app/andreiakimov/issue/NRT-107/sinhronizirovat-izmeneniya-interfejsa-andreya-s-doccheck)
прочитана 14 ноября 2026 года. Перенесён мастер из `cda9bc2f2fb3f5d3ee7e022d85b148fee9059e86`.
[Сравнение с прежним референсом `eaef18a`](https://github.com/ananakimov/project-placeholder/compare/eaef18a1e05c6e54948730e30d91c12f341b06b8...cda9bc2f2fb3f5d3ee7e022d85b148fee9059e86)

| Исходник Андрея | DocCheck | Перенесённые элементы |
| --- | --- | --- |
| `src/pages/NewCheck.tsx` | `frontend/src/pages/checks/NewCheck.tsx` | Два блока выбора, состояния пустого и заполненного списка, строка действий |
| `src/components/UploadFiles.tsx` | `frontend/src/pages/checks/UploadFiles.tsx` | Компактные строки выбранных файлов |
| `src/styles/workspace.css` и Tailwind-классы мастера | `frontend/src/pages/checks/accountant-workspace.css` и классы в компонентах | Сетка, плотность карточек и списков |

Локально можно выбрать КФЗ и первичные документы в любом порядке. Мастер
использует действующий multipart POST и повтор с тем же ключом идемпотентности.
Публичная сборка показывает ограничение загрузки и ссылку на готовый
синтетический результат без обращения к API.

В Chromium сопоставлены живой референс Pages и локальная сборка на ширинах
320, 390, 701, 768 и 1440 px. До 768 px блоки расположены друг под другом,
начиная с 768 px идут рядом. На 1440 px ширина карточек составляет 520 px в
обоих вариантах. На 320 px ширина страницы DocCheck совпала с viewport,
у референса замерено 360 px. Публичная сборка на тех же размерах открыла
готовый пример. Точный коммит деплоя Pages не подтверждался.

Прошли `pnpm lint`, `pnpm typecheck`, `pnpm build`, публичная сборка,
142 Vitest, 19 Playwright и `git diff --check`. Сетевые сценарии использовали
синтетические HTTP-ответы. После обновления базы до `f2781e1` дерево
frontend совпало с проверенной версией. Изменения экрана результата в этот
срез не входят.
