"""Service-level tests with mocked API and Sheets clients."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from tinvest_sync import sync_service
from tinvest_sync.api import Account, Operation, TInvestAPIError
from tinvest_sync.config import Settings
from tinvest_sync.sync_service import SyncResult, sync_operations


FROM = datetime(2024, 1, 1, tzinfo=timezone.utc)
A = Account("a", "Broker", "broker")
B = Account("b", "IIS", "iis")


def operation(identifier, account=A):
    return Operation(identifier, account.id, account.name, "2024-01-02 00:00:00",
                     "OPERATION_TYPE_BUY", "TEST", 1, 100.0, -100.0, -1.0, "rub", "Buy")


@pytest.fixture
def clients(monkeypatch):
    api, sheets = Mock(), Mock()
    api.get_accounts.return_value = [A, B]
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


@pytest.mark.parametrize("other_status", ["ACCOUNT_STATUS_CLOSED", "ACCOUNT_STATUS_NEW"])
def test_sync_processes_other_statuses_the_same_as_open(clients, other_status):
    settings, api, sheets, _, _ = clients
    opened = Account("open", "Broker", "broker", status="ACCOUNT_STATUS_OPEN")
    other = Account("other", "Other", "broker", status=other_status)
    api.get_accounts.return_value = [opened, other]
    operations = [operation("open-operation", opened), operation("other-operation", other)]
    api.iter_operations.side_effect = [iter([operations[0]]), iter([operations[1]])]

    assert sync_operations(settings, date_from=FROM) == SyncResult(2, 2, 2, 0)
    assert [call.args for call in api.iter_operations.call_args_list] == [
        (opened, FROM), (other, FROM),
    ]
    sheets.append_operations.assert_called_once_with(operations)


def test_new_account_api_error_still_aborts_sync_without_append(clients):
    settings, api, sheets, _, _ = clients
    api.get_accounts.return_value = [
        Account("open", "Broker", "broker", status="ACCOUNT_STATUS_OPEN"),
        Account("new", "New", "broker", status="ACCOUNT_STATUS_NEW"),
    ]
    api.iter_operations.side_effect = [iter([operation("one")]), TInvestAPIError("account unavailable")]
    with pytest.raises(TInvestAPIError, match="account unavailable"):
        sync_operations(settings, date_from=FROM)
    assert api.iter_operations.call_count == 2
    sheets.append_operations.assert_not_called()
