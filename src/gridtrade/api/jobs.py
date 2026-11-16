"""Background research jobs.

Backtests hold the GIL for seconds at a time, so they run on plain worker
threads instead of the event loop. Cancellation is cooperative: the runner
checks between months or sweep combinations and raises ``JobCanceled``.
"""

from __future__ import annotations

import logging
import queue
import threading
import traceback
from typing import Callable

from .store import Store, utcnow

log = logging.getLogger("gridtrade.jobs")

Progress = Callable[[float, str], None]
JobFn = Callable[[Progress], dict]


class JobCanceled(Exception):
    pass


class JobQueue:
    def __init__(self, store: Store, *, workers: int = 2) -> None:
        self.store = store
        self.workers = max(1, workers)
        self._queue: queue.Queue[tuple[str, JobFn] | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._closing = False

    def start(self) -> None:
        if self._threads:
            return
        for index in range(self.workers):
            thread = threading.Thread(
                target=self._loop, name=f"research-job-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def submit(self, run_id: str, fn: JobFn) -> None:
        self._queue.put((run_id, fn))

    def stop(self, timeout: float = 5.0) -> None:
        self._closing = True
        for _ in self._threads:
            self._queue.put(None)
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            run_id, fn = item
            self._execute(run_id, fn)

    def _execute(self, run_id: str, fn: JobFn) -> None:
        run = self.store.get_run(run_id)
        if run is None:
            return
        if run["cancel_requested"]:
            self.store.update_run(
                run_id, status="canceled", finished_at=utcnow(), message="canceled before start"
            )
            return

        self.store.update_run(run_id, status="running", started_at=utcnow(), progress=0.01)
        last_write = 0.0

        def progress(value: float, message: str = "") -> None:
            nonlocal last_write
            current = self.store.get_run(run_id)
            if current and current["cancel_requested"]:
                raise JobCanceled()
            if value - last_write < 0.02 and value < 1.0:
                return
            last_write = value
            self.store.update_run(
                run_id, progress=round(max(0.0, min(value, 0.99)), 3), message=message
            )

        try:
            artifact = fn(progress)
        except JobCanceled:
            log.info("run %s canceled", run_id)
            self.store.update_run(
                run_id, status="canceled", finished_at=utcnow(), message="canceled"
            )
            return
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
            log.error("run %s failed: %s\n%s", run_id, exc, traceback.format_exc())
            self.store.update_run(
                run_id,
                status="failed",
                finished_at=utcnow(),
                error=f"{type(exc).__name__}: {exc}"[:500],
                message="failed",
            )
            return

        try:
            size = self.store.save_artifact(run_id, artifact)
            self.store.update_run(
                run_id,
                status="succeeded",
                finished_at=utcnow(),
                progress=1.0,
                message=f"产物 {size // 1024} KiB",
                summary=artifact.get("summary"),
                error=None,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("run %s could not persist: %s", run_id, exc)
            self.store.update_run(
                run_id,
                status="failed",
                finished_at=utcnow(),
                error=f"persist failed: {type(exc).__name__}: {exc}"[:500],
            )
