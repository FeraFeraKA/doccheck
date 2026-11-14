# NRT-107. Адаптивная вёрстка мастера загрузки

[NRT-107](https://linear.app/andreiakimov/issue/NRT-107/sinhronizirovat-izmeneniya-interfejsa-andreya-s-doccheck) прочитана 14.11.2026. База DocCheck `1c074ded57a915d45a3785366b4dcb0553c21908`. Сверка опирается на [диапазон от компактного мастера `cda9bc2` до `ed8c2f1`](https://github.com/ananakimov/project-placeholder/compare/cda9bc2f2fb3f5d3ee7e022d85b148fee9059e86...ed8c2f159fbc207c177aaf950649d456553ca4c4).

| Источник Андрея | DocCheck | Перенос |
| --- | --- | --- |
| `src/pages/NewCheck.tsx` и правила загрузки в `src/styles/workspace.css` | `frontend/src/pages/checks/NewCheck.tsx` и `accountant-workspace.css` | Существующая структура формы уже подходит. Согласованы размеры заголовков и подсказок, внутренние отступы, радиус и высота зоны загрузки, положение ряда действий. |
| `src/components/UploadFiles.tsx` | `frontend/src/pages/checks/UploadFiles.tsx` и `accountant-workspace.css` | Восстановлены компактная строка файла, индикатор выбора, удаление в правом верхнем углу и оформление действий под списком. На сенсорных устройствах удаление видно сразу, на десктопе оно доступно при наведении или клавиатурном фокусе. |

На 390, 768 и 1440 px Chromium подтвердил совпадение размеров двух карточек и вертикальных координат ряда действий в пустом и заполненном состояниях. На 390 px заголовок «Первичные документы» занимает одну строку, на 768 px — две, на 1440 px — одну. Для состояния ошибки высота зависит от количества строк реального сообщения. Перетаскивание проверено отдельно. В DocCheck сохранены более контрастные подсказки, допустимые API форматы, кнопка реальной отправки и явно подписанный готовый синтетический результат.

Прошли `pnpm lint`, `pnpm typecheck`, 146 тестов `pnpm test`, обычная и публичная сборки `pnpm build`, 49 Playwright с локальным Chrome и `git diff --check`. Фотографии экранов и замеры собраны на локальных сборках с синтетическими файлами. Браузерные тесты этого среза используют подмену API. Живой прогон v3.2 выполнялся отдельно в [#89](https://github.com/VCyberPunk2077/doccheck/pull/89).

Очередь и повторная отправка пакетов относятся к [#83](https://github.com/VCyberPunk2077/doccheck/pull/83). Приём архивов отслеживает [NRT-109](https://linear.app/andreiakimov/issue/NRT-109/soglasovat-priyom-arhivov-s-pervichnymi-dokumentami). Измеримые стадии обработки, архив принятых проверок и версионирование требуют подтверждённых серверных операций. [Предложение по жизненному циклу](https://github.com/ananakimov/project-placeholder/blob/ed8c2f159fbc207c177aaf950649d456553ca4c4/docs/check-lifecycle-nrt107.md)
