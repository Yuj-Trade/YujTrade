import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load(script_name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "scripts" / script_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_encrypt_keys_missing_env_logs_and_returns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module = load("encrypt_keys.py", "encrypt_keys_missing")
    module.run()
    assert not (tmp_path / ".env").exists()


def test_encrypt_keys_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=super_secret_token\n"
        "SENTRY_DSN=my_sentry_dsn\n"
        "CRYPTOPANIC_KEY=panic123\n"
        "OTHER=plain\n",
        encoding="utf-8",
    )
    module = load("encrypt_keys.py", "encrypt_keys_roundtrip")
    monkeypatch.setattr(module.getpass, "getpass", lambda *a, **k: "pw123")

    from utils.security import KeyEncryptor

    module.run()

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "ENCRYPTED_SENTRY_DSN=" in content
    assert "ENCRYPTED_CRYPTOPANIC_KEY=" in content
    assert "SENTRY_DSN=my_sentry_dsn" not in content
    assert "OTHER=plain" in content

    encrypted = {
        line.split("=")[0]: line.split("=", 1)[1].strip()
        for line in content.splitlines()
        if line.startswith("ENCRYPTED_")
    }
    encryptor = KeyEncryptor("pw123")
    assert encryptor.decrypt(encrypted["ENCRYPTED_SENTRY_DSN"]) == "my_sentry_dsn"


def test_encrypt_keys_empty_password_aborts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=abc\n", encoding="utf-8")
    module = load("encrypt_keys.py", "encrypt_keys_empty_pw")
    monkeypatch.setattr(module.getpass, "getpass", lambda *a, **k: "")
    module.run()
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert content == "TELEGRAM_BOT_TOKEN=abc\n"
