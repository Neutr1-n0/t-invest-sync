#!/usr/bin/env python3
"""Установка корневого сертификата НУЦ Минцифры для Python и Windows.

Скрипт:
1. Скачивает корневой (Russian Trusted Root CA) и промежуточный
   (Russian Trusted Sub CA) сертификаты НУЦ Минцифры.
2. Создаёт файл ca_bundle.pem в папке проекта — расширенный CA-бандл,
   который используется tinvest_sync для проверки SSL-сертификата Т-Банка.
3. Устанавливает сертификаты в системное хранилище Windows (CurrentUser).

После установки можно запускать sync.py без флага --insecure:
    python sync.py --from 2020-01-01
"""

from __future__ import annotations

import ssl
import sys
import urllib.request
from pathlib import Path

# Путь к папке проекта (родительская относительно этого скрипта)
PROJECT_DIR = Path(__file__).resolve().parent

# URL сертификатов НУЦ Минцифры на официальном сайте gu-st.ru
CERT_URLS = {
    "root": "https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer",
    "sub": "https://gu-st.ru/content/Other/doc/russian_trusted_sub_ca.cer",
}

# Итоговый CA-бандл в папке проекта
CA_BUNDLE_PATH = PROJECT_DIR / "ca_bundle.pem"


def download_cert(url: str) -> bytes:
    """Скачать сертификат по URL, с запасным вариантом без проверки SSL."""
    print(f"  Скачивание: {url}")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(url, context=ctx, timeout=30) as resp:
            return resp.read()
    except Exception:
        print("  Не удалось проверить сертификат сайта, пробую в обход...")
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(url, context=ctx, timeout=30) as resp:
            return resp.read()


def main() -> int:
    print("Скачивание сертификатов НУЦ Минцифры...")

    certs: dict[str, bytes] = {}
    for name, url in CERT_URLS.items():
        try:
            certs[name] = download_cert(url)
            print(f"  {name}: {len(certs[name])} байт")
        except Exception as exc:
            print(f"  {name}: ОШИБКА — {exc}", file=sys.stderr)

    if not certs:
        print(
            "Не удалось скачать ни одного сертификата. Проверьте подключение к интернету.",
            file=sys.stderr,
        )
        return 1

    # Создаём ca_bundle.pem: берём системный cacert.pem из certifi
    # и добавляем сертификаты НУЦ
    try:
        import certifi
        ca_path = Path(certifi.where())
    except ImportError:
        ca_path = None

    if ca_path and ca_path.exists():
        print(f"Чтение системного CA-бандла: {ca_path}")
        with open(ca_path, "rb") as f:
            bundle = f.read()
    else:
        print("certifi не найден, создаю бандл только из сертификатов НУЦ")
        bundle = b""

    for data in certs.values():
        bundle += b"\n" + data + b"\n"

    with open(CA_BUNDLE_PATH, "wb") as f:
        f.write(bundle)

    print(f"Создан CA-бандл: {CA_BUNDLE_PATH} ({len(bundle)} байт)")

    # Установка в системное хранилище Windows (опционально)
    print("\nУстановка сертификатов в хранилище Windows (CurrentUser)...")
    import subprocess
    import tempfile

    for name, data in certs.items():
        with tempfile.NamedTemporaryFile(suffix=".crt", delete=False) as tmp:
            tmp.write(data)
            tmp.flush()
            tmp_path = tmp.name

        # Определяем хранилище: Root — для корневого, CA — для промежуточного
        store = "Root" if name == "root" else "CA"
        ps_script = (
            f"Import-Certificate -FilePath '{tmp_path}' "
            f"-CertStoreLocation Cert:\\CurrentUser\\{store} "
            f"-Confirm:$false"
        )
        result = subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            print(f"  {name}: установлен в CurrentUser\\{store}")
        else:
            print(f"  {name}: ошибка установки — {result.stderr.strip()}")
        Path(tmp_path).unlink(missing_ok=True)

    print("\nГотово! Сертификаты НУЦ Минцифры установлены.")
    print(f"CA-бандл сохранён: {CA_BUNDLE_PATH}")
    print("\nТеперь можно запускать sync.py без флага --insecure:")
    print("  python sync.py --from 2020-01-01")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())