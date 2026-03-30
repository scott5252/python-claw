from __future__ import annotations

import os
import time

from apps.worker.jobs import run_once


def main() -> None:
    poll_seconds = float(os.getenv("PYTHON_CLAW_WORKER_POLL_SECONDS", "2"))
    idle_log_every = max(1, int(os.getenv("PYTHON_CLAW_WORKER_IDLE_LOG_EVERY", "30")))
    idle_count = 0

    while True:
        run_id = run_once()
        if run_id:
            idle_count = 0
            print(f"processed run {run_id}", flush=True)
        else:
            idle_count += 1
            if idle_count % idle_log_every == 0:
                print("worker idle", flush=True)
            time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
