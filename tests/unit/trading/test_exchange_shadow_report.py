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
        {
            "exchange_id": "binance",
            "reason": "shadow",
            "price": 101.0,
            "average_price": 0.0,
            "reference_price": 100.0,
        },
        {
            "exchange_id": "binance",
            "reason": "shadow",
            "price": 99.0,
            "average_price": 0.0,
            "reference_price": 100.0,
        },
    ]
    summary = summarize_shadow_rows(rows)
    assert summary["mean_deviation_pct"] == pytest.approx(1.0)
    assert summary["max_deviation_pct"] == pytest.approx(1.0)
    assert summary["deviation_samples"] == 2
    assert summary["rows_without_reference"] == 0


def test_rows_without_reference_are_counted_not_averaged():
    from scripts.exchange_shadow_report import summarize_shadow_rows

    rows = [{"exchange_id": "binance", "reason": "shadow", "price": 101.0, "reference_price": 0.0}]
    summary = summarize_shadow_rows(rows)
    assert summary["deviation_samples"] == 0
    assert summary["rows_without_reference"] == 1
    assert summary["mean_deviation_pct"] == 0.0


def test_refusals_are_merged_into_reasons():
    from scripts.exchange_shadow_report import summarize_shadow_rows

    rows = [
        {"exchange_id": "binance", "reason": "shadow", "reference_price": 100.0, "price": 100.0}
    ]
    summary = summarize_shadow_rows(rows, {"exchange_not_ready": 3, "key_not_attested": 1})
    assert summary["reasons"]["shadow"] == 1
    assert summary["reasons"]["exchange_not_ready"] == 3
    assert summary["refusals"] == {"exchange_not_ready": 3, "key_not_attested": 1}


def test_soak_exit_criteria():
    from scripts.exchange_shadow_report import soak_exit_criteria

    clean = {
        "reasons": {"shadow": 4},
        "max_deviation_pct": 0.4,
        "deviation_samples": 4,
        "unknown_rows": 0,
    }
    assert all(soak_exit_criteria(clean, 2.0).values())

    blocked = {
        "reasons": {"exchange_not_ready": 1, "key_not_attested": 1},
        "max_deviation_pct": 5.0,
        "deviation_samples": 0,
        "unknown_rows": 2,
    }
    result = soak_exit_criteria(blocked, 2.0)
    assert result["no_exchange_not_ready"] is False
    assert result["no_key_not_attested"] is False
    assert result["deviation_within_limit"] is False
    assert result["has_samples"] is False
    assert result["no_unknown_rows"] is False


@pytest.mark.asyncio
async def test_unknown_rows_are_reported_and_fail_the_soak(ledger):
    from scripts.exchange_shadow_report import build_report, soak_exit_criteria

    await ledger.append_pending(_intent(), "sandbox")
    await ledger.set_status("cid-1", "binance", "unknown", "reconcile_no_snapshot")

    summary = await build_report(ledger)

    assert summary["unknown_rows"] == 1
    assert soak_exit_criteria(summary, 2.0)["no_unknown_rows"] is False


@pytest.mark.asyncio
async def test_no_unknown_rows_passes_the_soak(ledger):
    from scripts.exchange_shadow_report import build_report

    await ledger.append_pending(_intent(), "shadow", "shadow")

    summary = await build_report(ledger)

    assert summary["unknown_rows"] == 0
