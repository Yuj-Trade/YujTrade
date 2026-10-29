import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from config.logger import logger
from trading.exchanges.ccxt_gateway import CcxtGateway
from trading.exchanges.registry import EXCHANGE_REGISTRY

PROBE_SYMBOL = "BTC/USDT"
PROBE_TIMEOUT_SECONDS = 25.0


async def _probe_public(spec) -> dict:
    result = {
        "exchange_id": spec.exchange_id,
        "ccxt_id": spec.ccxt_id,
        "load_markets": False,
        "btc_usdt": False,
        "ticker": None,
        "sandbox": "unknown",
        "error": "",
    }
    gateway = None
    try:
        gateway = CcxtGateway(spec=spec, sandbox=False)
        await gateway.load_markets()
        result["load_markets"] = True
        markets = getattr(gateway.client, "markets", None) or {}
        result["btc_usdt"] = PROBE_SYMBOL in markets
        if result["btc_usdt"]:
            result["ticker"] = await gateway.fetch_last(PROBE_SYMBOL)
    except Exception as exc:
        result["error"] = gateway.error_text(exc) if gateway else str(exc)
    finally:
        if gateway is not None:
            await gateway.close()
    sandbox_gateway = None
    try:
        sandbox_gateway = CcxtGateway(spec=spec, sandbox=True)
        result["sandbox"] = "supported"
    except Exception as exc:
        result["sandbox"] = "not_supported"
        if not result["error"]:
            result["error"] = str(exc)
    finally:
        if sandbox_gateway is not None:
            await sandbox_gateway.close()
    return result


async def run_probe(output_path: Path) -> list[dict]:
    import ccxt

    results = []
    for spec in EXCHANGE_REGISTRY:
        if spec.ccxt_id is None:
            results.append(
                {
                    "exchange_id": spec.exchange_id,
                    "ccxt_id": None,
                    "load_markets": False,
                    "btc_usdt": False,
                    "ticker": None,
                    "sandbox": "unknown",
                    "error": "no_ccxt_class",
                }
            )
            continue
        try:
            results.append(
                await asyncio.wait_for(_probe_public(spec), timeout=PROBE_TIMEOUT_SECONDS)
            )
        except TimeoutError:
            results.append(
                {
                    "exchange_id": spec.exchange_id,
                    "ccxt_id": spec.ccxt_id,
                    "load_markets": False,
                    "btc_usdt": False,
                    "ticker": None,
                    "sandbox": "unknown",
                    "error": "probe_timeout",
                }
            )
            logger.warning(f"Probe timed out for {spec.exchange_id}")
    payload = {
        "ccxt_version": getattr(ccxt, "__version__", "unknown"),
        "run_at_utc": datetime.now(UTC).isoformat(),
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return results


def main() -> None:
    results = asyncio.run(run_probe(Path("runs/exchange_probe.json")))
    for result in results:
        logger.info(
            f"{result['exchange_id']}: markets={result['load_markets']} "
            f"btc={result['btc_usdt']} sandbox={result['sandbox']} error={result['error']}"
        )
    logger.info("Probe written to runs/exchange_probe.json")


if __name__ == "__main__":
    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
