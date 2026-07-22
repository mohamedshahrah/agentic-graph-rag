"""Background exporter: a daemon thread drains a bounded queue and POSTs batches
to the ingest API. The cardinal rule of an observability SDK is that it must
never slow or crash the app it observes — so the queue is bounded (drop on
overflow) and every network error is swallowed. The one exception to silence:
a 4xx from the server (bad key / bad URL) is logged once, because otherwise
events vanish with no way to notice."""

from __future__ import annotations

import atexit
import logging
import queue
import threading
import time

from llmlens.config import get_config

log = logging.getLogger("llmlens")


class Exporter:
    def __init__(self) -> None:
        # Created lazily (first emit) so `configure(max_queue=...)` takes effect.
        self._q: queue.Queue | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._warned_rejected = False

    def _ensure_started(self) -> queue.Queue:
        if self._q is not None and self._thread is not None:
            return self._q
        with self._lock:
            if self._q is None:
                self._q = queue.Queue(maxsize=get_config().max_queue)
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, daemon=True, name="llmlens-exporter"
                )
                self._thread.start()
            return self._q

    def emit(self, event: dict) -> None:
        if not get_config().enabled:
            return
        q = self._ensure_started()
        try:
            q.put_nowait(event)
        except queue.Full:
            pass  # drop — observability must not backpressure the app

    def _run(self) -> None:
        while True:
            batch = self._drain()
            if batch:
                self._send(batch)
            else:
                time.sleep(get_config().flush_interval)

    def _drain(self) -> list[dict]:
        cfg = get_config()
        batch: list[dict] = []
        if self._q is None:
            return batch
        try:
            batch.append(self._q.get(timeout=cfg.flush_interval))
        except queue.Empty:
            return batch
        while len(batch) < cfg.batch_size:
            try:
                batch.append(self._q.get_nowait())
            except queue.Empty:
                break
        return batch

    def _send(self, batch: list[dict]) -> None:
        import httpx  # lazy: keep the SDK importable without httpx present

        cfg = get_config()
        headers = {"Content-Type": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"{cfg.url}/api/v1/ingest",
                    json={"events": batch}, headers=headers, timeout=5.0,
                )
                if resp.status_code < 400:
                    return  # delivered
                if resp.status_code < 500:
                    # Client-side rejection (401/422/...): retrying won't help,
                    # and staying silent means "empty dashboard, no clue why".
                    if not self._warned_rejected:
                        self._warned_rejected = True
                        log.warning(
                            "llmlens: server rejected events (HTTP %s): %s — "
                            "check LLMLENS_API_KEY / LLMLENS_URL",
                            resp.status_code, resp.text[:200],
                        )
                    return
            except Exception:
                pass
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
        # exhausted retries -> drop silently

    def flush(self, timeout: float = 5.0) -> None:
        if self._q is None:
            return
        deadline = time.time() + timeout
        while not self._q.empty() and time.time() < deadline:
            batch = self._drain()
            if batch:
                self._send(batch)


_exporter = Exporter()
atexit.register(_exporter.flush)


def get_exporter() -> Exporter:
    return _exporter
