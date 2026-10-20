from typing import Protocol


class NotificationDeliveryError(Exception):
    def __init__(self, message: str, *, permanent: bool) -> None:
        super().__init__(message)
        self.permanent = permanent


class OutcomeNotifier(Protocol):
    async def send(self, text: str) -> None: ...
