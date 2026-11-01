import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "seed_exchange_env_names.py"


def _load(tmp_path, monkeypatch):
    module_path = tmp_path / "seed.py"
    module_path.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("seed_env_names", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_seed_adds_empty_names_only(tmp_path, monkeypatch):
    module = _load(tmp_path, monkeypatch)
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=real-value\nBINANCE_API_KEY=\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    module.env_path = env
    module.names = ["BINANCE_API_KEY", "KRAKEN_API_KEY"]
    module.main()
    text = env.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=real-value" in text
    assert text.count("BINANCE_API_KEY=") == 1
    assert "KRAKEN_API_KEY=\n" in text
    assert "real-value" in text


def test_seed_never_writes_a_value(tmp_path, monkeypatch):
    module = _load(tmp_path, monkeypatch)
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    module.env_path = env
    module.names = ["OKX_API_KEY", "OKX_API_SECRET"]
    module.main()
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            assert line.endswith("="), line


def test_seed_is_idempotent(tmp_path, monkeypatch):
    module = _load(tmp_path, monkeypatch)
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    module.env_path = env
    module.names = ["GATE_API_KEY"]
    module.main()
    first = env.read_text(encoding="utf-8")
    module.main()
    assert env.read_text(encoding="utf-8") == first
