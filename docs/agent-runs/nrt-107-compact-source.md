# NRT-107 — компактная панель источника

[NRT-107](https://linear.app/andreiakimov/issue/NRT-107/sinhronizirovat-izmeneniya-interfejsa-andreya-s-doccheck)
· База `d0922d35bb61098cfe7497a9fefbde135f909b58) ·
[Изменение исходника `282804f`](https://github.com/ananakimov/project-placeholder/commit/282804f6b2a25c42803b999d2adf7471bf40ea06)

Из `src/pages/CheckDetail.tsx` перенесена компактная шапка панели в
`SourceDrawer.tsx`. Группы управления из
`src/components/check/SourceViewer.tsx` перенесены в
`DocumentSourcePreview.tsx`, а размеры и прокрутка из
`src/styles/workspace.css` — в `source-drawer.css`.
В обычном окне оставшееся место занимает область документа. При малой
высоте панель может прокручиваться целиком, чтобы кнопки оставались доступны.

Адреса и оригиналы получает существующий API. Для PNG использована та же
рамка сохранённого доказательства, доступны масштаб и переход к фрагменту.
Кнопка «К таблице» сохраняет доступное имя «Вернуться к таблице».
Растровые страницы внешнего примера не добавлялись.

Сверены 25 разрешённых файлов кейса. В тестах использован публичный
синтетический PNG NRT-89 с синтетическими HTTP-ответами. Chromium проверил
1440×1100, 768×844 и 390×600, доступную высоту документа, рамку после
масштабирования, скачивание и возврат фокуса по Escape. Прошли lint,
typecheck, сборка, 142 Vitest, 31 Playwright и `git diff --check`.
