"""
Юнит-тесты на конвертацию дат из Google Sheets (исправление бага
'Invalid isoformat string: 45924,62396').

Никакой реальной сети — SheetsClient создаётся напрямую через __new__,
минуя __init__ (который требует реальные credentials), а _service подменяется
заглушкой.
"""
from __future__ import annotations

from datetime import datetime

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

    def get(self, **kwargs):
        self.last_call_kwargs = kwargs
        return self

    def execute(self):
        return self._response


class _FakeSpreadsheetsResource:
    def __init__(self, values_resource: _FakeValuesResource):
        self._values_resource = values_resource

    def values(self):
        return self._values_resource


class TestGetLastOperationDate:
    def _make_client(self, response: dict) -> tuple[SheetsClient, _FakeValuesResource]:
        client = SheetsClient.__new__(SheetsClient)
        fake_values = _FakeValuesResource(response)
        client._service = _FakeSpreadsheetsResource(fake_values)
        client._spreadsheet_id = "fake-id"
        return client, fake_values

    def test_uses_unformatted_value_render_option(self):
        """Критично: без этого баг с локалью таблицы вернётся."""
        client, fake_values = self._make_client(
            {"values": [["date"], [45292]]}
        )
        client.get_last_operation_date()
        assert fake_values.last_call_kwargs["valueRenderOption"] == "UNFORMATTED_VALUE"

    def test_picks_max_date_among_serials(self):
        client, _ = self._make_client(
            {"values": [["date"], [45292], [45924.62396], [45300]]}
        )
        result = client.get_last_operation_date()
        assert result == "2025-09-24 14:58:30"

    def test_empty_sheet_returns_none(self):
        client, _ = self._make_client({"values": [["date"]]})
        assert client.get_last_operation_date() is None

    def test_no_values_at_all_returns_none(self):
        client, _ = self._make_client({"values": []})
        assert client.get_last_operation_date() is None

    def test_skips_empty_rows(self):
        client, _ = self._make_client(
            {"values": [["date"], [45292], [], [""]]}
        )
        result = client.get_last_operation_date()
        assert result == "2024-01-01 00:00:00"
