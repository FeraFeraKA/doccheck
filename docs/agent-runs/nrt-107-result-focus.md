# NRT-107 — полноэкранная сверка и клавиатура

[NRT-107](https://linear.app/andreiakimov/issue/NRT-107/sinhronizirovat-izmeneniya-interfejsa-andreya-s-doccheck)
· База `2bb0a7051af17a86a0de30b37c64be404ceadf81`.

Кнопка «На весь экран» перенесена из командной строки
`src/pages/CheckDetail.tsx` в одноимённый экран DocCheck. Полноэкранная
сверка использует модальный режим, блокирует прокрутку страницы и
возвращает фокус кнопке при закрытии. При открытии источника полноэкранная
сверка закрывается. [Исходный интерфейс](https://github.com/ananakimov/project-placeholder/blob/2d0c53c04c73526d9ee246df9f6c8909375a3485/src/pages/CheckDetail.tsx)

При открытой панели источника Alt+↑ и Alt+↓ не переключают строки
позади неё. Браузерный сценарий с двумя расхождениями и PNG проверяет,
что после Alt+↓ рамка остаётся на месте, а Escape возвращает фокус
к источнику выбранной строки. После закрытия панели Alt+↓ выбирает
и фокусирует следующую строку. Сценарий выполняется на 390 и 768 px.
[Замечание ревью](https://github.com/VCyberPunk2077/doccheck/pull/71#issuecomment-6868140189)

Прошли lint, typecheck, сборка, 142 Vitest, 26 Playwright и
`git diff --check`. Браузер проверял синтетические ответы API.
