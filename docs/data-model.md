# Модель данных и синхронизация

[README: запуск и конфигурация](../README.md) · [Changelog](../CHANGELOG.md)

t-invest-sync переносит данные T-Invest API в Google Sheets. Он предоставляет
историю исполненных операций и текущие snapshots счетов/позиций; аналитические
показатели портфеля отдельно не рассчитываются.

## Account eligibility

GetAccounts запрашивается с `ACCOUNT_STATUS_ALL`. Все возвращённые счета,
включая CLOSED/NEW/Invest Box/unknown, сохраняются в `accounts`.

GetPortfolio и GetOperationsByCursor вызываются только при одновременном
выполнении двух условий:

- status равен `ACCOUNT_STATUS_OPEN`;
- type равен `ACCOUNT_TYPE_TINKOFF` или `ACCOUNT_TYPE_TINKOFF_IIS`.

Остальные счета не участвуют в fetch portfolios/operations и расчёте start date.
Ранее сохранённые operations закрытого счёта остаются в истории.

## Листы и schemas

Ниже columns приведены в точном порядке из [config.py](../tinvest_sync/config.py).
Клиент [sheets.py](../tinvest_sync/sheets.py) создаёт отсутствующие листы.
Другие листы целевой таблицы не изменяются.

### operations

История операций со state `OPERATION_STATE_EXECUTED`. Новые строки добавляются
в конец; уже существующие строки не заменяются и не удаляются. Dedup по
`operation_id` глобальный: охватывает всю сохранённую историю и текущий fetch
всех eligible accounts.

| Column | Значение |
|---|---|
| `date` | Дата операции; API timestamp приводится к UTC и строке `YYYY-MM-DD HH:MM:SS` |
| `account_name` | Имя счёта из GetAccounts |
| `account_id` | ID счёта |
| `type` | Тип операции API |
| `ticker` | Тикер из операции, если присутствует |
| `quantity` | Количество из API |
| `price` | Цена из MoneyValue |
| `payment` | Сумма операции из MoneyValue |
| `commission` | Комиссия из MoneyValue |
| `currency` | Currency из payment, price или commission; fallback `rub` |
| `description` | Description или fallback name из операции |
| `operation_id` | Текущий dedup key |

Существующая конвертация денежных значений operations использует float;
Decimal применяется к positions. Append использует `USER_ENTERED`, поэтому
Sheets может интерпретировать даты и числовые IDs. Заголовки operations
записываются, только если A1 пустая; существующая schema не мигрируется.

### accounts

Полная замена snapshot всех возвращённых GetAccounts счетов.

| Column | Значение |
|---|---|
| `updated_at` | UTC ISO timestamp подготовки этого snapshot к записи |
| `account_id` | ID счёта, текст |
| `account_name` | Имя счёта; fallback на ID при отсутствии имени |
| `account_type` | Тип счёта API |
| `status` | Статус счёта API |
| `opened_date` | openedDate из API, без дополнительного преобразования |
| `closed_date` | closedDate из API, если присутствует |
| `access_level` | Уровень доступа API |

Строки сортируются по account_id. Неизвестные optional поля записываются
пустыми строками. Все ячейки snapshot записываются как текст.

### positions

Полная замена объединённого snapshot actual positions eligible accounts.

| Column | Значение |
|---|---|
| `updated_at` | UTC ISO timestamp подготовки этого snapshot к записи |
| `account_id` | ID счёта, текст |
| `account_name` | Имя из списка accounts |
| `instrument_uid` | instrumentUid из позиции |
| `figi` | FIGI из позиции |
| `ticker` | Тикер из позиции, если присутствует |
| `instrument_type` | instrumentType из API |
| `quantity` | Quantity: units + nano / 1 000 000 000 |
| `quantity_lots` | QuantityLots, только если deprecated поле присутствует в API |
| `currency` | Общая currency currentPrice/averagePositionPrice; пусто при отсутствии или расхождении |
| `current_price` | CurrentPrice в исходных monetary units API |
| `average_position_price` | AveragePositionPrice в исходных monetary units API |
| `expected_yield` | ExpectedYield позиции (Quotation), не процент доходности портфеля |

Quantity и monetary/Quotation values преобразуются через точный Decimal.
В Sheets они записываются строками в fixed-point формате, без scientific
notation и округления через float. Отсутствующее сообщение API становится
пустой ячейкой; присутствующее пустое monetary сообщение означает ноль.

Строки сортируются по account_id, ticker, instrument_uid, figi. Missing optional
поля записываются пустыми строками. `virtualPositions` не сохраняются;
Instruments API lookup не выполняется. Поля `name`, `lot`, `current_value`
и `expected_yield_pct` в этой schema отсутствуют.

### Замена snapshots

Каждый snapshot записывает заголовки и весь актуальный набор строк через
updateCells с `stringValue`. Старые значения ниже нового набора очищаются
в schema columns: A:H для accounts, A:M для positions. Пустой snapshot
оставляет заголовки и очищает предыдущие data rows. Размер листа при
необходимости увеличивается; форматирование и значения вне schema columns
этим запросом не заменяются.

