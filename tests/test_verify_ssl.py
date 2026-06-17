"""
Юнит-тесты на логику verify_ssl (Settings.from_env + TInvestClient).
Никаких реальных токенов, сети или Google Sheets — только конфигурация и
прокидывание параметра в requests.Session().
"""
from __future__ import annotations

import json

import pytest

from tinvest_sync import config as config_module
from tinvest_sync.api import TInvestClient
from tinvest_sync.config import Settings


@pytest.fixture()
def project_dir(tmp_path, monkeypatch):
    """Создаёт временный 'проект' с credentials.json и подменяет CA_BUNDLE_FILE."""
    creds = tmp_path / "credentials.json"
    creds.write_text(json.dumps({"type": "service_account"}))

    # config.py живёт в tinvest_sync/, ca_bundle.pem -- на уровень выше.
    # Подменяем константу, чтобы не зависеть от реального диска.
    fake_bundle = tmp_path / "ca_bundle.pem"
    monkeypatch.setattr(config_module, "CA_BUNDLE_FILE", fake_bundle)

    monkeypatch.setenv("TINVEST_TOKEN", "test-token")
    monkeypatch.setenv("GOOGLE_SPREADSHEET_ID", "test-sheet-id")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(creds))
    monkeypatch.delenv("TINVEST_VERIFY_SSL", raising=False)

    return tmp_path, fake_bundle


class TestSettingsVerifySsl:
    def test_default_no_bundle_verify_true(self, project_dir):
        """Нет TINVEST_VERIFY_SSL и нет ca_bundle.pem -> verify_ssl is True."""
        tmp_path, fake_bundle = project_dir
        assert not fake_bundle.exists()

        settings = Settings.from_env()

        assert settings.verify_ssl is True

    def test_explicit_false_wins_even_with_bundle(self, project_dir, monkeypatch):
        """TINVEST_VERIFY_SSL=false должен отключать проверку, даже если bundle есть."""
        tmp_path, fake_bundle = project_dir
        fake_bundle.write_text("fake-ca-bundle-contents")
        monkeypatch.setenv("TINVEST_VERIFY_SSL", "false")

        settings = Settings.from_env()

        assert settings.verify_ssl is False

    @pytest.mark.parametrize("falsy_value", ["false", "False", "0", "no", "NO"])
    def test_various_falsy_spellings(self, project_dir, monkeypatch, falsy_value):
        monkeypatch.setenv("TINVEST_VERIFY_SSL", falsy_value)

        settings = Settings.from_env()

        assert settings.verify_ssl is False

    @pytest.mark.parametrize("truthy_value", ["true", "True", "1", "yes", ""])
    def test_various_truthy_spellings_without_bundle(self, project_dir, monkeypatch, truthy_value):
        monkeypatch.setenv("TINVEST_VERIFY_SSL", truthy_value)

        settings = Settings.from_env()

        assert settings.verify_ssl is True

    def test_bundle_present_and_ssl_not_disabled_uses_bundle_path(self, project_dir):
        """Если ca_bundle.pem существует и verify не отключён явно -> путь к файлу."""
        tmp_path, fake_bundle = project_dir
        fake_bundle.write_text("fake-ca-bundle-contents")

        settings = Settings.from_env()

        assert settings.verify_ssl == str(fake_bundle)
        assert isinstance(settings.verify_ssl, str)

    def test_missing_required_env_raises(self, project_dir, monkeypatch):
        monkeypatch.delenv("TINVEST_TOKEN", raising=False)

        with pytest.raises(ValueError, match="TINVEST_TOKEN"):
            Settings.from_env()


class TestTInvestClientVerifySsl:
    def test_verify_true_propagates_to_session(self):
        client = TInvestClient(token="test-token", verify_ssl=True)
        assert client._session.verify is True

    def test_verify_false_propagates_to_session(self):
        client = TInvestClient(token="test-token", verify_ssl=False)
        assert client._session.verify is False

    def test_verify_path_propagates_to_session(self):
        client = TInvestClient(token="test-token", verify_ssl="/some/ca_bundle.pem")
        assert client._session.verify == "/some/ca_bundle.pem"

    def test_default_verify_is_true(self):
        client = TInvestClient(token="test-token")
        assert client._session.verify is True

    def test_auth_header_set(self):
        client = TInvestClient(token="my-secret-token")
        assert client._session.headers["Authorization"] == "Bearer my-secret-token"
