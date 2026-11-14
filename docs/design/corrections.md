# NRT-62. Исправление в черновике после сверки

Проект для питча и roadmap, 13 ноября 2026 г. На базе
`a61e80c0b41e01c0a96e84b51dcb4e967a80f414` экран и отдельный worker
проводят синтетическое задание через FastAPI и PostgreSQL. Решения по
расхождениям, журнал и редактор черновика здесь ещё не реализованы.
Проект использует семантику результата NRT-85. Маршруты ниже предложены
для согласования с NRT-13. [NRT-62][nrt62] · [Исторический экран](https://github.com/VCyberPunk2077/doccheck/blob/e454fa91978527a5fb0051e3b504a9a37db08d90/frontend/src/pages/home/HomePage.tsx) ·
[API](../../backend/src/doccheck_backend/api.py) · [Контракт результата](../result-source-contract.md) ·
[NRT-13][nrt13]

## Что меняет кнопка

«Применить в черновик» создаёт новую локальную версию черновика отчёта.
Черновик хранит набор изменений к конкретной версии исходной КФЗ. Для
этого проекта достаточно показать черновик в DocCheck. Выгрузка файла
с изменениями относится к дальнейшей работе.
Первичные документы, исходная КФЗ и сохранённый результат сверки доступны
как исходные доказательства. В интерфейсе у результата сверки и черновика
разные идентификаторы и состояния. Исходная строка сохраняет
`discrepancy` после применения. Статус нового отчёта появится только
после отдельной сверки этого отчёта. [Контракт результата](../result-source-contract.md#показатели-и-полнота)

- Карточка FloQast AI Assistant описывает внесение выбранной правки
  в черновик проводки после подтверждения пользователя. TakeControl
  помечает функцию для проводок как Beta. Одобрение проводки и запись
  в ERP описаны в Journal Entry Management. [Карточка][floqast] ·
  [Beta][floqast-beta] · [Проводки][floqast-je]
- Диадок связывает исправленный УПД с исходным. Пользователь отдельно
  подписывает и отправляет документ. BlackLine описывает проверку,
  разделение обязанностей, согласование и журнал при проведении.
  [Диадок][diadoc] · [BlackLine][blackline]
- ABBYY FlexiCapture показывает оператору исходное изображение и
  предлагает проверить распознанные символы. Reporting Service описывает
  статистику обработки и ограничение на сравнение значений до и после.
  Для DocCheck предусмотрен собственный журнал прежних и новых значений.
  [Верификация ABBYY][abbyy] · [Ограничения Reporting Service][abbyy-log] ·
  [Обзор NRT-61](../research/analogs.md#как-применяют-исправление)

## Когда предлагать исправление

В первом сценарии ядро может **автоматически подготовить** предложение
для подтверждённого денежного расхождения в поддерживаемом поле КФЗ.
Применение требует явного действия пользователя. Обработчик проверяет
`discrepancy`, `completeness.state=complete`, подтверждённое
`expected_value`, одно точное место записи в отчёте, валюту и версии
правила и источников. Из строк с `derived_mismatch: true` ядро исключает
самостоятельные предложения, даже когда у зависимой строки есть полный
расчёт и точный адрес. Такие строки пересчитываются и применяются в
одной версии с исправлением причины. Их связывает `root_issue_id`, а
порядок пересчёта определяет правило. При неподтверждённой формуле или
неполном перечне зависимостей исправление передаётся на ручной разбор.
Суммы и зависимые изменения рассчитываются в Python в копейках или
`Decimal`. UI показывает полученные значения.
Неполная наблюдаемая сумма остаётся в исходном результате. [Контракт результата](../result-source-contract.md#показатели-и-полнота) ·
[Допуск слагаемых](../result-source-contract.md#адреса-доказательств-и-допуск-суммы)

| Ситуация | Действие | Основание |
| --- | --- | --- |
| Подтверждённая сумма в КФЗ отличается от полного расчёта, адрес поля и правило известны, `derived_mismatch: false` | Подготовить предложение для строки с причиной и включить в него пересчитанные зависимости. Пользователь принимает предложение и применяет все изменения одной командой | `expected_value` получено из допущенных слагаемых и относится к той же области |
| Зависимый итог с `derived_mismatch: true` | Показать его в предложении для строки с причиной. Пересчитанный итог входит в ту же версию черновика. При неизвестной зависимости показать причину и оставить весь набор изменений для ручного разбора | `root_issue_id` связывает результаты сверки с причиной. Для пересчёта нужна поддерживаемая формула с известными зависимостями |
| OCR исказил значение, источник читается человеком | Открыть точный фрагмент и предложить ручную проверку наблюдения. После подтверждения запустить новую сверку | Исправляется наблюдение с журналом старого и нового чтения. Этот сценарий относится к NRT-52 |
| Не хватает документа или части периода, конфликтуют чтения, договор, статья либо версия | Показать причину `unverified` и известные источники. Запросить документ или ручную проверку | Для предложения требуется полное ожидаемое значение. Неизвестные значения остаются `null` |
| Побайтовая копия, подозрение на дубль, чужой договор или период | Показать решение по файлу и основание. Неоднозначные связи отправить на ручную проверку | Повторный учёт предотвращает обработчик. Изменение состава требует нового прогона |
| Ошибка в первичке или нужна бухгалтерская проводка | Подготовить описание для владельца учёта. Выпуск отдельного исправления или запись в ERP рассматривать после согласования процесса | Первичный документ сохраняется. Внешнее действие требует полномочий, отдельного одобрения и подтверждения результата |
| Сотрудник считает расхождение допустимым | До утверждения политики оставить расхождение и комментарий. Будущая отметка допустимости хранит основание и версию допуска | Решение сотрудника не переписывает исходную сумму и статус уже выполненной сверки |

Сценарий ручной верификации согласуется с NRT-52 после MVP. Выбор между
ним и сравнением прогонов остаётся в этой задаче. [NRT-52][nrt52]

## Предложение, версии и журнал

| Данные | Содержание |
| --- | --- |
| Происхождение | `id`, `run_id`, `result_revision` сохранённого результата, `row_id`, область сверки из результата, `policy_id` и версия правила. ID строк и доказательств разрешаются только в этой версии задания |
| Цель и значения | Поле `reported_value`, ID документа, SHA исходной версии и точный локатор. `changes` содержит основное поле и вычисленные зависимости. `before` берётся из `based_on_draft_version`, `after` вычисляет сервер. Значение `"0.00"` допустимо при подтверждённом нуле |
| Основание и уверенность | Машинная причина предложения, ссылки на отчёт и первичку, правило и оценка `confirmed_evidence` для подтверждённого предложения. Оценка выражает пригодность доказательств. Для OCR можно показывать происхождение и исходный score отдельно, если он доступен. Числовой общий балл в этом проекте отсутствует |
| Состояние и авторство | `status`, `created_at`, `created_by`, версия черновика, на которой создано предложение. Кто, когда и почему принял, отклонил, применил или отменил правку, видно из событий |
| Черновик и события | Версия 0 указывает на исходный отчёт. Следующие версии содержат изменения и ссылку на предыдущую версию. Событие содержит действие, прежнее и новое состояния, серверные ID автора и время UTC, причину, ссылки, версии черновика и результата, ссылку на предложенные значения и ключ повторного запроса. При перевыпуске обе карточки связаны идентификаторами |

Для каждой версии результата используется своя цепочка черновика.
Черновик и предложение наследуют признак `synthetic` от исходной сверки.
Интерфейс показывает этот признак в списке и карточке.
Предложение неизменно в части источников, значений и области. Сервер
проверяет это основание заново при перевыпуске. Изменение статуса, запись
события, создание версии черновика при применении или отмене и сохранение
квитанции выполняются одной транзакцией в PostgreSQL. Перевыпуск сохраняет
старую и новую карточки, связь и событие в одной транзакции. Журнал хранит
идентификаторы, адреса, значения и причины в рамках доступа к заданию.
[Режим данных](../data-policy.md)

## Действия пользователя

1. В карточке расхождения открыть предложение `proposed`. Предпросмотр
   показывает `before` из версии черновика, `after`, формулу, слагаемые и
   ссылки на фрагменты. Исходная сумма видна отдельно по адресу в отчёте.
   Для неподдерживаемых случаев карточка показывает причину, по которой
   предложения нет.
2. «Принять» переводит предложение в `accepted`. «Отклонить» переводит
   `proposed` или `accepted` в `rejected`. Сотрудник указывает причину.
   Оба действия сохраняются в журнале.
3. «Применить в черновик» доступно для `accepted` с действующей версией.
   Сервер повторно проверяет источники, правило, права, исходное значение
   в черновике и версии. Интерфейс показывает ход запроса, затем статус
   `applied`, новую версию черновика и событие. При конфликте версий
   UI загружает актуальное состояние. Если изменилась версия черновика,
   карточка предлагает перевыпуск по правилам ниже.
4. «Отменить применение» для `applied` доступно, пока применённая им
   версия является последней. Сервер создаёт компенсирующую версию
   с прежними значениями, сохраняет обе записи и переводит предложение
   в `reverted`. При наличии более новой версии UI показывает её и причину
   отказа в отмене. `rejected`, `reverted` и `superseded` завершают предложение.

### Перевыпуск на текущую версию

Если `based_on_draft_version` отличается от текущей версии, сервер
отключает `accept` и `apply` для старой карточки. Свежий `ETag` позволяет
выполнить `refresh` для `proposed` или `accepted`. Сервер заново проверяет
адреса и версии источников, правило, пригодность суммы, зависимости и
значения из текущей версии. Проверка требуется и для независимой строки,
когда изменилась только версия черновика. При успехе сервер создаёт
новый ID со статусом `proposed` и текущей базовой версией, переводит
старую карточку в `superseded` и сохраняет событие перевыпуска. Старые
значения, принятие и события видны в истории. Квитанция содержит
`replacement_proposal_id`. UI открывает новый предпросмотр и запрашивает
принятие. Если исправление утратило основание или уже не нужно, сервер
возвращает `409 basis_changed` с пояснением. Пользователь может отклонить
предложение, оставшееся в `proposed` или `accepted`.

Предложения A и B могут относиться к двум независимым строкам одного
итога. На версии 0 строки `"157.00"` и `"30.00"` дают `"187.00"`.
Применение A одной командой меняет первую строку на `"149.50"` и итог
на `"179.50"` в версии 1. Для зависимого итога отдельной карточки нет.
Перевыпущенное B на версии 1 показывает для итога
`"179.50" → "174.50"` после замены второй строки на `"25.00"`.
Если сначала отменить A, сервер создаёт версию 2 с итогом `"187.00"`.
Перевыпуск B на версии 2 покажет `"187.00" → "182.00"`. Если B уже
применено после A, отмена A заблокирована более новой версией.

## Черновик API

OpenAPI 3.1.1 описывает локальные операции. Ядро формирует предложения,
поэтому команда из UI принимает действие и причину. Сервер отдаёт
сильный `ETag` карточки. Тег меняется при изменении видимого состояния,
включая текущую версию черновика. Команда с `If-Match` выполняется в
том же ресурсе и сравнивает тег в транзакции. Для `accept` и `apply`
сервер сверяет `based_on_draft_version` с текущей версией черновика и
проверяет версию результата. Для `refresh` сервер использует текущий
черновик и сохранённую сверку. Для `revert` сверяет текущую версию с той,
которую создало событие `apply`. Попытка `accept` или `apply` со свежим
тегом старой карточки возвращает `409 draft_changed`. [OpenAPI 3.1.1][oas] ·
[RFC 9110, If-Match][if-match] · [RFC 6585, код 428][precondition]

Для команды требуется уникальный ключ `Idempotency-Key` в пределах
пользователя, задания и предложения. После проверки доступа повтор
успешного запроса с тем же ключом, тегом и телом возвращает сохранённую
квитанцию с ID события. Повтор не создаёт новую версию или событие.
Использование ключа с другим тегом или телом даёт `409`. После ответа UI
перечитывает карточку. При перевыпуске он открывает новую карточку по
`replacement_proposal_id`. После `apply` или `revert` UI читает точную
версию черновика через `GET /runs/{run_id}/drafts/{result_revision}/versions/{draft_version}`.
Версия возвращает денежные поля в состоянии на момент её создания.
Параллельные команды по одному черновику сериализуются по его текущей версии.
Сервер проверяет право чтения задания и право на действие. Чужое или
отсутствующее задание возвращает `404`, отсутствие права на изменение
доступного задания — `403`.

~~~yaml
openapi: 3.1.1
info:
  title: DocCheck Corrections Draft
  version: 0.1.0
paths:
  /runs/{run_id}/corrections:
    parameters:
      - $ref: '#/components/parameters/RunId'
    get:
      operationId: listCorrectionProposals
      responses:
        '200':
          description: Предложения сохранённого результата.
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/ProposalSummary'
        '401': {description: Требуется вход.}
        '404': {description: Задание отсутствует или недоступно.}
  /runs/{run_id}/corrections/{proposal_id}:
    parameters:
      - $ref: '#/components/parameters/RunId'
      - name: proposal_id
        in: path
        required: true
        schema: {type: string, minLength: 1}
    get:
      operationId: getCorrectionProposal
      responses:
        '200': {$ref: '#/components/responses/Proposal'}
        '401': {description: Требуется вход.}
        '404': {description: Задание или предложение отсутствует либо недоступно.}
    post:
      operationId: transitionCorrectionProposal
      parameters:
        - name: If-Match
          in: header
          required: true
          description: Один сильный ETag из GET карточки.
          schema: {type: string, minLength: 1}
        - name: Idempotency-Key
          in: header
          required: true
          schema: {type: string, minLength: 1, maxLength: 128}
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/Transition'
            example:
              action: apply
              reason: Сверены оба слагаемых и адрес строки отчёта.
      responses:
        '200':
          description: Квитанция успешного действия, включая повтор того же запроса.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ActionReceipt'
        '400': {description: Некорректный заголовок команды.}
        '401': {description: Требуется вход.}
        '403': {description: Действие запрещено.}
        '404': {description: Задание или предложение отсутствует либо недоступно.}
        '409': {$ref: '#/components/responses/TransitionConflict'}
        '412': {description: Тег карточки устарел. Получите актуальное состояние через GET.}
        '422': {description: Тело запроса не соответствует схеме.}
        '428': {description: Требуется If-Match.}
  /runs/{run_id}/drafts/{result_revision}/versions/{draft_version}:
    parameters:
      - $ref: '#/components/parameters/RunId'
      - name: result_revision
        in: path
        required: true
        schema: {type: string, minLength: 1}
      - name: draft_version
        in: path
        required: true
        schema: {type: integer, minimum: 0}
    get:
      operationId: getCorrectionDraftVersion
      responses:
        '200':
          description: Денежные поля указанной версии черновика.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/DraftVersion'
        '401': {description: Требуется вход.}
        '404': {description: Версия отсутствует или недоступна.}
components:
  parameters:
    RunId:
      name: run_id
      in: path
      required: true
      schema: {type: string, minLength: 1}
  responses:
    Proposal:
      description: Карточка предложения и сохранённые события.
      headers:
        ETag:
          description: Сильный тег возвращённого состояния карточки.
          schema: {type: string}
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Proposal'
    TransitionConflict:
      description: Действие невозможно в текущем состоянии.
      content:
        application/json:
          schema:
            type: object
            required: [code, message]
            properties:
              code:
                type: string
                enum: [invalid_transition, draft_changed, basis_changed, newer_draft_exists, idempotency_key_reused]
              message: {type: string, minLength: 1}
  schemas:
    Status:
      type: string
      enum: [proposed, accepted, rejected, applied, reverted, superseded]
    Action:
      type: string
      enum: [accept, reject, apply, revert, refresh]
    Transition:
      type: object
      additionalProperties: false
      required: [action, reason]
      properties:
        action: {$ref: '#/components/schemas/Action'}
        reason: {type: string, minLength: 1, maxLength: 1000, pattern: '\S'}
    ProposalSummary:
      type: object
      required: [id, row_id, status, synthetic]
      properties:
        id: {type: string, minLength: 1}
        row_id: {type: string, minLength: 1}
        status: {$ref: '#/components/schemas/Status'}
        synthetic: {type: boolean}
    Proposal:
      allOf:
        - $ref: '#/components/schemas/ProposalSummary'
        - type: object
          required:
            - run_id
            - result_revision
            - based_on_draft_version
            - draft_version
            - policy_id
            - rules_version
            - reason
            - confidence
            - changes
            - created_at
            - created_by
            - allowed_actions
            - events
          properties:
            run_id: {type: string, minLength: 1}
            result_revision: {type: string, minLength: 1}
            based_on_draft_version: {type: integer, minimum: 0}
            draft_version: {type: integer, minimum: 0}
            replaces_proposal_id: {type: string, minLength: 1}
            replacement_proposal_id: {type: string, minLength: 1}
            policy_id: {type: string, minLength: 1}
            rules_version: {type: string, minLength: 1}
            reason: {type: string, minLength: 1}
            confidence: {const: confirmed_evidence}
            created_at: {type: string, format: date-time}
            created_by: {type: string, minLength: 1}
            changes:
              type: array
              minItems: 1
              items: {$ref: '#/components/schemas/Change'}
            allowed_actions:
              type: array
              uniqueItems: true
              items: {$ref: '#/components/schemas/Action'}
            events:
              type: array
              items: {$ref: '#/components/schemas/Event'}
          if:
            required: [status]
            properties:
              status: {const: superseded}
          then:
            required: [replacement_proposal_id]
    Change:
      type: object
      required: [row_id, field, unit, before, after, reported_evidence_ref, support_evidence_refs, calculation]
      properties:
        row_id: {type: string, minLength: 1}
        field: {const: reported_value}
        unit: {const: RUB}
        before: {$ref: '#/components/schemas/Money'}
        after: {$ref: '#/components/schemas/Money'}
        reported_evidence_ref: {type: string, minLength: 1}
        support_evidence_refs:
          type: array
          minItems: 1
          items: {type: string, minLength: 1}
        calculation: {$ref: '#/components/schemas/PreviewCalculation'}
    PreviewCalculation:
      type: object
      required: [formula, components]
      properties:
        formula: {type: string, minLength: 1}
        components:
          type: array
          minItems: 1
          items:
            type: object
            required: [label, amount, evidence_refs]
            properties:
              label: {type: string, minLength: 1}
              amount: {$ref: '#/components/schemas/Money'}
              draft_row_id: {type: string, minLength: 1}
              evidence_refs:
                type: array
                minItems: 1
                items: {type: string, minLength: 1}
    DraftVersion:
      type: object
      required: [run_id, result_revision, draft_version, previous_version, synthetic, rows]
      properties:
        run_id: {type: string, minLength: 1}
        result_revision: {type: string, minLength: 1}
        draft_version: {type: integer, minimum: 0}
        previous_version: {type: [integer, 'null'], minimum: 0}
        synthetic: {type: boolean}
        rows:
          type: array
          items:
            type: object
            required: [row_id, label, unit, value, reported_evidence_ref]
            properties:
              row_id: {type: string, minLength: 1}
              label: {type: string, minLength: 1}
              unit: {const: RUB}
              value:
                anyOf:
                  - $ref: '#/components/schemas/Money'
                  - type: 'null'
              reported_evidence_ref: {type: [string, 'null'], minLength: 1}
    Money:
      type: string
      pattern: '^-?(0|[1-9][0-9]*)\.[0-9]{2}(?![\s\S])'
      not: {const: '-0.00'}
    ActionReceipt:
      type: object
      required: [event_id, action, status, result_revision, draft_version]
      properties:
        event_id: {type: string, minLength: 1}
        action: {$ref: '#/components/schemas/Action'}
        status: {$ref: '#/components/schemas/Status'}
        result_revision: {type: string, minLength: 1}
        draft_version: {type: integer, minimum: 0}
        replacement_proposal_id: {type: string, minLength: 1}
      allOf:
        - if:
            properties:
              action: {const: refresh}
          then:
            required: [replacement_proposal_id]
            properties:
              status: {const: superseded}
        - if:
            properties:
              action: {const: apply}
          then:
            properties:
              status: {const: applied}
              draft_version: {minimum: 1}
        - if:
            properties:
              action: {const: revert}
          then:
            properties:
              status: {const: reverted}
              draft_version: {minimum: 1}
    Event:
      type: object
      required: [id, action, actor_id, occurred_at, reason, status_before, status_after, draft_before, draft_after]
      properties:
        id: {type: string, minLength: 1}
        action: {$ref: '#/components/schemas/Action'}
        actor_id: {type: string, minLength: 1}
        occurred_at: {type: string, format: date-time}
        reason: {type: string, minLength: 1}
        status_before: {$ref: '#/components/schemas/Status'}
        status_after: {$ref: '#/components/schemas/Status'}
        draft_before: {type: integer, minimum: 0}
        draft_after: {type: integer, minimum: 0}
        replacement_proposal_id: {type: string, minLength: 1}
~~~

`reported_evidence_ref` разрешается в исходный отчёт, его SHA и
локатор. Он остаётся адресом исходного значения. Значение `before`
сервер берёт из `based_on_draft_version` и сохраняет в предпросмотре.
`calculation.formula` и `calculation.components` описывают серверный
пересчёт для `after`. У суммы из первички есть ссылки на её доказательства.
У компонента зависимого итога `draft_row_id` указывает строку черновика.
Его `amount` учитывает изменения из выбранной версии и из текущего
предложения, а `evidence_refs` ведут к основаниям строки. UI показывает
формулу и слагаемые, а сумму берёт из `after`. Для проверки `before`
можно открыть ту же строку в версии `based_on_draft_version`.

`DraftVersion.rows` возвращает текущее значение каждой денежной строки
в запрошенной исторической версии, включая зависимые итоги. `null`
остаётся неизвестным. `previous_version` у версии 0 равен `null`, у
следующей версии указывает на её предшественника. Квитанция содержит
`result_revision` и точный `draft_version` созданного черновика. Журнал
в карточке сохраняет действия, а для перевыпуска — ссылку на новую карточку.
Формат ошибок и маршруты просмотра доказательств согласуются с NRT-13.
[NRT-13][nrt13]

## Две минуты для демо

- **0:00–0:30.** На макете с пометкой «синтетика» открыть расхождение.
  В вымышленной КФЗ стоит `"157.00"`, два допустимых слагаемых
  `"70.25"` и `"79.25"` дают `"149.50"`, дельта `"7.50"`.
- **0:30–1:10.** Перейти к доказательствам, открыть предпросмотр,
  принять предложение и показать переход черновика с версии 0 на 1.
- **1:10–2:00.** Показать исходное расхождение, запись журнала, отмену
  с версией 2 и отдельную строку `unverified` с неполной первичкой.
  У последней видна причина и нет предложения на замену суммы.

Для MVP применимы экран результата и адресные доказательства из обзора
NRT-61. В roadmap сначала идут ручной разбор и журнал решений, затем
черновики и проверка отмены на разрешённых пакетах. Интеграция
внешней записи зависит от правил доступа, согласования, хранения и
подтверждения операции в системе вуза. [Обзор NRT-61](../research/analogs.md#десять-паттернов-и-приоритеты) ·
[NRT-51][nrt51]

Локальный черновик, переходы, ETag и ограничение отмены последней версией
предложены для технического проекта. До реализации Андрей подтверждает
виды допустимых исправлений и необходимость второго согласования,
Николай — роли и маршруты, Семён — правила для зависимых строк и
проверку источников. Для записи в ERP или ЭДО нужен отдельный сценарий
приёмки. [NRT-62][nrt62]

[nrt62]: https://linear.app/andreiakimov/issue/NRT-62/dizajn-predlozhenie-i-primenenie-ispravlenij-posle-sverki
[nrt13]: https://linear.app/andreiakimov/issue/NRT-13/kontrakt-api-i-moki-dlya-fronta
[nrt51]: https://linear.app/andreiakimov/issue/NRT-51/roadmap-i-plan-vnedreniya-10-ballov
[nrt52]: https://linear.app/andreiakimov/issue/NRT-52/posle-mvp-ruchnaya-proverka-spornyh-znachenij
[floqast]: https://www.floqast.com/close-management/products/ai-assistant
[floqast-beta]: https://www.floqast.com/takecontrol/products
[floqast-je]: https://www.floqast.com/close-ai/products/journal-entry-management
[diadoc]: https://support.kontur.ru/diadoc/40486-ispravlenie_upd
[blackline]: https://www.blackline.com/record-to-report/automated-journal-entries/
[abbyy]: https://help.abbyy.com/en-us/flexicapture/12/standalone_administrator/properties_verification/
[abbyy-log]: https://help.abbyy.com/en-us/flexicapture/12/ReportingServiceGuide/reporting_overview/
[oas]: https://spec.openapis.org/oas/v3.1.1.html
[if-match]: https://www.rfc-editor.org/rfc/rfc9110.html#name-if-match
[precondition]: https://www.rfc-editor.org/rfc/rfc6585.html#section-3
