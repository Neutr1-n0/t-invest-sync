"""
T-Invest API Proxy — Google Cloud Function
===========================================
Прокси-функция для обхода SSL-проблемы в Google Apps Script.
Серверы Google не доверяют сертификату НУЦ Минцифры, поэтому
Apps Script не может напрямую вызвать API Т-Инвестиций.

Эта функция принимает запрос от Apps Script и проксирует его
в API Т-Инвестиций с отключённой проверкой SSL.

Деплой:
  gcloud functions deploy tinvest-proxy \
    --runtime python310 \
    --trigger-http \
    --allow-unauthenticated \
    --entry-point proxy

После деплоя вы получите URL вида:
  https://us-central1-<project>.cloudfunctions.net/tinvest-proxy

Этот URL нужно указать в AppsScript.gs как PROXY_URL.
"""

from __future__ import annotations

import json
from typing import Any

import requests


def proxy(request: Any) -> Any:
    """Прокси-функция для Google Cloud Functions."""
    # CORS headers для запросов из Apps Script
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }

    # Preflight (OPTIONS)
    if request.method == "OPTIONS":
        return ("", 204, headers)

    if request.method != "POST":
        return (json.dumps({"error": "Only POST allowed"}), 405, {**headers, "Content-Type": "application/json"})

    try:
        body = request.get_json(force=True, silent=True)
        if not body:
            return (json.dumps({"error": "Invalid JSON"}), 400, {**headers, "Content-Type": "application/json"})

        method = body.get("method", "")
        payload = body.get("payload", {})
        token = body.get("token", "")

        if not method or not token:
            return (json.dumps({"error": "Missing 'method' or 'token'"}), 400, {**headers, "Content-Type": "application/json"})

        # Вызов API Т-Инвестиций без проверки SSL
        url = f"https://invest-public-api.tbank.ru/rest/{method}"
        response = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            verify=False,  # Отключаем проверку SSL
            timeout=60,
        )

        result = {
            "status": response.status_code,
            "body": response.json() if response.text else {},
        }

        return (json.dumps(result), 200, {**headers, "Content-Type": "application/json"})

    except Exception as e:
        return (json.dumps({"error": str(e)}), 500, {**headers, "Content-Type": "application/json"})