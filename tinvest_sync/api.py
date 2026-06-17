from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

import requests

from tinvest_sync.config import API_BASE_URL
from tinvest_sync.money import money_to_float, pick_currency


class TInvestAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    type: str


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
            {"status": "ACCOUNT_STATUS_OPEN"},
        )
        accounts = data.get("accounts", [])
        result: list[Account] = []
        for item in accounts:
            result.append(
                Account(
                    id=item.get("id", ""),
                    name=item.get("name", "") or item.get("id", ""),
                    type=item.get("type", "ACCOUNT_TYPE_UNSPECIFIED"),
                )
            )
        return result

    def iter_operations(
        self,
        account: Account,
        date_from: datetime,
        date_to: datetime | None = None,
    ) -> Iterator[Operation]:
        if date_to is None:
            date_to = datetime.now(timezone.utc)

        cursor = ""
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
                break


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
