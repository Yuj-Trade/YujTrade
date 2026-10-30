from typing import Protocol, runtime_checkable


class NotificationDeliveryError(Exception):
    def __init__(self, message: str, *, permanent: bool) -> None:
        super().__init__(message)
        self.permanent = permanent


class OutcomeNotifier(Protocol):
    async def send(self, text: str) -> None: ...


@runtime_checkable
class IntrabarPriceFeed(Protocol):
    async def last_price(self, symbol: str) -> float | None: ...
