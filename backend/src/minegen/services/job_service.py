"""In-memory asynchronous job registry (rule 60).

    POST …/design/decline → 202 {jobId, status: QUEUED}
    GET  /jobs/{jobId}    → status + progress (+ result when finished)
    WS   /ws/jobs/{jobId} → the same records streamed until terminal

Jobs run on a small thread pool. The registry is process-local and lost on
restart (documented v0.1 limitation). One job per scenario at a time.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from minegen.core.enums import JobStatus
from minegen.design.progress import ProgressEvent

TERMINAL = {JobStatus.SUCCEEDED, JobStatus.FAILED}


class JobAlreadyRunningError(RuntimeError):
    def __init__(self, scenario_id: str, job_id: str) -> None:
        super().__init__(f"scenario '{scenario_id}' already has running job '{job_id}'")
        self.scenario_id = scenario_id
        self.job_id = job_id


class JobNotFoundError(KeyError):
    pass


@dataclass
class JobRecord:
    id: str
    scenario_id: str
    kind: str
    status: JobStatus = JobStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    version: int = 0  # bumps on every change (WebSocket change detection)

    def to_dict(self, *, include_result: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "jobId": self.id,
            "scenarioId": self.scenario_id,
            "kind": self.kind,
            "status": self.status.value,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
            "progress": self.progress,
            "error": self.error,
            "version": self.version,
        }
        if include_result:
            d["result"] = self.result
        return d


class JobService:
    def __init__(self, max_workers: int = 2) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="minegen-job")

    # -- submission -------------------------------------------------------- #

    def submit(
        self,
        scenario_id: str,
        kind: str,
        work: Callable[[Callable[[ProgressEvent], None]], dict[str, Any]],
    ) -> JobRecord:
        """``work(on_progress)`` runs on the pool and returns the result payload."""
        with self._lock:
            for j in self._jobs.values():
                if j.scenario_id == scenario_id and j.status not in TERMINAL:
                    raise JobAlreadyRunningError(scenario_id, j.id)
            job = JobRecord(id=uuid.uuid4().hex[:12], scenario_id=scenario_id, kind=kind)
            self._jobs[job.id] = job

        def on_progress(ev: ProgressEvent) -> None:
            with self._lock:
                job.progress = ev.to_dict()
                job.version += 1

        def run() -> None:
            with self._lock:
                job.status = JobStatus.RUNNING
                job.started_at = time.time()
                job.version += 1
            try:
                result = work(on_progress)
            except Exception as exc:
                with self._lock:
                    job.status = JobStatus.FAILED
                    job.error = {
                        # exceptions may carry a structured code (e.g. the
                        # stale-input guard raises code JOB_INPUTS_CHANGED)
                        "code": getattr(exc, "code", "JOB_FAILED"),
                        "message": str(exc) or f"{type(exc).__name__}",
                        "exception": type(exc).__name__,
                        "traceback": traceback.format_exc(),
                    }
                    job.finished_at = time.time()
                    job.version += 1
                return
            with self._lock:
                job.status = JobStatus.SUCCEEDED
                job.result = result
                job.finished_at = time.time()
                if job.progress:
                    job.progress["progress"] = 1.0
                job.version += 1

        self._pool.submit(run)
        return job

    # -- queries ----------------------------------------------------------- #

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            return job

    def snapshot(self, job_id: str, *, include_result: bool = True) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            return job.to_dict(include_result=include_result)

    def list(self, scenario_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return [
                j.to_dict(include_result=False)
                for j in sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
                if scenario_id is None or j.scenario_id == scenario_id
            ]

    def wait(self, job_id: str, timeout: float = 60.0) -> JobRecord:
        """Block until terminal (tests / CLI)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.get(job_id)
            if job.status in TERMINAL:
                return job
            time.sleep(0.02)
        raise TimeoutError(job_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
