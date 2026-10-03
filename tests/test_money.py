"""Money conversion and currency selection, without external services."""
import pytest

from tinvest_sync.money import money_to_float, pick_currency


@pytest.mark.parametrize("value,expected", [
    (None, None), ({}, None),
    ({"units": 0, "nano": 0}, 0.0),
    ({"units": "12", "nano": "345000000"}, 12.345),
    ({"units": -12, "nano": -345000000}, -12.345),
    ({"units": "0", "nano": -1}, -0.000000001),
    ({"units": 5}, 5.0),
    ({"nano": 500000000}, 0.5),
    ({"units": "", "nano": ""}, 0.0),
])
def test_money_conversion(value, expected):
    actual = money_to_float(value)
    if expected is None:
        assert actual is None
    else:
        assert isinstance(actual, float)
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-15)


@pytest.mark.parametrize("values,expected", [
    ((), "rub"),
    ((None, {}, {"units": "1"}), "rub"),
    (({"currency": "USD"}, {"currency": "RUB"}), "usd"),
    ((None, {"currency": "EUR"}, {"currency": "USD"}), "eur"),
    (({"currency": ""}, None, {"currency": "RUB"}), "rub"),
])
def test_currency_priority_and_fallback(values, expected):
    assert pick_currency(*values) == expected
