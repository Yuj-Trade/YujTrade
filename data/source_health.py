import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SourceStatus:
    name: str
    ok: bool = True
    latency_ms: float = 0.0
    last_error: str = ""
    success_count: int = 0
    fail_count: int = 0
    last_check: float = 0.0


class SourceHealthMonitor:
    def __init__(self, clock=time.time, cooldown_seconds: float = 300.0) -> None:
        self._sources: Dict[str, SourceStatus] = {}
        self._clock = clock
        self._cooldown_seconds = float(cooldown_seconds)
        self._cooldowns: Dict[str, float] = {}

    def register(self, name: str) -> None:
        if name not in self._sources:
            self._sources[name] = SourceStatus(name=name)

    def record_success(self, name: str, latency_ms: float = 0.0) -> None:
        self.register(name)
        s = self._sources[name]
        s.ok = True
        s.latency_ms = float(latency_ms)
        s.last_error = ""
        s.success_count += 1
        s.last_check = self._clock()
        self._cooldowns.pop(name, None)

    def record_failure(self, name: str, error: str = "") -> None:
        self.register(name)
        s = self._sources[name]
        s.fail_count += 1
        s.last_error = str(error)[:300]
        s.last_check = self._clock()
        if s.fail_count >= 5 and s.success_count == 0:
            s.ok = False
        elif s.fail_count >= 10:
            s.ok = False
        if not s.ok:
            previous = self._cooldowns.get(name)
            self._cooldowns[name] = min(
                3600.0,
                self._cooldown_seconds
                if previous is None
                else max(self._cooldown_seconds, previous * 2),
            )

    def is_healthy(self, name: str) -> bool:
        s = self._sources.get(name)
        if s is None:
            return True
        if not s.ok and self._clock() - s.last_check >= self._cooldowns.get(
            name, self._cooldown_seconds
        ):
            return True
        return s.ok

    def can_probe(self, name: str) -> bool:
        status = self._sources.get(name)
        if status is None or status.ok:
            return False
        return self._clock() - status.last_check >= self._cooldowns.get(
            name, self._cooldown_seconds
        )

    def begin_probe(self, name: str) -> bool:
        if not self.can_probe(name):
            return False
        self._sources[name].last_check = self._clock()
        return True

    def probe_result(self, name: str, ok: bool, error: str = "") -> None:
        if ok:
            self.record_success(name)
        else:
            self.record_failure(name, error)

    def healthy_sources(self, ordered: List[str]) -> List[str]:
        out: List[str] = []
        for name in ordered:
            if self.is_healthy(name):
                out.append(name)
        if not out:
            return list(ordered)
        return out

    def snapshot(self) -> Dict[str, Any]:
        return {
            k: {
                "ok": v.ok,
                "latency_ms": v.latency_ms,
                "last_error": v.last_error,
                "success": v.success_count,
                "fail": v.fail_count,
            }
            for k, v in self._sources.items()
        }
