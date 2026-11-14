# NRT-107. Подсветка документов и состояния загрузки

[Задача Linear](https://linear.app/andreiakimov/issue/NRT-107/sinhronizirovat-izmeneniya-interfejsa-andreya-s-doccheck) прочитана 14.11.2026. Этот срез закрывает дополнительные замечания Николая к просмотрщику, загрузке и переходу в результат. База DocCheck `45b30eddd0bf3ad47e8918ab1eeac2633dfcc335`. Для легенды сверены файлы Андрея по [диапазону 3034701…9b8ca16](https://github.com/ananakimov/project-placeholder/compare/3034701610194c394d9d188576924eb0ea642ead...9b8ca16ea07c29cec24f700689ff04e160fd5e73).

| Референс или сценарий | Файлы DocCheck | Поведение |
| --- | --- | --- |
| `src/components/check/SourceWorkspace.tsx` | `SourceWorkspace.tsx`, `SourceContext.tsx` | Один список документов. Переход из показателя и сохранённые ссылки открывают нужный адрес. |
| `SourceViewer.tsx`, `document-annotations.ts`, `src/styles/workspace.css` | `DocumentSourcePreview.tsx`, `sourceHighlights.ts`, `OfficeReader.tsx`, `PdfReader.tsx` и стили просмотрщика | У каждого доступного типа извлечённых данных свой цвет и флажок. Совпадающие адреса подсвечиваются одной отметкой. Настройки и увеличенные кнопки масштаба проверены в просмотрщике. |
| Отправка пакета | `NewCheck.tsx`, `usePreparedRun.ts`, `createRun.ts`, `upload-files.css` | Полоса от 0% до 100% по событиям передачи. Кнопка запуска активируется после подтверждения приёма. |
| Открытие проверки и редактирование комплекта | `CheckDetail.tsx`, `RunPackEditor.tsx`, `CheckLoadingSkeletons.tsx`, `SourcePreviewSkeleton.tsx` | Скелетоны результата, списка документов, редактора и предпросмотра. Шаблон результата остаётся одним и тем же до окончания обоих запросов. |

Категории берутся из `evidence.kind`. Для сохранённых результатов без этого поля используются типизированные ссылки слагаемых и значения КФЗ. У PDF и PNG рамка появляется при сохранённом `bbox`. У адресного PDF без рамки отображается текстовый фрагмент, если API возвращает его. Прогресс обработки в очереди использует отдельный счётчик сервера.

Проверки 14.11.2026. Прошли `pnpm lint`, проверка типов, обычная и публичная сборки, 143 теста Vitest и 61 тест Playwright. Браузерные сценарии включают задержанные ответы статуса и результата, независимое отключение типов, дубли рамок, переходы по адресам, сохранение состояния просмотра и доступность кнопок на узком экране. Передача 1 МиБ в локальный тестовый HTTP-сервис в Chromium показала промежуточные проценты и ожидание подтверждения на 100%. Два прогона v3.2 с синтетическими XLSX и DOCX через локальный API и PostgreSQL прошли от отправки до открытия подсвеченного DOCX. В расширении Brave проверены сохранённые XLSX и DOCX и независимое отключение договора.

Снимки Chromium на синтетических данных. [DOCX до, 1440 px](media/nrt-107-viewer-loading/before-docx-1440.png) · [DOCX после, 1440 px](media/nrt-107-viewer-loading/after-docx-1440.png) · [768 px](media/nrt-107-viewer-loading/after-docx-768.png) · [390 px](media/nrt-107-viewer-loading/after-docx-390.png) · [Полоса загрузки на 390 px](media/nrt-107-viewer-loading/upload-progress-390.png) · [Скелетон результата на 1440 px](media/nrt-107-viewer-loading/result-skeleton-1440.png).
