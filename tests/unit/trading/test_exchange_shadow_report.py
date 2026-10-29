import pytest

from domain.exchange_types import SHADOW, OrderIntent
from trading.live_ledger import LiveLedger


def _intent(signal_id="sig-1", client_order_id="cid-1"):
    return OrderIntent(
        exchange_id="binance",
        signal_id=signal_id,
        symbol="BTC/USDT",
        side="buy",
        amount=0.0005,
        price=50_000.0,
        client_order_id=client_order_id,
        sandbox=False,
    )


@pytest.fixture
async def ledger(tmp_path):
    instance = LiveLedger(tmp_path / "live.db")
    await instance.initialize()
    return instance


@pytest.mark.asyncio
async def test_shadow_rows_are_collected(ledger):
    await ledger.append_pending(_intent(), "shadow", "shadow")
    await ledger.append_pending(_intent("sig-2", "cid-2"), "sandbox")
    rows = await ledger.get_shadow_rows()
    assert len(rows) == 1
    assert rows[0]["status"] == SHADOW
    assert rows[0]["mode"] == "shadow"


@pytest.mark.asyncio
async def test_shadow_report_summarizes(ledger):
    from scripts.exchange_shadow_report import build_report, format_report

    await ledger.append_pending(_intent(), "shadow", "shadow")
    await ledger.append_pending(_intent("sig-2", "cid-2"), "shadow", "shadow")
    summary = await build_report(ledger)
    assert summary["count"] == 2
    assert summary["reasons"] == {"shadow": 2}
    assert summary["exchanges"] == {"binance": 2}
    text = format_report(summary)
    assert "Shadow rows: 2" in text
    assert "shadow: 2" in text


@pytest.mark.asyncio
async def test_shadow_report_empty(ledger):
    from scripts.exchange_shadow_report import build_report

    summary = await build_report(ledger)
    assert summary["count"] == 0
    assert summary["reasons"] == {}
    assert summary["mean_deviation_pct"] == 0.0


@pytest.mark.asyncio
async def test_shadow_report_has_no_secret_fields(ledger):
    from scripts.exchange_shadow_report import build_report

    await ledger.append_pending(_intent(), "shadow", "shadow")
    summary = await build_report(ledger)
    flat = " ".join(str(value) for value in summary.values())
    assert "api_key" not in flat.lower()
    assert "secret" not in flat.lower()
    assert "passphrase" not in flat.lower()


def test_summarize_computes_mean_deviation():
    from scripts.exchange_shadow_report import summarize_shadow_rows

    rows = [
        {"exchange_id": "binance", "reason": "shadow", "price": 100.0, "average_price": 101.0},
        {"exchange_id": "binance", "reason": "shadow", "price": 100.0, "average_price": 99.0},
    ]
    summary = summarize_shadow_rows(rows)
    assert summary["mean_deviation_pct"] == pytest.approx(1.0)
    assert summary["deviation_samples"] == 2
