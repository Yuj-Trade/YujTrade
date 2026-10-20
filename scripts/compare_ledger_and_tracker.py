import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_LEDGER = Path("runs/paper_ledger.db")
DEFAULT_TRACKER = Path("signal_history.json")
SNAPSHOT = Path("runs/performance/ledger_row_count.json")
NO_DATA_LIMIT = 0.05


def _parse_since(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _ledger_rows(ledger_path: Path, since: datetime | None) -> list[dict]:
    if not ledger_path.exists():
        return []
    connection = sqlite3.connect(ledger_path)
    try:
        connection.row_factory = sqlite3.Row
        query = (
            "SELECT signal_id, side, exit_reason, exit_at_utc, exit_price, recorded_at_utc "
            "FROM signal_resolutions"
        )
        params: tuple = ()
        if since is not None:
            query += " WHERE COALESCE(exit_at_utc, created_at_utc) >= ?"
            params = (since.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00"),)
        cursor = connection.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


def _tracker_entries(tracker_path: Path) -> dict:
    if not tracker_path.exists():
        return {"total": 0, "resolved": 0, "pending": 0, "no_data": 0}
    try:
        history = json.loads(tracker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"total": 0, "resolved": 0, "pending": 0, "no_data": 0}
    resolved = 0
    pending = 0
    no_data = 0
    for entry in history.values():
        outcome = entry.get("outcome")
        details = entry.get("details") or {}
        if outcome is True or outcome is False:
            resolved += 1
        else:
            pending += 1
        if details.get("resolution_status") == "no_data":
            no_data += 1
    return {
        "total": len(history),
        "resolved": resolved,
        "pending": pending,
        "no_data": no_data,
    }


def _read_snapshot(snapshot_path: Path) -> int | None:
    if not snapshot_path.exists():
        return None
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("rows")
    return int(value) if isinstance(value, int) else None


def _write_snapshot(snapshot_path: Path, rows: int) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps({"rows": rows}, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare the paper ledger with the signal tracker")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--tracker", type=Path, default=DEFAULT_TRACKER)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--since", default=None, help="ISO-8601 lower bound of the window")
    args = parser.parse_args()

    since = _parse_since(args.since)
    rows = _ledger_rows(args.ledger, since)
    tracker = _tracker_entries(args.tracker)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["exit_reason"]] = counts.get(row["exit_reason"], 0) + 1
    no_data_rows = counts.get("no_data", 0)
    priced_rows = len(rows) - no_data_rows
    total_rows = len(rows)

    previous = _read_snapshot(args.snapshot)
    _write_snapshot(args.snapshot, total_rows)

    no_data_ratio = (no_data_rows / total_rows) if total_rows else 0.0
    expected_tracker_resolved = priced_rows

    problems: list[str] = []
    if tracker["resolved"] < expected_tracker_resolved:
        problems.append(
            f"the tracker holds {tracker['resolved']} resolved signals but the ledger holds "
            f"{expected_tracker_resolved} priced resolutions"
        )
    if no_data_ratio > NO_DATA_LIMIT:
        problems.append(
            f"the no_data ratio is {no_data_ratio:.2%}, above the {NO_DATA_LIMIT:.0%} limit"
        )
    if previous is not None and total_rows < previous:
        problems.append(
            f"the ledger row count fell from {previous} to {total_rows}: the ledger must be "
            "append-only and must never be pruned"
        )

    print(f"ledger rows: {total_rows} (priced {priced_rows}, no_data {no_data_rows})")
    for reason in sorted(counts):
        print(f"  {reason}: {counts[reason]}")
    print(
        f"tracker entries: {tracker['total']} "
        f"(resolved {tracker['resolved']}, pending {tracker['pending']}, "
        f"no_data {tracker['no_data']})"
    )
    print(f"no_data ratio: {no_data_ratio:.2%}")
    print(f"ledger row count: {total_rows} (previous snapshot {previous})")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        raise SystemExit(1)
    print(
        "OK: the ledger and the tracker agree, the no_data ratio is within the limit "
        "and the ledger never shrank"
    )


if __name__ == "__main__":
    if sys.platform == "win32":
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    main()
