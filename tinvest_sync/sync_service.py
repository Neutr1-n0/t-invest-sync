from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tinvest_sync.api import TInvestClient
from tinvest_sync.config import Settings
from tinvest_sync.sheets import SheetsClient


@dataclass
class SyncResult:
    accounts: int
    fetched: int
    appended: int
    skipped_duplicates: int


def parse_from_date(value: str) -> datetime:
    text = value.strip()
    if len(text) == 10:
        text += "T00:00:00Z"
    if text.endswith("Z"):
        text = text.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sync_operations(
    settings: Settings,
    date_from: datetime | None = None,
    use_last_sheet_date: bool = False,
) -> SyncResult:
    client = TInvestClient(settings.tinvest_token, verify_ssl=settings.verify_ssl)
    sheets = SheetsClient(settings.spreadsheet_id, settings.service_account_file)
    sheets.ensure_sheet()

    if date_from is None:
        if use_last_sheet_date:
            last_date = sheets.get_last_operation_date()
            if last_date:
                date_from = parse_from_date(last_date) - timedelta(days=1)
            else:
                date_from = parse_from_date(settings.default_from_date)
        else:
            date_from = parse_from_date(settings.default_from_date)

    existing_ids = sheets.get_existing_operation_ids()
    accounts = client.get_accounts()

    fetched = 0
    skipped = 0
    new_operations = []

    for account in accounts:
        for operation in client.iter_operations(account, date_from):
            fetched += 1
            if operation.operation_id in existing_ids:
                skipped += 1
                continue
            new_operations.append(operation)
            existing_ids.add(operation.operation_id)

    appended = sheets.append_operations(new_operations)

    return SyncResult(
        accounts=len(accounts),
        fetched=fetched,
        appended=appended,
        skipped_duplicates=skipped,
    )
