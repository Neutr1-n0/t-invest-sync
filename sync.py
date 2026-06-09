#!/usr/bin/env python3
"""CLI entry point for T-Invest operations sync."""

from __future__ import annotations

import argparse
import sys

from tinvest_sync.config import Settings
from tinvest_sync.sync_service import parse_from_date, sync_operations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Синхронизация операций T-Invest в Google Таблицу",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        help="Начало периода (YYYY-MM-DD или ISO datetime). По умолчанию — DEFAULT_FROM_DATE из .env",
    )
    parser.add_argument(
        "--from-last",
        action="store_true",
        help="Начать с последней даты в таблице (минус 1 день для перекрытия)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Отключить проверку SSL-сертификата (если сертификат НУЦ Минцифры не установлен в системе)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 1

    if args.from_date and args.from_last:
        print("Укажите либо --from, либо --from-last", file=sys.stderr)
        return 1

    if args.insecure:
        settings = Settings(
            tinvest_token=settings.tinvest_token,
            spreadsheet_id=settings.spreadsheet_id,
            service_account_file=settings.service_account_file,
            default_from_date=settings.default_from_date,
            verify_ssl=False,
        )

    date_from = parse_from_date(args.from_date) if args.from_date else None

    try:
        result = sync_operations(
            settings,
            date_from=date_from,
            use_last_sheet_date=args.from_last,
        )
    except Exception as exc:
        print(f"Ошибка синхронизации: {exc}", file=sys.stderr)
        return 1

    print(
        "Готово: "
        f"счетов={result.accounts}, "
        f"получено={result.fetched}, "
        f"добавлено={result.appended}, "
        f"дубликатов={result.skipped_duplicates}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
