"""Account snapshots use only the accounts sheet and replace stale values."""
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from tinvest_sync import sheets as sheets_module
from tinvest_sync.api import Account
from tinvest_sync.sheets import SheetsClient


HEADERS = ["updated_at", "account_id", "account_name", "account_type", "status",
           "opened_date", "closed_date", "access_level"]
OPEN = Account("a", "Broker", "ACCOUNT_TYPE_TINKOFF", "ACCOUNT_STATUS_OPEN",
               "2020-01-01T00:00:00Z", None, "ACCOUNT_ACCESS_LEVEL_READ_ONLY")
CLOSED = Account("b", "IIS", "ACCOUNT_TYPE_TINKOFF_IIS", "ACCOUNT_STATUS_CLOSED",
                 "2021-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
                 "ACCOUNT_ACCESS_LEVEL_FULL_ACCESS")


@pytest.fixture
def snapshot_client(monkeypatch):
    clock = Mock()
    clock.now.return_value = datetime(2026, 10, 3, 9, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(sheets_module, "datetime", clock)
    client = SheetsClient.__new__(SheetsClient)
    client._spreadsheet_id = "test-sheet"
    client._service = Mock()
    client._service.get.return_value.execute.return_value = {"sheets": [
        {"properties": {"title": "operations", "sheetId": 1,
                        "gridProperties": {"rowCount": 1000, "columnCount": 12}}},
        {"properties": {"title": "accounts", "sheetId": 2,
                        "gridProperties": {"rowCount": 1000, "columnCount": 8}}},
    ]}
    return client, client._service, clock


def written_rows(service):
    update = service.batchUpdate.call_args.kwargs["body"]["requests"][-1]["updateCells"]
    return [[cell["userEnteredValue"]["stringValue"] for cell in row["values"]]
            for row in update["rows"]]


def test_headers_all_fields_sorting_and_one_utc_timestamp(snapshot_client):
    client, service, clock = snapshot_client
    client.replace_accounts(iter([CLOSED, OPEN]))
    assert written_rows(service) == [HEADERS,
        ["2026-10-03T09:30:00+00:00", "a", "Broker", "ACCOUNT_TYPE_TINKOFF",
         "ACCOUNT_STATUS_OPEN", "2020-01-01T00:00:00Z", "", "ACCOUNT_ACCESS_LEVEL_READ_ONLY"],
        ["2026-10-03T09:30:00+00:00", "b", "IIS", "ACCOUNT_TYPE_TINKOFF_IIS",
         "ACCOUNT_STATUS_CLOSED", "2021-01-01T00:00:00Z", "2024-01-01T00:00:00Z",
         "ACCOUNT_ACCESS_LEVEL_FULL_ACCESS"],
    ]
    clock.now.assert_called_once_with(timezone.utc)


def test_missing_optional_fields_are_empty_strings(snapshot_client):
    client, service, _ = snapshot_client
    client.replace_accounts([Account("a", "Broker", "broker")])
    assert written_rows(service)[1][4:] == ["", "", "", ""]


def test_creates_accounts_sheet_when_missing(snapshot_client):
    client, service, _ = snapshot_client
    service.get.return_value.execute.return_value["sheets"].pop()
    service.batchUpdate.return_value.execute.return_value = {"replies": [
        {"addSheet": {"properties": {"sheetId": 42, "title": "accounts",
                                   "gridProperties": {"rowCount": 1000, "columnCount": 8}}}},
    ]}
    client.replace_accounts([OPEN])
    creation = service.batchUpdate.call_args_list[0].kwargs["body"]["requests"]
    assert creation == [{"addSheet": {"properties": {"title": "accounts",
                       "gridProperties": {"rowCount": 1000, "columnCount": 8}}}}]
    update = service.batchUpdate.call_args.kwargs["body"]["requests"][0]["updateCells"]
    assert update["range"]["sheetId"] == 42
    assert written_rows(service)[0] == HEADERS


@pytest.mark.parametrize("accounts", [[OPEN], []])
def test_replaces_old_rows_and_preserves_operations(snapshot_client, accounts):
    client, service, _ = snapshot_client
    operations = [["date", "operation_id"], ["2024-01-01", "keep-me"]]
    stored = {1: operations.copy(), 2: [["old headers"], ["old account"], ["stale tail"]]}

    def apply_batch():
        requests = service.batchUpdate.call_args.kwargs["body"]["requests"]
        assert len(requests) == 1
        update = requests[0]["updateCells"]
        # Contract: uncovered cells in range are cleared for the specified fields.
        assert update["range"] == {"sheetId": 2, "startRowIndex": 0,
                                   "startColumnIndex": 0, "endColumnIndex": 8}
        assert update["fields"] == "userEnteredValue"
        stored[2] = written_rows(service)
        return {}

    service.batchUpdate.return_value.execute.side_effect = apply_batch
    client.replace_accounts(accounts)
    assert stored[2][0] == HEADERS
    assert len(stored[2]) == len(accounts) + 1
    assert stored[1] == operations
    service.values.assert_not_called()
    service.batchUpdate.assert_called_once()


def test_grows_small_accounts_grid_before_replacement(snapshot_client):
    client, service, _ = snapshot_client
    service.get.return_value.execute.return_value["sheets"][1]["properties"]["gridProperties"] = {
        "rowCount": 1, "columnCount": 4,
    }
    client.replace_accounts([OPEN, CLOSED])
    requests = service.batchUpdate.call_args.kwargs["body"]["requests"]
    assert requests[:2] == [
        {"appendDimension": {"sheetId": 2, "dimension": "ROWS", "length": 2}},
        {"appendDimension": {"sheetId": 2, "dimension": "COLUMNS", "length": 4}},
    ]
    assert "updateCells" in requests[2]


def test_snapshot_write_error_is_not_hidden(snapshot_client):
    client, service, _ = snapshot_client
    service.batchUpdate.return_value.execute.side_effect = RuntimeError("write failed")
    with pytest.raises(RuntimeError, match="write failed"):
        client.replace_accounts([OPEN])
