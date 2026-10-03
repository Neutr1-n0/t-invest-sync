"""Offline tests against PortfolioPosition's REST camelCase contract."""
from decimal import Decimal, localcontext
from unittest.mock import Mock

import pytest

from tinvest_sync.api import Account, Position, TInvestAPIError, TInvestClient
from tinvest_sync.money import money_to_decimal


ACCOUNT = Account("account-1", "Broker", "ACCOUNT_TYPE_TINKOFF", status="ACCOUNT_STATUS_OPEN")
METHOD = "tinkoff.public.invest.api.contract.v1.OperationsService/GetPortfolio"


def load(monkeypatch, response, account=ACCOUNT):
    client = TInvestClient("test-token")
    post = Mock(return_value=response)
    monkeypatch.setattr(client, "_post", post)
    return client.get_portfolio(account), post


@pytest.mark.parametrize("instrument_type,ticker", [("share", "SBER"), ("etf", "TMOS"), ("bond", "BOND")])
def test_maps_position_and_requests_account(monkeypatch, instrument_type, ticker):
    positions, post = load(monkeypatch, {"positions": [{
        "instrumentUid": "uid-1", "figi": "figi-1", "ticker": ticker,
        "instrumentType": instrument_type,
        "quantity": {"units": "10", "nano": 125000000},
        "quantityLots": {"units": "1", "nano": 12500000},
        "currentPrice": {"currency": "RUB", "units": "101", "nano": 1},
        "averagePositionPrice": {"currency": "rub", "units": "102", "nano": 250000000},
        "expectedYield": {"units": "-12", "nano": -625000000},
    }]})
    post.assert_called_once_with(METHOD, {"accountId": ACCOUNT.id})
    assert positions == [Position(
        ACCOUNT.id, "uid-1", "figi-1", ticker, instrument_type,
        Decimal("10.125"), Decimal("1.0125"), Decimal("101.000000001"),
        Decimal("102.25"), Decimal("-12.625"), "rub",
    )]
    assert isinstance(positions[0].quantity, Decimal)


def test_optional_fields_do_not_invent_values(monkeypatch):
    positions, _ = load(monkeypatch, {"positions": [{"quantity": {}}]})
    assert positions == [Position(ACCOUNT.id, None, None, None, None,
                                  Decimal(0), None, None, None, None, None)]


@pytest.mark.parametrize("response", [{}, {"positions": []}])
def test_empty_portfolio(monkeypatch, response):
    assert load(monkeypatch, response)[0] == []


def test_multiple_positions_do_not_inherit_portfolio_yield_or_virtual_positions(monkeypatch):
    positions, _ = load(monkeypatch, {
        "expectedYield": {"units": "50"},
        "positions": [{"instrumentUid": "one"}, {"instrumentUid": "two"}],
        "virtualPositions": [{"instrumentUid": "virtual"}],
    })
    assert [position.instrument_uid for position in positions] == ["one", "two"]
    assert all(position.expected_yield is None for position in positions)
    assert all(position.quantity is None for position in positions)


@pytest.mark.parametrize("prices,currency", [
    ({"averagePositionPrice": {"currency": "USD", "units": "1"}}, "usd"),
    ({"currentPrice": {"units": "1"}}, None),
    ({"currentPrice": {"currency": "rub"}, "averagePositionPrice": {"currency": "usd"}}, None),
])
def test_currency_comes_only_from_price_money_values(monkeypatch, prices, currency):
    positions, _ = load(monkeypatch, {"positions": [prices]})
    assert positions[0].currency == currency


@pytest.mark.parametrize("status", [None, "ACCOUNT_STATUS_CLOSED", "ACCOUNT_STATUS_NEW",
                                    "ACCOUNT_STATUS_UNSPECIFIED", "UNKNOWN"])
def test_conservative_status_policy_does_not_call_api(monkeypatch, status):
    client = TInvestClient("test-token")
    post = Mock()
    monkeypatch.setattr(client, "_post", post)
    with pytest.raises(ValueError, match="requires an OPEN account"):
        client.get_portfolio(Account("id", "name", "ACCOUNT_TYPE_TINKOFF", status=status))
    post.assert_not_called()


def test_invest_box_does_not_call_api(monkeypatch):
    client = TInvestClient("test-token")
    post = Mock()
    monkeypatch.setattr(client, "_post", post)
    with pytest.raises(ValueError, match="Invest Box"):
        client.get_portfolio(Account("id", "name", "ACCOUNT_TYPE_INVEST_BOX", status="ACCOUNT_STATUS_OPEN"))
    post.assert_not_called()


def test_open_iis_is_supported(monkeypatch):
    account = Account("iis", "IIS", "ACCOUNT_TYPE_TINKOFF_IIS", status="ACCOUNT_STATUS_OPEN")
    _, post = load(monkeypatch, {"positions": []}, account)
    post.assert_called_once_with(METHOD, {"accountId": "iis"})


def test_api_error_is_not_hidden(monkeypatch):
    client = TInvestClient("test-token")
    monkeypatch.setattr(client, "_post", Mock(side_effect=TInvestAPIError("denied")))
    with pytest.raises(TInvestAPIError, match="denied"):
        client.get_portfolio(ACCOUNT)


@pytest.mark.parametrize("value,expected", [
    (None, None), ({}, Decimal(0)),
    ({"currency": "usd", "units": "5", "nano": 1}, Decimal("5.000000001")),
    ({"units": "0", "nano": -1}, Decimal("-0.000000001")),
    ({"units": -2, "nano": -500000000}, Decimal("-2.5")),
])
def test_exact_money_value_and_quotation(value, expected):
    assert money_to_decimal(value) == expected


def test_decimal_mapping_preserves_int64_and_nanos_under_low_context_precision():
    with localcontext() as context:
        context.prec = 6
        actual = money_to_decimal({"units": "9223372036854775807", "nano": 999999999})
    assert actual == Decimal("9223372036854775807.999999999")
