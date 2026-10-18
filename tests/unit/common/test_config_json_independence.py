import json

from config.settings import ConfigManager


def _effective_config(config_path):
    weights_path = config_path.parent / "indicator_weights.json"
    manager = ConfigManager(config_path=str(config_path), weights_path=str(weights_path))
    return manager.config


def test_missing_config_file_yields_default_signal_threshold(tmp_path):
    config = _effective_config(tmp_path / "config.json")
    assert config["signal_threshold"] == 10


def test_legacy_tracked_override_is_identical_to_defaults(tmp_path):
    legacy = tmp_path / "config.json"
    legacy.write_text(json.dumps({"signal_threshold": 10}), encoding="utf-8")
    with_override = _effective_config(legacy)
    without_override = _effective_config(tmp_path / "absent.json")
    assert with_override == without_override


def test_default_config_covers_every_default_key(tmp_path):
    config = _effective_config(tmp_path / "config.json")
    for key, value in ConfigManager.DEFAULT_CONFIG.items():
        assert config[key] == value
