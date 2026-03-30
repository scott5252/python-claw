"""Continuous worker loop that polls for and processes queued execution runs.

Usage:
    uv run python scripts/worker_loop.py

Environment variables:
    PYTHON_CLAW_WORKER_POLL_SECONDS  - seconds between polls (default: 2)
    PYTHON_CLAW_WORKER_IDLE_LOG_EVERY - log idle message every N polls (default: 30)
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from apps.worker.jobs import run_once
from src.config.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    logger.info("received signal %s, shutting down after current run", signum)
    _shutdown = True


def main() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    settings = get_settings()
    poll_seconds = getattr(settings, "worker_poll_seconds", 2)
    idle_log_every = getattr(settings, "worker_idle_log_every", 30)

    logger.info("worker started, polling every %s seconds", poll_seconds)

    idle_count = 0
    while not _shutdown:
        try:
            run_id = run_once(settings=settings)
        except Exception:
            logger.exception("error processing run")
            time.sleep(poll_seconds)
            continue

        if run_id:
            idle_count = 0
            logger.info("processed run %s", run_id)
        else:
            idle_count += 1
            if idle_count % idle_log_every == 0:
                logger.info("idle (%d polls with no work)", idle_count)

        time.sleep(poll_seconds)

    logger.info("worker shut down cleanly")


if __name__ == "__main__":
    main()
