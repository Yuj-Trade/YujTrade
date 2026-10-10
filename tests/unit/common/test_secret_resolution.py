from pathlib import Path
from unittest.mock import patch

from utils import security


def test_secret_env_password_resolves(monkeypatch):
    monkeypatch.setenv("SECRET_ENCRYPTION_PASSWORD", "s3cret-value")
    with patch.object(
        Path, "read_text", side_effect=FileNotFoundError
    ):
        assert security.get_password_from_key_manager() == "s3cret-value"


def test_legacy_env_password_alone_resolves_to_none(monkeypatch):
    monkeypatch.delenv("SECRET_ENCRYPTION_PASSWORD", raising=False)
    monkeypatch.setenv("ENCRYPTION_PASSWORD", "legacy-value")
    with patch.object(
        Path, "read_text", side_effect=FileNotFoundError
    ):
        assert security.get_password_from_key_manager() is None


def test_mounted_secret_file_wins_over_env(monkeypatch):
    monkeypatch.setenv("SECRET_ENCRYPTION_PASSWORD", "env-value")
    with patch.object(security, "Path") as mock_path:
        mock_path.return_value.read_text.return_value = "file-value\n"
        assert security.get_password_from_key_manager() == "file-value"
