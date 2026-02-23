from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class JobInfo:
    id: str
    filename: str
    status: str = "queued"          # queued | transcribing | cleaning | structuring | done | failed
    message: str = "대기 중..."
    percent: int = 0
    output_path: str = ""
    error: str = ""


class JobManager:
    """
    Thread-safe job registry + asyncio-based SSE event distribution.

    Worker threads push events via `push_event()` (thread-safe).
    FastAPI SSE handlers subscribe via `subscribe()` (async generator).

    Event history is kept per job so that late SSE connections receive
    all past events before switching to live updates.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobInfo] = {}
        self._history: dict[str, list[dict]] = {}          # full event log
        self._subscribers: dict[str, list[asyncio.Queue]] = {}  # live listeners
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Initialisation (called from FastAPI startup)
    # ------------------------------------------------------------------

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    def create_job(self, filename: str) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self._jobs[job_id] = JobInfo(id=job_id, filename=filename)
            self._history[job_id] = []
            self._subscribers[job_id] = []
        return job_id

    def get_job(self, job_id: str) -> JobInfo | None:
        return self._jobs.get(job_id)

    def get_output_path(self, job_id: str) -> Path | None:
        job = self._jobs.get(job_id)
        if job and job.output_path:
            return Path(job.output_path)
        return None

    # ------------------------------------------------------------------
    # Event push (called from worker threads)
    # ------------------------------------------------------------------

    def push_event(
        self,
        job_id: str,
        status: str,
        message: str,
        percent: int,
        output_path: str = "",
        error: str = "",
    ) -> None:
        """Thread-safe: record the event and wake all SSE subscribers."""
        event: dict = {
            "job_id": job_id,
            "status": status,
            "message": message,
            "percent": percent,
        }
        if output_path:
            event["output_path"] = output_path
        if error:
            event["error"] = error

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status
            job.message = message
            job.percent = percent
            if output_path:
                job.output_path = output_path
            if error:
                job.error = error

            self._history[job_id].append(event)
            queues = list(self._subscribers.get(job_id, []))

        if self._loop and self._loop.is_running():
            for q in queues:
                self._loop.call_soon_threadsafe(q.put_nowait, event)

    # ------------------------------------------------------------------
    # SSE subscription (called from async FastAPI handlers)
    # ------------------------------------------------------------------

    async def subscribe(self, job_id: str):
        """
        Async generator yielding events for *job_id*.

        Replays the full event history first, then yields live updates.
        Terminates automatically when status reaches 'done' or 'failed'.
        """
        # Replay history
        with self._lock:
            past_events = list(self._history.get(job_id, []))
            current_status = self._jobs[job_id].status if job_id in self._jobs else "failed"

        for event in past_events:
            yield event

        # If already terminal, nothing more to wait for
        if current_status in ("done", "failed"):
            return

        # Register as a live subscriber
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            if job_id in self._subscribers:
                self._subscribers[job_id].append(queue)

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # Send a heartbeat comment to keep the connection alive
                    yield {"heartbeat": True}
                    continue

                yield event
                if event.get("status") in ("done", "failed"):
                    break
        finally:
            with self._lock:
                subs = self._subscribers.get(job_id, [])
                if queue in subs:
                    subs.remove(queue)
