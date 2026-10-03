from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tinvest_sync.api import Account, TInvestClient
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


def _is_syncable_invest_account(account: Account) -> bool:
    return account.status == "ACCOUNT_STATUS_OPEN" and account.type in (
        "ACCOUNT_TYPE_TINKOFF", "ACCOUNT_TYPE_TINKOFF_IIS",
    )


def sync_operations(
    settings: Settings,
    date_from: datetime | None = None,
    use_last_sheet_date: bool = False,
) -> SyncResult:
    client = TInvestClient(settings.tinvest_token, verify_ssl=settings.verify_ssl)
    sheets = SheetsClient(settings.spreadsheet_id, settings.service_account_file)

    # Fetch every eligible portfolio before ensure_sheet, which may write headers.
    # The account snapshot includes every status; data fetches use eligible accounts.
    accounts = client.get_accounts()
    eligible_accounts = [account for account in accounts if _is_syncable_invest_account(account)]
    positions = []
    for account in eligible_accounts:
        positions.extend(client.get_portfolio(account))
    sheets.ensure_sheet()

    last_dates: dict[str, datetime] = {}
    if date_from is None:
        if use_last_sheet_date:
            last_dates = sheets.get_last_operation_dates_by_account()
        date_from = parse_from_date(settings.default_from_date)

    existing_ids = sheets.get_existing_operation_ids()

    fetched = 0
    skipped = 0
    new_operations = []

    for account in eligible_accounts:
        account_date_from = date_from
        if account.id in last_dates:
            account_date_from = last_dates[account.id] - timedelta(days=1)
        for operation in client.iter_operations(account, account_date_from):
            fetched += 1
            if operation.operation_id in existing_ids:
                skipped += 1
                continue
            new_operations.append(operation)
            existing_ids.add(operation.operation_id)

    appended = sheets.append_operations(new_operations)
    sheets.replace_accounts(accounts)
    sheets.replace_positions(positions, accounts)

    return SyncResult(
        accounts=len(accounts),
        fetched=fetched,
        appended=appended,
        skipped_duplicates=skipped,
    )
