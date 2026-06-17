from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = "https://invest-public-api.tbank.ru/rest"
SHEET_NAME = "operations"
CA_BUNDLE_FILE = Path(__file__).resolve().parent.parent / "ca_bundle.pem"
HEADERS_ROW = [
    "date",
    "account_name",
    "account_id",
    "type",
    "ticker",
    "quantity",
    "price",
    "payment",
    "commission",
    "currency",
    "description",
    "operation_id",
]


@dataclass(frozen=True)
class Settings:
    tinvest_token: str
    spreadsheet_id: str
    service_account_file: Path
    default_from_date: str = "2019-01-01T00:00:00Z"
    verify_ssl: bool | str = True

    @classmethod
    def from_env(cls) -> Settings:
        token = os.getenv("TINVEST_TOKEN", "").strip()
        spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID", "").strip()
        service_account_file = Path(
            os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json")
        )

        missing = []
        if not token:
            missing.append("TINVEST_TOKEN")
        if not spreadsheet_id:
            missing.append("GOOGLE_SPREADSHEET_ID")
        if not service_account_file.exists():
            missing.append(f"GOOGLE_SERVICE_ACCOUNT_FILE ({service_account_file})")

        if missing:
            raise ValueError(
                "Заполните переменные окружения в .env: " + ", ".join(missing)
            )

        default_from = os.getenv("DEFAULT_FROM_DATE", "2019-01-01T00:00:00Z").strip()

        ssl_disabled = os.getenv("TINVEST_VERIFY_SSL", "true").strip().lower() in ("false", "0", "no")
        if ssl_disabled:
            verify_ssl: bool | str = False
        elif CA_BUNDLE_FILE.exists():
            # Кастомный бандл с сертификатом НУЦ Минцифры (см. install_nuc_cert.py),
            # на случай если он не установлен в системное хранилище ОС.
            verify_ssl = str(CA_BUNDLE_FILE)
        else:
            verify_ssl = True

        return cls(
            tinvest_token=token,
            spreadsheet_id=spreadsheet_id,
            service_account_file=service_account_file,
            default_from_date=default_from,
            verify_ssl=verify_ssl,
        )
