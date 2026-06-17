from __future__ import annotations

from typing import Any


def money_to_float(value: dict[str, Any] | None) -> float | None:
    """Convert T-Invest MoneyValue / Quotation to float."""
    if not value:
        return None

    units = value.get("units", 0)
    nano = value.get("nano", 0)

    if isinstance(units, str):
        units = int(units) if units else 0
    if isinstance(nano, str):
        nano = int(nano) if nano else 0

    return float(units) + float(nano) / 1_000_000_000


def pick_currency(*values: dict[str, Any] | None) -> str:
    for value in values:
        if value and value.get("currency"):
            return str(value["currency"]).lower()
    return "rub"
