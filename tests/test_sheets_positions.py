"""Position snapshots preserve Decimal text and clear stale data independently."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest

from tinvest_sync import sheets as sheets_module
from tinvest_sync.api import Account, Position
from tinvest_sync.sheets import SheetsClient


HEADERS = ["updated_at", "account_id", "account_name", "instrument_uid", "figi",
           "ticker", "instrument_type", "quantity", "quantity_lots", "currency",
           "current_price", "average_position_price", "expected_yield"]
ACCOUNT = Account("a", "Broker", "ACCOUNT_TYPE_TINKOFF", "ACCOUNT_STATUS_OPEN")
POSITION = Position("a", "uid", "figi", "SBER", "share", Decimal("10.125"),
                    Decimal("1.0125"), Decimal("101.000000001"),
                    Decimal("102.25"), Decimal("-12.625"), "rub")


@pytest.fixture
def snapshot_client(monkeypatch):
    clock = Mock()
    clock.now.return_value = datetime(2026, 10, 3, 9, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(sheets_module, "datetime", clock)
    client = SheetsClient.__new__(SheetsClient)
    client._spreadsheet_id = "test-sheet"
    client._service = Mock()
    client._service.get.return_value.execute.return_value = {"sheets": [
        {"properties": {"title": title, "sheetId": sheet_id,
                        "gridProperties": {"rowCount": 1000, "columnCount": columns}}}
        for title, sheet_id, columns in [("operations", 1, 12), ("accounts", 2, 8), ("positions", 3, 13)]
    ]}
    return client, client._service, clock


def update_cells(service):
    return service.batchUpdate.call_args.kwargs["body"]["requests"][-1]["updateCells"]


def written_rows(service):
    return [[cell["userEnteredValue"]["stringValue"] for cell in row["values"]]
            for row in update_cells(service)["rows"]]


def test_headers_mapping_decimal_text_and_timestamp(snapshot_client):
    client, service, clock = snapshot_client
    client.replace_positions(iter([POSITION]), iter([ACCOUNT]))
    assert written_rows(service) == [HEADERS, [
        "2026-10-03T09:30:00+00:00", "a", "Broker", "uid", "figi", "SBER", "share",
        "10.125", "1.0125", "rub", "101.000000001", "102.25", "-12.625",
    ]]
    clock.now.assert_called_once_with(timezone.utc)
    assert all(set(cell["userEnteredValue"]) == {"stringValue"}
               for row in update_cells(service)["rows"] for cell in row["values"])
    service.values.assert_not_called()


def test_none_is_empty_but_zero_is_preserved(snapshot_client):
    client, service, _ = snapshot_client
    position = Position("a", None, None, None, None, Decimal(0), None, None, None, None, None)
    client.replace_positions([position], [ACCOUNT])
    assert written_rows(service)[1][3:] == ["", "", "", "", "0", "", "", "", "", ""]


def test_decimal_large_and_small_values_are_exact_fixed_point_text(snapshot_client):
    client, service, _ = snapshot_client
    position = replace(POSITION, quantity=Decimal("9223372036854775807.999999999"),
                       current_price=Decimal("1E-9"), expected_yield=Decimal("-1E-9"))
    client.replace_positions([position], [ACCOUNT])
    row = written_rows(service)[1]
    assert row[7] == "9223372036854775807.999999999"
    assert row[10] == "0.000000001"
    assert row[12] == "-0.000000001"


def test_sorting_all_keys_and_common_timestamp(snapshot_client):
    client, service, clock = snapshot_client
    positions = [
        replace(POSITION, account_id="b"),
        replace(POSITION, ticker="ZZZ"),
        replace(POSITION, instrument_uid="z"),
        replace(POSITION, figi="zzz"),
        POSITION,
        replace(POSITION, ticker=None, instrument_uid=None, figi=None),
    ]
    accounts = [ACCOUNT, Account("b", "IIS", "ACCOUNT_TYPE_TINKOFF_IIS")]
    client.replace_positions(reversed(positions), accounts)
    rows = written_rows(service)[1:]
    keys = [(row[1], row[5], row[3], row[4]) for row in rows]
    assert keys == [
        ("a", "", "", ""), ("a", "SBER", "uid", "figi"),
        ("a", "SBER", "uid", "zzz"), ("a", "SBER", "z", "figi"),
        ("a", "ZZZ", "uid", "figi"), ("b", "SBER", "uid", "figi"),
    ]
    assert {row[0] for row in rows} == {"2026-10-03T09:30:00+00:00"}
    assert rows[-1][2] == "IIS"
    clock.now.assert_called_once_with(timezone.utc)


@pytest.mark.parametrize("positions", [[POSITION], []])
def test_creates_positions_sheet_and_headers(snapshot_client, positions):
    client, service, _ = snapshot_client
    service.get.return_value.execute.return_value["sheets"].pop()
    service.batchUpdate.return_value.execute.return_value = {"replies": [
        {"addSheet": {"properties": {"sheetId": 42, "title": "positions",
                                   "gridProperties": {"rowCount": 1000, "columnCount": 13}}}},
    ]}
    client.replace_positions(positions, [ACCOUNT])
    assert service.batchUpdate.call_args_list[0].kwargs["body"]["requests"] == [
        {"addSheet": {"properties": {"title": "positions",
                     "gridProperties": {"rowCount": 1000, "columnCount": 13}}}},
    ]
    assert update_cells(service)["range"]["sheetId"] == 42
    assert written_rows(service)[0] == HEADERS
    assert len(written_rows(service)) == len(positions) + 1


@pytest.mark.parametrize("positions", [[POSITION], []])
def test_replaces_old_tail_and_does_not_touch_other_sheets(snapshot_client, positions):
    client, service, _ = snapshot_client
    stored = {1: [["operation", "keep"]], 2: [["account", "keep"]],
              3: [["old headers"], ["old position"], ["stale tail"]]}

    def apply_batch():
        requests = service.batchUpdate.call_args.kwargs["body"]["requests"]
        assert len(requests) == 1
        update = requests[0]["updateCells"]
        assert update["range"] == {"sheetId": 3, "startRowIndex": 0,
                                   "startColumnIndex": 0, "endColumnIndex": 13}
        assert update["fields"] == "userEnteredValue"
        # Sheets clears uncovered cells within the range when rows run out.
        stored[3] = written_rows(service)
        return {}

    service.batchUpdate.return_value.execute.side_effect = apply_batch
    client.replace_positions(positions, [ACCOUNT])
    assert stored[1] == [["operation", "keep"]]
    assert stored[2] == [["account", "keep"]]
    assert stored[3][0] == HEADERS
    assert len(stored[3]) == len(positions) + 1
    service.values.assert_not_called()


def test_grows_grid_before_replacing(snapshot_client):
    client, service, _ = snapshot_client
    service.get.return_value.execute.return_value["sheets"][2]["properties"]["gridProperties"] = {
        "rowCount": 1, "columnCount": 4,
    }
    client.replace_positions([POSITION, POSITION], [ACCOUNT])
    requests = service.batchUpdate.call_args.kwargs["body"]["requests"]
    assert requests[:2] == [
        {"appendDimension": {"sheetId": 3, "dimension": "ROWS", "length": 2}},
        {"appendDimension": {"sheetId": 3, "dimension": "COLUMNS", "length": 9}},
    ]


def test_write_error_propagates(snapshot_client):
    client, service, _ = snapshot_client
    service.batchUpdate.return_value.execute.side_effect = RuntimeError("positions failed")
    with pytest.raises(RuntimeError, match="positions failed"):
        client.replace_positions([POSITION], [ACCOUNT])
