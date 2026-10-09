try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
    _signals_total = Counter("yujtrade_signals_total", "Signals generated", ["symbol", "timeframe", "side"])
    _orders_total = Counter("yujtrade_orders_total", "Orders executed", ["symbol", "mode", "status"])
    _equity = Gauge("yujtrade_equity", "Portfolio equity")
    _exposure = Gauge("yujtrade_exposure_pct", "Portfolio exposure pct")
    _signal_latency = Histogram("yujtrade_signal_latency_seconds", "Signal pipeline latency")
    _PROM = True
except Exception:
    _PROM = False


def start_metrics_server(enabled: bool = False, port: int = 9108) -> bool:
    if not enabled or not _PROM:
        return False
    from prometheus_client import start_http_server
    start_http_server(int(port), addr="127.0.0.1")
    return True


def init_sentry(dsn: str = "") -> bool:
    if not dsn:
        return False
    import sentry_sdk
    sentry_sdk.init(dsn=dsn)
    return True


def record_signal(symbol: str, timeframe: str, side: str):
    if _PROM:
        _signals_total.labels(symbol, timeframe, side).inc()


def record_order(symbol: str, mode: str, status: str):
    if _PROM:
        _orders_total.labels(symbol, mode, status).inc()


def set_equity(value: float):
    if _PROM:
        _equity.set(float(value))


def set_exposure(value: float):
    if _PROM:
        _exposure.set(float(value))


def observe_latency(seconds: float):
    if _PROM:
        _signal_latency.observe(float(seconds))


def metrics_payload():
    if _PROM:
        return generate_latest(), CONTENT_TYPE_LATEST
    return b"yujtrade_metrics_disabled", "text/plain"
