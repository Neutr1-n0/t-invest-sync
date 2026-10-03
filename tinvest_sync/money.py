from __future__ import annotations

from typing import Any
from decimal import Decimal


def money_to_decimal(value: dict[str, Any] | None) -> Decimal | None:
    """Convert MoneyValue / Quotation exactly, independent of Decimal context.

    An absent message is unknown; a present empty protobuf message is zero.
    """
    if value is None:
        return None
    nanounits = int(value.get("units", 0)) * 1_000_000_000 + int(value.get("nano", 0))
    digits = tuple(int(digit) for digit in str(abs(nanounits)))
    return Decimal((int(nanounits < 0), digits, -9))


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
