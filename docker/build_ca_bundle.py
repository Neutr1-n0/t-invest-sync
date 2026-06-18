#!/usr/bin/env python3
"""Сборка ca_bundle.pem с сертификатами НУЦ Минцифры (Linux/Docker-вариант).

Платформонезависимая часть install_nuc_cert.py: скачивает корневой и
промежуточный сертификаты НУЦ Минцифры и добивает их к системному
CA-бандлу из certifi. Без шага установки в хранилище Windows — он тут
не нужен, в контейнере используется только готовый ca_bundle.pem,
передаваемый в requests.Session(verify=...).
"""

from __future__ import annotations

import ssl
import sys
import urllib.request
from pathlib import Path

CERT_URLS = {
    "root": "https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer",
    "sub": "https://gu-st.ru/content/Other/doc/russian_trusted_sub_ca.cer",
}

OUTPUT_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "ca_bundle.pem")


def download_cert(url: str) -> bytes:
    print(f"  Скачивание: {url}")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(url, context=ctx, timeout=30) as resp:
        return resp.read()


def main() -> int:
    print("Скачивание сертификатов НУЦ Минцифры...")

    certs: dict[str, bytes] = {}
    for name, url in CERT_URLS.items():
        certs[name] = download_cert(url)
        print(f"  {name}: {len(certs[name])} байт")

    import certifi

    ca_path = Path(certifi.where())
    print(f"Чтение системного CA-бандла: {ca_path}")
    bundle = ca_path.read_bytes()

    for data in certs.values():
        bundle += b"\n" + data + b"\n"

    OUTPUT_PATH.write_bytes(bundle)
    print(f"Создан CA-бандл: {OUTPUT_PATH} ({len(bundle)} байт)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
