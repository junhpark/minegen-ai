"""Job status endpoints and the WebSocket progress stream (rule 60)."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from minegen.api.deps import get_job_service
from minegen.core.models import ErrorDetail
from minegen.services.job_service import TERMINAL, JobNotFoundError, JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])
ws_router = APIRouter()

Jobs = Annotated[JobService, Depends(get_job_service)]


def _not_found(job_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ErrorDetail(
            code="JOB_NOT_FOUND", message=f"job '{job_id}' does not exist"
        ).model_dump(by_alias=True),
    )


@router.get("")
def list_jobs(jobs: Jobs, scenario_id: str | None = None) -> list[dict[str, Any]]:
    return jobs.list(scenario_id)


@router.get("/{job_id}")
def get_job(
    job_id: str,
    jobs: Jobs,
    include_result: Annotated[bool, Query(alias="includeResult")] = True,
) -> dict[str, Any]:
    try:
        return jobs.snapshot(job_id, include_result=include_result)
    except JobNotFoundError as e:
        raise _not_found(job_id) from e


@ws_router.websocket("/ws/jobs/{job_id}")
async def job_progress(websocket: WebSocket, job_id: str) -> None:
    """Streams the job record whenever it changes (≤ 10 Hz), then closes
    after the terminal record. The algorithm thread never touches the socket;
    this coroutine polls the registry version counter."""
    jobs = get_job_service()
    await websocket.accept()
    try:
        jobs.get(job_id)
    except JobNotFoundError:
        await websocket.send_json({"type": "error", "code": "JOB_NOT_FOUND", "jobId": job_id})
        await websocket.close(code=4404)
        return
    last_version = -1
    try:
        while True:
            snap = jobs.snapshot(job_id, include_result=False)
            if snap["version"] != last_version:
                last_version = int(snap["version"])
                await websocket.send_json({"type": "progress", **snap})
                if snap["status"] in {s.value for s in TERMINAL}:
                    await websocket.send_json(
                        {"type": "done", "jobId": job_id, "status": snap["status"]}
                    )
                    break
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        return
    await websocket.close()
