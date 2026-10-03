"""Service-level tests with mocked API and Sheets clients."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from tinvest_sync import sync_service
from tinvest_sync.api import Account, Operation, Position, TInvestAPIError
from tinvest_sync.config import Settings
from tinvest_sync.sync_service import SyncResult, sync_operations


FROM = datetime(2024, 1, 1, tzinfo=timezone.utc)
A = Account("a", "Broker", "ACCOUNT_TYPE_TINKOFF", "ACCOUNT_STATUS_OPEN")
B = Account("b", "IIS", "ACCOUNT_TYPE_TINKOFF_IIS", "ACCOUNT_STATUS_OPEN")


def operation(identifier, account=A):
    return Operation(identifier, account.id, account.name, "2024-01-02 00:00:00",
                     "OPERATION_TYPE_BUY", "TEST", 1, 100.0, -100.0, -1.0, "rub", "Buy")


@pytest.fixture
def clients(monkeypatch):
    api, sheets = Mock(), Mock()
    api.get_accounts.return_value = [A, B]
    api.get_portfolio.return_value = []
    api.iter_operations.side_effect = lambda account, date_from: iter([])
    sheets.get_existing_operation_ids.return_value = set()
    sheets.get_last_operation_dates_by_account.return_value = {}
    sheets.append_operations.side_effect = lambda operations: len(operations)
    api_factory, sheets_factory = Mock(return_value=api), Mock(return_value=sheets)
    monkeypatch.setattr(sync_service, "TInvestClient", api_factory)
    monkeypatch.setattr(sync_service, "SheetsClient", sheets_factory)
    settings = Settings("test-token", "test-sheet", Path("not-read.json"), verify_ssl=False)
    return settings, api, sheets, api_factory, sheets_factory


def test_multiple_accounts_existing_and_new_operations_and_statistics(clients):
    settings, api, sheets, api_factory, sheets_factory = clients
    old, first, second = operation("old"), operation("new-a"), operation("new-b", B)
    pages = {A.id: [old, first, first], B.id: [operation("old", B), second]}
    api.iter_operations.side_effect = lambda account, date_from: iter(pages[account.id])
    sheets.get_existing_operation_ids.return_value = {"old"}

    result = sync_operations(settings, date_from=FROM)

    assert result == SyncResult(accounts=2, fetched=5, appended=2, skipped_duplicates=3)
    sheets.append_operations.assert_called_once_with([first, second])
    sheets.replace_accounts.assert_called_once_with([A, B])
    assert sheets.method_calls[-3:] == [
        ("append_operations", ([first, second],), {}),
        ("replace_accounts", ([A, B],), {}),
        ("replace_positions", ([], [A, B]), {}),
    ]
    assert api.iter_operations.call_args_list[0].args == (A, FROM)
    assert api.iter_operations.call_args_list[1].args == (B, FROM)
    api_factory.assert_called_once_with("test-token", verify_ssl=False)
    sheets_factory.assert_called_once_with("test-sheet", settings.service_account_file)
    sheets.ensure_sheet.assert_called_once_with()
    sheets.get_existing_operation_ids.assert_called_once_with()
    sheets.get_last_operation_dates_by_account.assert_not_called()


@pytest.mark.parametrize("accounts,items,existing,expected", [
    ([], [], set(), SyncResult(0, 0, 0, 0)),
    ([A], [], set(), SyncResult(1, 0, 0, 0)),
    ([A], [operation("old"), operation("old")], {"old"}, SyncResult(1, 2, 0, 2)),
    ([A], [operation("new")], set(), SyncResult(1, 1, 1, 0)),
])
def test_empty_existing_only_and_new_only(clients, accounts, items, existing, expected):
    settings, api, sheets, _, _ = clients
    api.get_accounts.return_value = accounts
    api.iter_operations.side_effect = lambda account, date_from: iter(items)
    sheets.get_existing_operation_ids.return_value = existing
    assert sync_operations(settings, date_from=FROM) == expected
    sheets.append_operations.assert_called_once_with(items if expected.appended else [])
    sheets.replace_accounts.assert_called_once_with(accounts)


def test_same_id_across_accounts_is_deduplicated_globally(clients):
    """Characterize the current operation_id-only key, without changing it."""
    settings, api, sheets, _, _ = clients
    api.iter_operations.side_effect = lambda account, date_from: iter([operation("shared", account)])
    assert sync_operations(settings, date_from=FROM) == SyncResult(2, 2, 1, 1)
    sheets.append_operations.assert_called_once_with([operation("shared", A)])


def test_empty_operation_ids_currently_drop_distinct_operations(clients):
    """Known risk: missing IDs are accepted and treated as the same key."""
    settings, api, sheets, _, _ = clients
    api.iter_operations.side_effect = lambda account, date_from: iter([operation("", account)])
    assert sync_operations(settings, date_from=FROM) == SyncResult(2, 2, 1, 1)
    sheets.append_operations.assert_called_once_with([operation("", A)])


def test_api_failure_does_not_append_partial_account_data(clients):
    settings, api, sheets, _, _ = clients
    api.iter_operations.side_effect = [iter([operation("new")]), RuntimeError("API unavailable")]
    with pytest.raises(RuntimeError, match="API unavailable"):
        sync_operations(settings, date_from=FROM)
    sheets.append_operations.assert_not_called()
    sheets.replace_accounts.assert_not_called()


@pytest.mark.parametrize("last_dates,expected", [
    ({A.id: datetime(2024, 2, 3, 12, 30, tzinfo=timezone.utc),
      B.id: datetime(2024, 3, 4, tzinfo=timezone.utc)},
     [datetime(2024, 2, 2, 12, 30, tzinfo=timezone.utc),
      datetime(2024, 3, 3, tzinfo=timezone.utc)]),
    ({A.id: datetime(2024, 2, 3, 12, 30, tzinfo=timezone.utc)},
     [datetime(2024, 2, 2, 12, 30, tzinfo=timezone.utc),
      datetime(2019, 1, 1, tzinfo=timezone.utc)]),
    ({}, [datetime(2019, 1, 1, tzinfo=timezone.utc)] * 2),
])
def test_from_last_uses_per_account_overlap_and_fallback(clients, last_dates, expected):
    settings, api, sheets, _, _ = clients
    sheets.get_last_operation_dates_by_account.return_value = last_dates
    sync_operations(settings, use_last_sheet_date=True)
    assert [call.args for call in api.iter_operations.call_args_list] == [
        (A, expected[0]), (B, expected[1]),
    ]
    sheets.get_last_operation_dates_by_account.assert_called_once_with()


def test_explicit_start_date_takes_priority_over_from_last(clients):
    settings, api, sheets, _, _ = clients
    sheets.get_last_operation_dates_by_account.return_value = {
        A.id: datetime(2024, 2, 3, tzinfo=timezone.utc),
    }
    sync_operations(settings, date_from=FROM, use_last_sheet_date=True)
    assert [call.args for call in api.iter_operations.call_args_list] == [(A, FROM), (B, FROM)]
    sheets.get_last_operation_dates_by_account.assert_not_called()


def test_default_start_date(clients):
    settings, api, sheets, _, _ = clients
    settings = Settings(settings.tinvest_token, settings.spreadsheet_id,
                        settings.service_account_file, default_from_date="2020-05-06")
    sheets.get_last_operation_dates_by_account.return_value = {
        A.id: datetime(2024, 2, 3, tzinfo=timezone.utc),
    }
    sync_operations(settings)
    assert [call.args[1] for call in api.iter_operations.call_args_list] == [
        datetime(2020, 5, 6, tzinfo=timezone.utc),
        datetime(2020, 5, 6, tzinfo=timezone.utc),
    ]
    sheets.get_last_operation_dates_by_account.assert_not_called()


@pytest.mark.parametrize("closed_has_watermark", [False, True])
def test_from_last_skips_closed_account_and_preserves_existing_operations(clients, closed_has_watermark):
    settings, api, sheets, _, _ = clients
    closed = Account("closed", "Closed IIS", "ACCOUNT_TYPE_TINKOFF_IIS", "ACCOUNT_STATUS_CLOSED")
    accounts = [A, closed, B]
    api.get_accounts.return_value = accounts
    last_date = datetime(2024, 2, 3, tzinfo=timezone.utc)
    sheets.get_last_operation_dates_by_account.return_value = {A.id: last_date}
    if closed_has_watermark:
        sheets.get_last_operation_dates_by_account.return_value[closed.id] = last_date
    sheets.get_existing_operation_ids.return_value = {"closed-history", "existing-open"}
    new = operation("new", B)
    api.iter_operations.side_effect = lambda account, date_from: iter(
        [operation("existing-open", A)] if account == A else [new]
    )

    assert sync_operations(settings, use_last_sheet_date=True) == SyncResult(3, 2, 1, 1)
    sheets.get_last_operation_dates_by_account.assert_called_once_with()
    assert api.get_portfolio.call_args_list == [call(A), call(B)]
    assert api.iter_operations.call_args_list == [
        call(A, datetime(2024, 2, 2, tzinfo=timezone.utc)),
        call(B, datetime(2019, 1, 1, tzinfo=timezone.utc)),
    ]
    assert sheets.method_calls == [
        call.ensure_sheet(), call.get_last_operation_dates_by_account(),
        call.get_existing_operation_ids(), call.append_operations([new]),
        call.replace_accounts(accounts), call.replace_positions([], accounts),
    ]


def test_snapshot_failure_propagates_after_operations_append(clients):
    settings, api, sheets, _, _ = clients
    api.get_accounts.return_value = [A]
    new = operation("new")
    api.iter_operations.side_effect = lambda account, date_from: iter([new])
    sheets.replace_accounts.side_effect = RuntimeError("accounts write failed")
    with pytest.raises(RuntimeError, match="accounts write failed"):
        sync_operations(settings, date_from=FROM)
    sheets.append_operations.assert_called_once_with([new])
    sheets.replace_accounts.assert_called_once_with([A])


def test_operations_write_failure_does_not_replace_snapshot(clients):
    settings, _, sheets, _, _ = clients
    sheets.append_operations.side_effect = RuntimeError("operations write failed")
    with pytest.raises(RuntimeError, match="operations write failed"):
        sync_operations(settings, date_from=FROM)
    sheets.replace_accounts.assert_not_called()
    sheets.replace_positions.assert_not_called()


def position(account):
    return Position(account.id, "uid", "figi", "TEST", "share",
                    None, None, None, None, None, None)


@pytest.mark.parametrize("count", [1, 2])
def test_open_portfolios_form_one_snapshot_before_sheet_writes(clients, count):
    settings, api, sheets, _, _ = clients
    accounts = [
        Account("open", "Broker", "ACCOUNT_TYPE_TINKOFF", "ACCOUNT_STATUS_OPEN"),
        Account("iis", "IIS", "ACCOUNT_TYPE_TINKOFF_IIS", "ACCOUNT_STATUS_OPEN"),
    ][:count]
    api.get_accounts.return_value = accounts
    api.get_portfolio.side_effect = lambda account: [position(account)]
    timeline = Mock()
    timeline.attach_mock(api, "api")
    timeline.attach_mock(sheets, "sheets")

    assert sync_operations(settings, date_from=FROM) == SyncResult(count, 0, 0, 0)
    assert api.get_portfolio.call_args_list == [call(account) for account in accounts]
    assert api.iter_operations.call_args_list == [call(account, FROM) for account in accounts]
    sheets.replace_positions.assert_called_once_with([position(a) for a in accounts], accounts)
    assert timeline.method_calls[:count + 2] == [
        call.api.get_accounts(), *[call.api.get_portfolio(a) for a in accounts],
        call.sheets.ensure_sheet(),
    ]
    assert timeline.method_calls[-3:] == [
        call.sheets.append_operations([]), call.sheets.replace_accounts(accounts),
        call.sheets.replace_positions([position(a) for a in accounts], accounts),
    ]


@pytest.mark.parametrize("status,account_type", [
    ("ACCOUNT_STATUS_CLOSED", "ACCOUNT_TYPE_TINKOFF"),
    ("ACCOUNT_STATUS_CLOSED", "ACCOUNT_TYPE_TINKOFF_IIS"),
    ("ACCOUNT_STATUS_NEW", "ACCOUNT_TYPE_TINKOFF"),
    ("ACCOUNT_STATUS_OPEN", "ACCOUNT_TYPE_INVEST_BOX"),
    ("ACCOUNT_STATUS_OPEN", "ACCOUNT_TYPE_UNSPECIFIED"),
    ("ACCOUNT_STATUS_OPEN", "FUTURE_ACCOUNT_TYPE"),
    (None, "ACCOUNT_TYPE_TINKOFF"),
    ("ACCOUNT_STATUS_UNSPECIFIED", "ACCOUNT_TYPE_TINKOFF"),
])
@pytest.mark.parametrize("use_last_sheet_date", [False, True])
def test_ineligible_accounts_skip_data_fetches_but_keep_snapshot(
    clients, status, account_type, use_last_sheet_date,
):
    settings, api, sheets, _, _ = clients
    account = Account("other", "Other", account_type, status)
    api.get_accounts.return_value = [account]
    assert sync_operations(settings, use_last_sheet_date=use_last_sheet_date) == SyncResult(1, 0, 0, 0)
    api.get_portfolio.assert_not_called()
    api.iter_operations.assert_not_called()
    sheets.append_operations.assert_called_once_with([])
    sheets.replace_accounts.assert_called_once_with([account])
    sheets.replace_positions.assert_called_once_with([], [account])


def test_empty_open_portfolio_replaces_old_snapshot(clients):
    settings, api, sheets, _, _ = clients
    account = Account("open", "Broker", "ACCOUNT_TYPE_TINKOFF", "ACCOUNT_STATUS_OPEN")
    api.get_accounts.return_value = [account]
    sync_operations(settings, date_from=FROM)
    api.get_portfolio.assert_called_once_with(account)
    sheets.replace_positions.assert_called_once_with([], [account])


def test_second_portfolio_failure_prevents_every_sheet_write(clients):
    settings, api, sheets, _, _ = clients
    accounts = [Account(identifier, identifier, "ACCOUNT_TYPE_TINKOFF", "ACCOUNT_STATUS_OPEN")
                for identifier in ("one", "two")]
    api.get_accounts.return_value = accounts
    api.get_portfolio.side_effect = [[position(accounts[0])], TInvestAPIError("portfolio failed")]
    with pytest.raises(TInvestAPIError, match="portfolio failed"):
        sync_operations(settings, date_from=FROM)
    assert api.get_portfolio.call_count == 2
    # Includes ensure_sheet: no first-run creation or header writes are allowed.
    assert sheets.method_calls == []
    api.iter_operations.assert_not_called()


def test_positions_failure_propagates_after_operations_and_accounts_writes(clients):
    settings, api, sheets, _, _ = clients
    new = operation("new")
    api.iter_operations.side_effect = [iter([new]), iter([])]
    sheets.replace_positions.side_effect = RuntimeError("positions write failed")
    with pytest.raises(RuntimeError, match="positions write failed"):
        sync_operations(settings, date_from=FROM)
    sheets.append_operations.assert_called_once_with([new])
    sheets.replace_accounts.assert_called_once_with([A, B])
    sheets.replace_positions.assert_called_once_with([], [A, B])
