from application.exchange_ports import ExchangeGateway
from trading.exchanges.ccxt_gateway import CcxtGateway
from trading.exchanges.credentials import ExchangeCredentials
from trading.exchanges.errors import OurbitNotReady
from trading.exchanges.registry import ExchangeSpec


def build_gateway(
    spec: ExchangeSpec,
    sandbox: bool,
    credentials: ExchangeCredentials | None = None,
) -> ExchangeGateway:
    if spec.exchange_id == "ourbit":
        raise OurbitNotReady("ourbit_endpoints_not_documented")
    if spec.ccxt_id is None:
        raise OurbitNotReady(f"{spec.exchange_id}_has_no_gateway")
    return CcxtGateway(spec=spec, sandbox=sandbox, credentials=credentials)
