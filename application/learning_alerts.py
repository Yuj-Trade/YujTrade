from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

EVENT_KINDS: frozenset[str] = frozenset(
    {"promoted", "rejected", "failed", "promotion_failed", "drift_detected"}
)
BUFFER_MAXLEN = 100


@dataclass(frozen=True)
class LearningEvent:
    kind: str
    key: str
    model_type: str = ""
    symbol: str = ""
    timeframe: str = ""
    version: str = ""
    reasons: tuple[str, ...] = field(default_factory=tuple)
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unsupported learning event kind {self.kind!r}")
        if not self.key:
            raise ValueError("key must not be empty")
        if self.at.tzinfo is None:
            raise ValueError("at must be timezone-aware")


class LearningAlertSink(Protocol):
    async def send(self, event: LearningEvent) -> None: ...


def render_learning_event(event: LearningEvent) -> str:
    parts = [f"[learning] {event.kind}: {event.key}"]
    if event.symbol and event.timeframe:
        parts.append(f"{event.symbol} {event.timeframe}")
    if event.version:
        parts.append(f"version {event.version}")
    if event.reasons:
        parts.append("reasons: " + "; ".join(event.reasons))
    parts.append(event.at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return " | ".join(parts)


class AlertBuffer:
    def __init__(self, maxlen: int = BUFFER_MAXLEN) -> None:
        self._buffer: deque[str] = deque(maxlen=maxlen)
        self._sender: Callable[[str], Awaitable[None]] | None = None

    def __len__(self) -> int:
        return len(self._buffer)

    def attach(self, sender: Callable[[str], Awaitable[None]]) -> None:
        self._sender = sender
        while self._buffer:
            self._buffer.popleft()

    async def send(self, event: LearningEvent) -> None:
        text = render_learning_event(event)
        sender = self._sender
        if sender is None:
            self._buffer.append(text)
            return
        await sender(text)

    async def flush(self) -> int:
        sender = self._sender
        if sender is None:
            return 0
        sent = 0
        while self._buffer:
            text = self._buffer.popleft()
            await sender(text)
            sent += 1
        return sent
