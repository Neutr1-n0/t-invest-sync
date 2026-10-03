from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from tinvest_sync.api import Account, Operation
from tinvest_sync.config import ACCOUNTS_HEADERS_ROW, ACCOUNTS_SHEET_NAME, HEADERS_ROW, SHEET_NAME

# Эпоха Google Sheets / Excel serial date (Lotus 1-2-3 наследие): 1899-12-30.
_SHEETS_EPOCH = datetime(1899, 12, 30)


class SheetsClient:
    def __init__(self, spreadsheet_id: str, service_account_file: Path) -> None:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        credentials = Credentials.from_service_account_file(
            str(service_account_file),
            scopes=scopes,
        )
        self._spreadsheet_id = spreadsheet_id
        self._service = build("sheets", "v4", credentials=credentials).spreadsheets()

    def ensure_sheet(self) -> None:
        spreadsheet = (
            self._service.get(spreadsheetId=self._spreadsheet_id).execute()
        )
        titles = {sheet["properties"]["title"] for sheet in spreadsheet["sheets"]}

        if SHEET_NAME not in titles:
            self._service.batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {"title": SHEET_NAME},
                            }
                        }
                    ]
                },
            ).execute()

        values = self._get_values(f"{SHEET_NAME}!A1:A1")
        if not values:
            self._service.values().update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{SHEET_NAME}!A1",
                valueInputOption="RAW",
                body={"values": [HEADERS_ROW]},
            ).execute()

    def get_existing_operation_ids(self) -> set[str]:
        values = self._get_values(f"{SHEET_NAME}!L:L")
        if len(values) <= 1:
            return set()

        return {row[0] for row in values[1:] if row and row[0]}

    def get_last_operation_dates_by_account(self) -> dict[str, datetime]:
        """Read per-account maxima in UTC, ignoring incomplete or invalid rows."""
        values = self._get_values(
            f"{SHEET_NAME}!A:C", value_render_option="UNFORMATTED_VALUE"
        )
        dates: dict[str, datetime] = {}
        for row in values[1:]:
            if len(row) < 3:
                continue
            raw_account_id = row[2]
            if isinstance(raw_account_id, str):
                account_id = raw_account_id.strip()
            elif isinstance(raw_account_id, int) and not isinstance(raw_account_id, bool):
                account_id = str(raw_account_id)
            elif isinstance(raw_account_id, float) and raw_account_id.is_integer():
                account_id = str(int(raw_account_id))
            else:
                continue
            if not account_id:
                continue
            if isinstance(row[0], bool):
                continue
            try:
                text = _normalize_sheet_date(row[0])
                if not text:
                    continue
                date = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                date = date.astimezone(timezone.utc)
            except (ValueError, OverflowError):
                continue
            if account_id not in dates or date > dates[account_id]:
                dates[account_id] = date
        return dates

    def append_operations(self, operations: Iterable[Operation]) -> int:
        rows = [_operation_to_row(operation) for operation in operations]
        if not rows:
            return 0

        self._service.values().append(
            spreadsheetId=self._spreadsheet_id,
            range=f"{SHEET_NAME}!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()
        return len(rows)

    def replace_accounts(self, accounts: Iterable[Account]) -> None:
        """Replace the account snapshot, including headers and stale data rows."""
        updated_at = datetime.now(timezone.utc).isoformat()
        rows = [ACCOUNTS_HEADERS_ROW] + [
            [updated_at, account.id, account.name, account.type,
             account.status or "", account.opened_date or "",
             account.closed_date or "", account.access_level or ""]
            for account in sorted(accounts, key=lambda account: account.id)
        ]
        spreadsheet = self._service.get(spreadsheetId=self._spreadsheet_id).execute()
        properties = next(
            (sheet["properties"] for sheet in spreadsheet["sheets"]
             if sheet["properties"]["title"] == ACCOUNTS_SHEET_NAME),
            None,
        )
        if properties is None:
            result = self._service.batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {
                    "title": ACCOUNTS_SHEET_NAME,
                    "gridProperties": {"rowCount": max(1000, len(rows)), "columnCount": 8},
                }}}]},
            ).execute()
            properties = result["replies"][0]["addSheet"]["properties"]

        sheet_id = properties["sheetId"]
        grid = properties["gridProperties"]
        requests = []
        for dimension, current, required in (
            ("ROWS", grid["rowCount"], len(rows)),
            ("COLUMNS", grid["columnCount"], len(ACCOUNTS_HEADERS_ROW)),
        ):
            if current < required:
                requests.append({"appendDimension": {
                    "sheetId": sheet_id, "dimension": dimension, "length": required - current,
                }})
        # A range without endRowIndex also clears values below the new snapshot.
        requests.append({"updateCells": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0,
                      "startColumnIndex": 0, "endColumnIndex": len(ACCOUNTS_HEADERS_ROW)},
            "rows": [{"values": [{"userEnteredValue": {"stringValue": value}}
                                  for value in row]} for row in rows],
            "fields": "userEnteredValue",
        }})
        self._service.batchUpdate(
            spreadsheetId=self._spreadsheet_id, body={"requests": requests},
        ).execute()

    def _get_values(
        self, range_name: str, value_render_option: str = "FORMATTED_VALUE"
    ) -> list[list[object]]:
        result = (
            self._service.values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=range_name,
                valueRenderOption=value_render_option,
            )
            .execute()
        )
        return result.get("values", [])


def _normalize_sheet_date(value: object) -> str | None:
    """Привести значение даты из Google Sheets к строке 'YYYY-MM-DD HH:MM:SS'.

    UNFORMATTED_VALUE отдаёт даты как float (serial number, дни с 1899-12-30),
    независимо от локали таблицы. Если значение уже строка (например, ячейка
    отформатирована как текст), пробуем использовать её как есть.
    """
    if isinstance(value, (int, float)):
        dt = _SHEETS_EPOCH + timedelta(days=float(value))
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    if isinstance(value, str):
        text = value.strip()
        return text or None

    return None


def _operation_to_row(operation: Operation) -> list[str | int | float | None]:
    return [
        operation.date,
        operation.account_name,
        operation.account_id,
        operation.type,
        operation.ticker,
        operation.quantity,
        operation.price,
        operation.payment,
        operation.commission,
        operation.currency,
        operation.description,
        operation.operation_id,
    ]