`updated_at` общий для строк одного snapshot, но формируется отдельно для
accounts и positions. Это время подготовки записи, а не единый timestamp
всех API запросов или исторический ряд snapshots.

## Watermarks и from-last

С флагом `--from-last` клиент читает `operations!A:C` как `UNFORMATTED_VALUE`
и вычисляет MAX(date) отдельно по account_id.

1. Serial dates Sheets преобразуются от эпохи 1899-12-30; текстовые даты
   разбираются как ISO datetime. Naive даты считаются UTC, timezone приводится
   к UTC. Неполные или некорректные строки не участвуют в MAX.
2. Account ID приводится к строке: строковые значения очищаются от краевых
   пробелов, целые числовые значения преобразуются в текст. Некорректные
   IDs пропускаются.
3. Eligible account с watermark запрашивается с `MAX(date) - 1 day`.
   Overlap повторно получает пограничные операции, а dedup предотвращает
   повторный append для тех же operation_id.
4. Eligible account без watermark запрашивается с `DEFAULT_FROM_DATE`;
   default — `2019-01-01T00:00:00Z`. Это может означать исторический backfill.
5. Ineligible accounts не участвуют в выборе from-date, даже если старые
   watermarks для них прочитаны из Sheets.

`--from DATE` задаёт explicit start для всех eligible accounts и не читает
Sheets maxima. CLI запрещает сочетать его с `--from-last`. Без обоих флагов
применяется DEFAULT_FROM_DATE. Период не ограничивает accounts/positions:
snapshots всегда текущие. Полная [справка CLI](../README.md#справка-по-флагам).

## API и порядок выполнения

Клиент [api.py](../tinvest_sync/api.py) выполняет REST POST к
`https://invest-public-api.tbank.ru/rest`:

| Метод | Назначение и payload |
|---|---|
| UsersService/GetAccounts | `{status: ACCOUNT_STATUS_ALL}` |
| OperationsService/GetPortfolio | `{accountId: ...}` для каждого eligible account |
| OperationsService/GetOperationsByCursor | accountId, from/to, limit=1000, state=OPERATION_STATE_EXECUTED, withoutCommissions=false; далее cursor |

Все service names имеют prefix `tinkoff.public.invest.api.contract.v1.`.
Operations paginated до `hasNext=false`; при `hasNext=true` без nextCursor
или cursor cycle возникает TInvestAPIError. Терминальная страница может
вернуть прежний cursor: он не используется для нового запроса.

Orchestration в [sync_service.py](../tinvest_sync/sync_service.py):

1. GetAccounts и фильтрация eligible accounts.
2. Все GetPortfolio запросы и mapping positions.
3. ensure_sheet для operations: при необходимости создание листа/заголовков.
4. Чтение watermarks (при --from-last) и существующих operation_id.
5. Fetch всех operations и dedup в памяти.
6. Append новых operations.
7. Replace accounts.
8. Replace positions.

Ошибка GetAccounts/GetPortfolio прерывает запуск до любых записей Sheets.
Operations API failure не допускает append и замену snapshots, но ensure_sheet
к этому моменту уже мог создать лист или заголовки. Ошибки Sheets не скрываются.

CLI summary `счетов` считает все GetAccounts accounts; `получено`, `добавлено`
и `дубликатов` относятся только к operations eligible accounts.

## Ограничения

- `operation_id` остаётся существующим глобальным dedup key, а не надёжным
  долгосрочным primary key. Пустые/повторные IDs могут схлопнуть разные операции.
- Operations append-only: изменения уже сохранённой операции не обновляются.
  Полноценной reconciliation/checkpoint model нет; overlap не гарантирует
  обнаружение поздних изменений за пределами окна. Для абсолютной полноты
  historical operations может потребоваться сверка с broker report.
- Отсутствующий или некорректный watermark приводит к fallback для eligible
  account. Настройка DEFAULT_FROM_DATE не предотвращает такой backfill автоматически.
- Sheets writes последовательные, не транзакционные. Если replace_accounts
  падает после append, operations уже обновлены; если replace_positions падает,
  accounts также могут быть обновлены. Создание листа и его заполнение —
  отдельные запросы, поэтому при ошибке может остаться пустой новый лист.
- Concurrent sync runs не сериализованы. Одновременные процессы могут прочитать
  одинаковый набор IDs и затем добавить одни и те же operations.
- Snapshots полностью заменяются и не сохраняют предыдущие состояния.
  Расчёты и пользовательские данные в управляемых schema columns будут заменены.

Запуск и настройка [Docker/TLS](../README.md#tls-и-ca-bundle),
[GitHub Actions](../README.md#автоматический-запуск-через-github-actions)
и [Google Sheets](../README.md#настройка-google-sheets--пошагово) описаны в README.
