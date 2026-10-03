"""Offline tests of cursor pagination and operation mapping."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from tinvest_sync.api import Account, Operation, TInvestAPIError, TInvestClient


ACCOUNT = Account("account-1", "Broker", "ACCOUNT_TYPE_TINKOFF")
FROM = datetime(2024, 1, 1, tzinfo=timezone.utc)
TO = datetime(2024, 2, 1, tzinfo=timezone.utc)
METHOD = "tinkoff.public.invest.api.contract.v1.OperationsService/GetOperationsByCursor"


def client_with_pages(monkeypatch, pages):
    client = TInvestClient("test-token")
    post = Mock(side_effect=pages)
    monkeypatch.setattr(client, "_post", post)
    return client, post


def test_multiple_pages_preserve_items_and_send_cursor(monkeypatch):
    client, post = client_with_pages(monkeypatch, [
        {"items": [{"id": "one"}, {"id": "two"}], "hasNext": True, "nextCursor": "page-2"},
        {"items": [{"id": "three"}], "hasNext": True, "nextCursor": "page-3"},
        {"items": [{"id": "four"}], "hasNext": False, "nextCursor": "unused"},
    ])
    operations = list(client.iter_operations(ACCOUNT, FROM, TO))
    assert [op.operation_id for op in operations] == ["one", "two", "three", "four"]
    assert post.call_count == 3
    base = {"accountId": ACCOUNT.id, "from": "2024-01-01T00:00:00Z",
            "to": "2024-02-01T00:00:00Z", "limit": 1000,
            "state": "OPERATION_STATE_EXECUTED", "withoutCommissions": False}
    assert post.call_args_list[0].args == (METHOD, base)
    assert post.call_args_list[1].args == (METHOD, {**base, "cursor": "page-2"})
    assert post.call_args_list[2].args == (METHOD, {**base, "cursor": "page-3"})


@pytest.mark.parametrize("page", [
    {"items": [], "hasNext": False},
    {"items": [{"id": "one"}], "hasNext": False, "nextCursor": "unused"},
    {"items": [{"id": "one"}]},
])
def test_terminal_page_stops_requests(monkeypatch, page):
    client, post = client_with_pages(monkeypatch, [page])
    assert len(list(client.iter_operations(ACCOUNT, FROM, TO))) == len(page["items"])
    post.assert_called_once()


def test_empty_intermediate_page_still_follows_cursor(monkeypatch):
    client, post = client_with_pages(monkeypatch, [
        {"items": [], "hasNext": True, "nextCursor": "next"},
        {"items": [{"id": "one"}], "hasNext": False},
    ])
    assert [op.operation_id for op in client.iter_operations(ACCOUNT, FROM, TO)] == ["one"]
    assert post.call_count == 2


def test_snake_case_pagination_fields(monkeypatch):
    client, post = client_with_pages(monkeypatch, [
        {"items": [{"id": "one"}], "has_next": True, "next_cursor": "next"},
        {"items": [{"id": "two"}], "has_next": False},
    ])
    assert [op.operation_id for op in client.iter_operations(ACCOUNT, FROM, TO)] == ["one", "two"]
    assert post.call_args_list[1].args[1]["cursor"] == "next"


@pytest.mark.parametrize("cursor_fields", [{}, {"nextCursor": ""}, {"nextCursor": None}])
def test_missing_next_cursor_raises_pagination_error(monkeypatch, cursor_fields):
    client, post = client_with_pages(monkeypatch, [
        {"items": [{"id": "one"}], "hasNext": True, **cursor_fields},
    ])
    with pytest.raises(TInvestAPIError, match="pagination violation:.*nextCursor is missing or empty"):
        list(client.iter_operations(ACCOUNT, FROM, TO))
    post.assert_called_once()


def test_mapping_complete_operation(monkeypatch):
    item = {"id": "trade-1", "date": "2024-01-02T12:30:45.123+03:00",
            "type": "OPERATION_TYPE_BUY", "ticker": "TEST", "quantity": "2",
            "price": {"units": "100", "nano": 500000000, "currency": "RUB"},
            "payment": {"units": "-201", "nano": 0, "currency": "RUB"},
            "commission": {"units": "0", "nano": -250000000, "currency": "RUB"},
            "description": "Buy", "name": "Fallback"}
    client, _ = client_with_pages(monkeypatch, [{"items": [item], "hasNext": False}])
    assert list(client.iter_operations(ACCOUNT, FROM, TO)) == [Operation(
        "trade-1", ACCOUNT.id, ACCOUNT.name, "2024-01-02 09:30:45",
        "OPERATION_TYPE_BUY", "TEST", 2, 100.5, -201.0, -0.25, "rub", "Buy",
    )]


@pytest.mark.parametrize("item,expected_date,expected_quantity,expected_description", [
    ({"id": "one"}, "", 0, ""),
    ({"id": "one", "date": {"seconds": "1704067200"}, "quantity": 3, "name": "Fallback"},
     "2024-01-01 00:00:00", 3, "Fallback"),
    ({"id": "one", "date": "2024-01-02T01:02:03Z", "quantity": "", "description": "", "name": "Fallback"},
     "2024-01-02 01:02:03", 0, "Fallback"),
])
def test_mapping_optional_fields(monkeypatch, item, expected_date, expected_quantity, expected_description):
    client, _ = client_with_pages(monkeypatch, [{"items": [item]}])
    operation, = client.iter_operations(ACCOUNT, FROM, TO)
    assert operation.date == expected_date
    assert operation.quantity == expected_quantity
    assert operation.description == expected_description
    assert operation.ticker == ""
    assert (operation.price, operation.payment, operation.commission) == (None, None, None)
    assert operation.currency == "rub"


def test_request_dates_are_normalized_to_utc(monkeypatch):
    client, post = client_with_pages(monkeypatch, [{"items": []}])
    local = datetime(2024, 1, 1, 3, tzinfo=timezone(timedelta(hours=3)))
    list(client.iter_operations(ACCOUNT, local, TO.replace(tzinfo=None)))
    assert post.call_args.args[1]["from"] == "2024-01-01T00:00:00Z"
    assert post.call_args.args[1]["to"] == "2024-02-01T00:00:00Z"


@pytest.mark.parametrize("cursors", [("same", "same"), ("first", "second", "first")])
def test_repeated_cursor_raises_before_another_request(monkeypatch, cursors):
    client, post = client_with_pages(monkeypatch, [
        {"items": [{"id": str(index)}], "hasNext": True, "nextCursor": cursor}
        for index, cursor in enumerate(cursors)
    ])
    with pytest.raises(TInvestAPIError, match="pagination violation:.*has already been used"):
        list(client.iter_operations(ACCOUNT, FROM, TO))
    assert post.call_count == len(cursors)


def test_terminal_page_allows_previously_used_cursor(monkeypatch):
    client, post = client_with_pages(monkeypatch, [
        {"items": [{"id": "one"}], "hasNext": True, "nextCursor": "same"},
        {"items": [{"id": "two"}], "hasNext": False, "nextCursor": "same"},
    ])
    assert [op.operation_id for op in client.iter_operations(ACCOUNT, FROM, TO)] == ["one", "two"]
    assert post.call_count == 2
