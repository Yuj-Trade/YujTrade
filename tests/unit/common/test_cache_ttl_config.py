import json
import re
from pathlib import Path

import pytest

from config.settings import ConfigManager

ROOT = Path(__file__).resolve().parents[3]

EXPECTED_TTLS = {
    ("ohlcv", "1h"): 300,
    ("ohlcv", "4h"): 900,
    ("ohlcv", "1d"): 1800,
    ("ohlcv", "1w"): 3600,
    ("ohlcv", "1M"): 7200,
    ("derivatives", None): 300,
    ("macro", None): 86400,
    ("indices", None): 600,
    ("news", None): 600,
    ("fundamental", None): 43200,
    ("trending", None): 3600,
    ("generic", None): 86400,
    ("asset_profile", None): 604800,
    ("fear_greed", None): 3600,
    ("defillama", None): 3600,
    ("onchain", None): 3600,
    ("sentiment", None): 1800,
}

# Keys reserved for the approved next phase; not read by current code yet.
FUTURE_KEYS = {"asset_profile"}


def _manager() -> ConfigManager:
    return ConfigManager()


@pytest.mark.parametrize(("category", "sub"), sorted(EXPECTED_TTLS, key=str))
def test_effective_ttl_values(category, sub):
    assert _manager().get_cache_ttl(category, sub) == EXPECTED_TTLS[(category, sub)]


def test_default_ttl_is_3600():
    assert _manager().get_cache_ttl("unknown_category_xyz") == 3600


def test_file_cache_config_matches_defaults_key_by_key():
    payload = json.loads((ROOT / "indicator_weights.json").read_text(encoding="utf-8"))
    file_config = payload["cache_config"]
    default_config = ConfigManager.DEFAULT_WEIGHTS_CONFIG["cache_config"]
    assert set(file_config) == set(default_config)
    for key in default_config:
        assert file_config[key] == default_config[key]


def test_every_cache_key_is_read_in_code():
    sources = []
    for base in ("data", "strategy"):
        sources.extend((ROOT / base).rglob("*.py"))
    reads: set[str] = set()
    for path in sources:
        if "__pycache__" in path.parts:
            continue
        reads.update(re.findall(r'get_cache_ttl\("([^"]+)"', path.read_text(encoding="utf-8")))
    payload = json.loads((ROOT / "indicator_weights.json").read_text(encoding="utf-8"))
    for key in payload["cache_config"]:
        if key in ("default_ttl", "ohlcv"):
            continue
        assert key in reads or key in FUTURE_KEYS, key
