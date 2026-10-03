from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterator

import requests

from tinvest_sync.config import API_BASE_URL
from tinvest_sync.money import money_to_decimal, money_to_float, pick_currency


class TInvestAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    type: str
    status: str | None = None
    opened_date: str | None = None
    closed_date: str | None = None
    access_level: str | None = None


@dataclass(frozen=True)
class Position:
    """Actual PortfolioPosition; prices retain their API monetary units.

    expected_yield is the position's Quotation, not portfolio yield percent.
    quantity_lots is mapped only when the deprecated API field is present.
    currency is unknown if price currencies are absent or disagree.
    """

    account_id: str
    instrument_uid: str | None
    figi: str | None
    ticker: str | None
    instrument_type: str | None
    quantity: Decimal | None
    quantity_lots: Decimal | None
    current_price: Decimal | None
    average_position_price: Decimal | None
    expected_yield: Decimal | None
    currency: str | None


@dataclass(frozen=True)
class Operation:
    operation_id: str
    account_id: str
    account_name: str
    date: str
    type: str
    ticker: str
    quantity: int | float
    price: float | None
    payment: float | None
    commission: float | None
    currency: str
    description: str


class TInvestClient:
    def __init__(self, token: str, request_pause_sec: float = 0.2, verify_ssl: bool | str = True) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )
        self._session.verify = verify_ssl
        self._request_pause_sec = request_pause_sec

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{API_BASE_URL}/{method}"
        response = self._session.post(url, json=payload, timeout=60)

        if response.status_code == 429:
            time.sleep(2)
            response = self._session.post(url, json=payload, timeout=60)

        if not response.ok:
            raise TInvestAPIError(
                f"API error {response.status_code} for {method}: {response.text}"
            )

        data = response.json()
        time.sleep(self._request_pause_sec)
        return data

    def get_accounts(self) -> list[Account]:
        data = self._post(
            "tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts",
            {"status": "ACCOUNT_STATUS_ALL"},
        )
        accounts = data.get("accounts", [])
        result: list[Account] = []
        for item in accounts:
            result.append(
                Account(
                    id=item.get("id", ""),
                    name=item.get("name", "") or item.get("id", ""),
                    type=item.get("type", "ACCOUNT_TYPE_UNSPECIFIED"),
                    status=item.get("status"),
                    opened_date=item.get("openedDate"),
                    closed_date=item.get("closedDate"),
                    access_level=item.get("accessLevel"),
                )
            )
        return result

    def get_portfolio(self, account: Account) -> list[Position]:
        """Load actual positions for an OPEN account; do not merge virtual positions.

        OPEN-only is a conservative client policy: documentation does not
        guarantee GetPortfolio availability for other account statuses.
        Invest Box is explicitly unsupported by the Operations service.
        """
        if account.type == "ACCOUNT_TYPE_INVEST_BOX":
            raise ValueError("GetPortfolio does not support Invest Box accounts")
        if account.status != "ACCOUNT_STATUS_OPEN":
            raise ValueError(f"GetPortfolio requires an OPEN account; status={account.status!r}")
        data = self._post(
            "tinkoff.public.invest.api.contract.v1.OperationsService/GetPortfolio",
            {"accountId": account.id},
        )
        return [_map_position(item, account) for item in data.get("positions", [])]

    def iter_operations(
        self,
        account: Account,
        date_from: datetime,
        date_to: datetime | None = None,
    ) -> Iterator[Operation]:
        if date_to is None:
            date_to = datetime.now(timezone.utc)

        cursor = ""
        used_cursors: set[str] = set()
        has_next = True

        while has_next:
            payload: dict[str, Any] = {
                "accountId": account.id,
                "from": _to_api_timestamp(date_from),
                "to": _to_api_timestamp(date_to),
                "limit": 1000,
                "state": "OPERATION_STATE_EXECUTED",
                "withoutCommissions": False,
            }
            if cursor:
                payload["cursor"] = cursor
                used_cursors.add(cursor)

            data = self._post(
                "tinkoff.public.invest.api.contract.v1.OperationsService/GetOperationsByCursor",
                payload,
            )

            items = data.get("items", [])
            for item in items:
                yield _map_operation(item, account)

            has_next = bool(data.get("hasNext", data.get("has_next", False)))
            cursor = data.get("nextCursor", data.get("next_cursor", ""))
            if has_next and not cursor:
                raise TInvestAPIError(
                    "GetOperationsByCursor pagination violation: "
                    "hasNext=true but nextCursor is missing or empty"
                )
            if has_next and cursor in used_cursors:
                raise TInvestAPIError(
                    "GetOperationsByCursor pagination violation: "
                    f"nextCursor {cursor!r} has already been used"
                )


def _map_position(item: dict[str, Any], account: Account) -> Position:
    current_price = item.get("currentPrice")
    average_price = item.get("averagePositionPrice")
    currencies = {
        str(price["currency"]).lower()
        for price in (current_price, average_price)
        if price and price.get("currency")
    }
    return Position(
        account_id=account.id,
        instrument_uid=item.get("instrumentUid") or None,
        figi=item.get("figi") or None,
        ticker=item.get("ticker") or None,
        instrument_type=item.get("instrumentType") or None,
        quantity=money_to_decimal(item.get("quantity")),
        quantity_lots=money_to_decimal(item.get("quantityLots")),
        current_price=money_to_decimal(current_price),
        average_position_price=money_to_decimal(average_price),
        expected_yield=money_to_decimal(item.get("expectedYield")),
        currency=next(iter(currencies)) if len(currencies) == 1 else None,
    )


def _to_api_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: str | dict[str, Any] | None) -> str:
    if not value:
        return ""

    if isinstance(value, dict):
        seconds = value.get("seconds")
        if seconds is not None:
            dt = datetime.fromtimestamp(int(seconds), tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return ""

    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)


def _map_operation(item: dict[str, Any], account: Account) -> Operation:
    payment = item.get("payment")
    price = item.get("price")
    commission = item.get("commission")

    quantity_raw = item.get("quantity", 0)
    quantity: int | float
    if isinstance(quantity_raw, str):
        quantity = int(quantity_raw) if quantity_raw else 0
    else:
        quantity = quantity_raw

    return Operation(
        operation_id=item.get("id", ""),
        account_id=account.id,
        account_name=account.name,
        date=_parse_timestamp(item.get("date")),
        type=str(item.get("type", "")),
        ticker=item.get("ticker", "") or "",
        quantity=quantity,
        price=money_to_float(price),
        payment=money_to_float(payment),
        commission=money_to_float(commission),
        currency=pick_currency(payment, price, commission),
        description=item.get("description", "") or item.get("name", "") or "",
    )
