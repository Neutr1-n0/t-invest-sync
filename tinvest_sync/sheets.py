from __future__ import annotations

from pathlib import Path
from typing import Iterable

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from tinvest_sync.api import Operation
from tinvest_sync.config import HEADERS_ROW, SHEET_NAME


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

    def get_last_operation_date(self) -> str | None:
        values = self._get_values(f"{SHEET_NAME}!A:A")
        if len(values) <= 1:
            return None

        dates = [row[0] for row in values[1:] if row and row[0]]
        return max(dates) if dates else None

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

    def _get_values(self, range_name: str) -> list[list[str]]:
        result = (
            self._service.values()
            .get(spreadsheetId=self._spreadsheet_id, range=range_name)
            .execute()
        )
        return result.get("values", [])


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
