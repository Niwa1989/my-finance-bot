"""Refresh configured STALZONE auction snapshots every two hours."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Callable

import auction_service

REFRESH_INTERVAL_SECONDS = 7200
LOG = logging.getLogger("auction-refresh")


def load_targets(path: str | Path = "resolved_catalog.json") -> list[dict[str, str]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot load auction targets: {exc}") from exc
    return [
        {"id": str(row["id"]), "name": str(row.get("name") or row.get("query") or row["id"])}
        for row in data
        if isinstance(row, dict) and row.get("id")
    ]


def refresh_once(targets: list[dict[str, str]] | None = None) -> tuple[int, int]:
    targets = targets if targets is not None else load_targets()
    ok = failed = 0
    for target in targets:
        try:
            auction_service.refresh_snapshot(target["id"], target["name"])
            ok += 1
        except Exception as exc:  # isolate every target, including unexpected parser failures
            failed += 1
            LOG.warning("refresh failed item=%s error=%s", target["id"], exc)
    LOG.info("refresh complete ok=%d failed=%d total=%d", ok, failed, len(targets))
    return ok, failed


def run_forever(
    interval_seconds: int = REFRESH_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    while True:
        try:
            refresh_once()
        except Exception as exc:
            LOG.exception("refresh cycle failed: %s", exc)
        sleep(interval_seconds)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    run_forever()


if __name__ == "__main__":
    main()
