import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADR_DIR = ROOT / "docs" / "adr"


def _status_line(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().lower().startswith("status:"):
            return line.split(":", 1)[1].strip().lower()
    return ""


def test_exchange_adrs_stay_proposed_without_written_confirmation():
    for name in ("ADR-0011-exchange-connectivity.md", "ADR-0012-exchange-access-profiles.md"):
        status = _status_line(ADR_DIR / name)
        assert status == "proposed", f"{name} is {status!r}"


def test_exchange_adrs_do_not_claim_recorded_approval():
    for name in ("ADR-0011-exchange-connectivity.md", "ADR-0012-exchange-access-profiles.md"):
        text = (ADR_DIR / name).read_text(encoding="utf-8")
        assert "Operator approval was recorded" not in text
        assert "Approval: pending" in text


def test_adr_0012_terms_of_use_statement_is_pending():
    text = (ADR_DIR / "ADR-0012-exchange-access-profiles.md").read_text(encoding="utf-8")
    assert "terms of use: pending" in text
    assert "were reviewed by the operator" not in text


def test_proposal_is_not_marked_approved():
    proposal = ROOT / "openspec" / "changes" / "add-exchange-connectivity" / "proposal.md"
    text = proposal.read_text(encoding="utf-8")
    assert "Status: approved" not in text
    assert "Status: pending approval" in text


def test_review_gate_rejects_proposed_adr(tmp_path):
    from trading.exchanges.gate_inputs import review_is_accepted

    accepted = tmp_path / "ADR-0011-test.md"
    accepted.write_text("# ADR\n\nStatus: accepted\n", encoding="utf-8")
    proposed = tmp_path / "ADR-0012-test.md"
    proposed.write_text("# ADR\n\nStatus: proposed\n", encoding="utf-8")
    assert review_is_accepted("ADR-0011", tmp_path) is True
    assert review_is_accepted("ADR-0012", tmp_path) is False


def test_live_gate_stays_closed_while_adrs_are_proposed():
    from application.exchange_policy import submission_mode
    from config.settings import ConfigManager
    from trading.exchanges.gate_inputs import build_gate_input, load_exchange_settings
    from trading.exchanges.registry import get_spec

    class LiveConfig(ConfigManager):
        DEFAULT_CONFIG = dict(ConfigManager.DEFAULT_CONFIG)

        def __init__(self):
            self.config = {
                **ConfigManager.DEFAULT_CONFIG,
                "exchange_enabled": ["binance"],
                "exchange_sandbox": False,
                "exchange_shadow_mode": False,
                "exchange_live_enabled": True,
                "exchange_live_review_id": "ADR-0011",
                "exchange_attested_keys": ["binance"],
                "exchange_symbol_allowlist": ["BTC/USDT"],
            }

        def get(self, key, default=None):
            return self.config.get(key, default)

    settings = load_exchange_settings(LiveConfig())
    assert settings.live_review_id == "ADR-0011"
    gate = build_gate_input(
        spec=get_spec("binance"),
        settings=settings,
        creds_ok=True,
        permissions_ok=True,
        halted=False,
        sandbox_mode_flag=False,
        execution_dry_run=False,
    )
    mode, reason = submission_mode(gate)
    assert mode is None
    assert reason == "review_not_accepted"


def test_no_tracked_file_enables_live():
    from config.settings import ConfigManager

    defaults = ConfigManager.DEFAULT_CONFIG
    assert defaults["exchange_live_enabled"] is False
    assert defaults["exchange_sandbox"] is True
    assert defaults["execution_dry_run"] is True
    assert defaults["exchange_live_review_id"] == ""
    assert defaults["exchange_attested_keys"] == []


def test_remediation_doc_exists():
    path = ROOT / "docs" / "remediation" / "exchange-remediation-2026-10-29.md"
    assert path.is_file()
    assert re.search(r"R0", path.read_text(encoding="utf-8"))
