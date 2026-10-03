"""
Юнит-тесты на конвертацию дат из Google Sheets (исправление бага
'Invalid isoformat string: 45924,62396').

Никакой реальной сети — SheetsClient создаётся напрямую через __new__,
минуя __init__ (который требует реальные credentials), а _service подменяется
заглушкой.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tinvest_sync.sheets import SheetsClient, _normalize_sheet_date


class TestNormalizeSheetDate:
    def test_known_reference_serial(self):
        """Контрольное значение: 1 января 2024 -> serial 45292."""
        assert _normalize_sheet_date(45292) == "2024-01-01 00:00:00"

    def test_serial_with_fractional_time(self):
        """Дробная часть serial -- это время суток."""
        result = _normalize_sheet_date(45924.62396)
        assert result == "2025-09-24 14:58:30"

    def test_int_serial(self):
        result = _normalize_sheet_date(45292)
        assert result == "2024-01-01 00:00:00"

    def test_string_value_passthrough(self):
        """Если ячейка хранит обычный текст -- используем как есть."""
        assert _normalize_sheet_date("2024-01-01 00:00:00") == "2024-01-01 00:00:00"

    def test_string_with_whitespace_stripped(self):
        assert _normalize_sheet_date("  2024-01-01 00:00:00  ") == "2024-01-01 00:00:00"

    def test_empty_string_returns_none(self):
        assert _normalize_sheet_date("") is None

    def test_none_returns_none(self):
        assert _normalize_sheet_date(None) is None

    def test_original_bug_value_no_longer_crashes(self):
        """
        Раньше API Sheets с локалью таблицы отдавал '45924,62396' (запятая
        вместо точки), что ломало datetime.fromisoformat. Теперь при
        UNFORMATTED_VALUE это приходит как float 45924.62396, без запятой.
        """
        result = _normalize_sheet_date(45924.62396)
        # Проверяем, что результат -- валидная ISO-строка, которую
        # parse_from_date сможет распарсить дальше по цепочке.
        parsed = datetime.fromisoformat(result)
        assert parsed.year == 2025
        assert parsed.month == 9
        assert parsed.day == 24


class _FakeValuesResource:
    """Минимальная заглушка google sheets values().get().execute()."""

    def __init__(self, response: dict):
        self._response = response
        self.last_call_kwargs: dict | None = None
        self.get_calls = 0

    def get(self, **kwargs):
        self.last_call_kwargs = kwargs
        self.get_calls += 1
        return self

    def execute(self):
        return self._response


class _FakeSpreadsheetsResource:
    def __init__(self, values_resource: _FakeValuesResource):
        self._values_resource = values_resource

    def values(self):
        return self._values_resource


class TestGetLastOperationDatesByAccount:
    def _make_client(self, response: dict) -> tuple[SheetsClient, _FakeValuesResource]:
        client = SheetsClient.__new__(SheetsClient)
        fake_values = _FakeValuesResource(response)
        client._service = _FakeSpreadsheetsResource(fake_values)
        client._spreadsheet_id = "fake-id"
        return client, fake_values

    def test_uses_unformatted_value_render_option(self):
        """Критично: без этого баг с локалью таблицы вернётся."""
        client, fake_values = self._make_client(
            {"values": [["date", "account_name", "account_id"], [45292, "Broker", "a"]]}
        )
        client.get_last_operation_dates_by_account()
        assert fake_values.last_call_kwargs["valueRenderOption"] == "UNFORMATTED_VALUE"
        assert fake_values.last_call_kwargs["range"] == "operations!A:C"
        assert fake_values.get_calls == 1

    def test_picks_max_date_among_serials(self):
        client, _ = self._make_client(
            {"values": [["date", "account_name", "account_id"],
                        [45292, "Broker", "a"], [45924.62396, "Broker", "a"],
                        [45300, "Broker", "a"], [45292, "IIS", "b"]]}
        )
        assert client.get_last_operation_dates_by_account() == {
            "a": datetime(2025, 9, 24, 14, 58, 30, tzinfo=timezone.utc),
            "b": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

    def test_empty_sheet_returns_empty_mapping(self):
        client, _ = self._make_client({"values": [["date"]]})
        assert client.get_last_operation_dates_by_account() == {}

    def test_no_values_at_all_returns_empty_mapping(self):
        client, _ = self._make_client({"values": []})
        assert client.get_last_operation_dates_by_account() == {}

    def test_skips_empty_rows(self):
        client, _ = self._make_client(
            {"values": [["date"], [45292, "Broker", "a"], [], [""],
                        ["", "IIS", "b"], [45292, "IIS", ""]]}
        )
        assert client.get_last_operation_dates_by_account() == {
            "a": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

    @pytest.mark.parametrize("invalid", [
        None, "", "  ", "not-a-date", "45924,62396", "2024-02-30",
        True, {}, [], float("nan"), float("inf"), 1e100,
    ])
    def test_invalid_dates_do_not_break_other_accounts(self, invalid):
        client, _ = self._make_client({"values": [
            ["date", "account_name", "account_id"],
            [invalid, "Broker", "a"], [45292, "Broker", "a"],
            [invalid, "Invalid only", "c"], [45300, "IIS", "b"],
        ]})
        assert client.get_last_operation_dates_by_account() == {
            "a": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "b": datetime(2024, 1, 9, tzinfo=timezone.utc),
        }

    @pytest.mark.parametrize("invalid", [None, "", "  ", True, 123.5, float("nan"), float("inf"), {}, []])
    def test_invalid_account_ids_are_skipped(self, invalid):
        client, _ = self._make_client({"values": [
            ["date", "account_name", "account_id"],
            [45924, "Invalid", invalid], [45292, "Broker", "a"],
        ]})
        assert client.get_last_operation_dates_by_account() == {
            "a": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }

    def test_numeric_account_ids_from_user_entered_cells(self):
        client, _ = self._make_client({"values": [
            ["date", "account_name", "account_id"],
            [45292, "Broker", 1234567890],
            [45300, "Broker", 1234567890.0],
            [45293, "IIS", " 9876543210 "],
        ]})
        assert client.get_last_operation_dates_by_account() == {
            "1234567890": datetime(2024, 1, 9, tzinfo=timezone.utc),
            "9876543210": datetime(2024, 1, 2, tzinfo=timezone.utc),
        }

    def test_text_dates_are_compared_as_utc_datetimes(self):
        client, _ = self._make_client({"values": [
            ["date", "account_name", "account_id"],
            ["2024-01-02T00:30:00+03:00", "Broker", "a"],
            [" 2024-01-01 22:00:00 ", "Broker", "a"],
            ["2024-01-03T01:00:00Z", "IIS", "b"],
            ["2024-01-01", "IIS", "b"],
        ]})
        assert client.get_last_operation_dates_by_account() == {
            "a": datetime(2024, 1, 1, 22, tzinfo=timezone.utc),
            "b": datetime(2024, 1, 3, 1, tzinfo=timezone.utc),
        }
