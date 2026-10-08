"""Demo write guard (hardening PR-2 H4) — ONE dependency on every
scenario-scoped router.

A baked demo is resolved in place by the scenario store and must never be
modified, so every state-changing request aimed at a demo id answers the
typed 409 ``DEMO_READ_ONLY`` BEFORE the route body runs. Read-only POSTs are
allowed through: the MineExchange / adapter exports (rule 209: an export
persists nothing), the analysis what-if (a projection, rule precedent of
``GET …/analysis/sensitivity``), the design-cost point query and the
shaft-collar suggestion (pure computations). The store's own
``assert_writable`` is the second line behind this one (replace / delete /
derived clearing), so a write that reaches a service through another path is
still refused.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from minegen.api.deps import get_scenario_store
from minegen.api.errors import error_response
from minegen.services.scenario_service import DemoReadOnlyError, ScenarioStore

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: sub-paths (after ``/scenarios/{id}``) whose POST is a READ — a projection
#: that writes nothing; every other mutating request on a demo is refused
READ_ONLY_POST_PREFIXES: tuple[str, ...] = (
    "/export/",
    "/analysis/what-if",
    "/design/cost/evaluate",
    "/design/shafts/suggest-collar",
)


def is_read_only_post(method: str, subpath: str) -> bool:
    return method == "POST" and subpath.startswith(READ_ONLY_POST_PREFIXES)


def refuse_demo_writes(
    request: Request, store: Annotated[ScenarioStore, Depends(get_scenario_store)]
) -> None:
    scenario_id = request.path_params.get("scenario_id")
    if not isinstance(scenario_id, str) or request.method not in MUTATING_METHODS:
        return
    if not store.is_demo(scenario_id):
        return
    marker = f"/scenarios/{scenario_id}"
    path = request.url.path
    subpath = path[path.index(marker) + len(marker) :] if marker in path else ""
    if is_read_only_post(request.method, subpath):
        return
    exc = DemoReadOnlyError(scenario_id, f"{request.method} {subpath or '/'}")
    raise error_response(exc.http_status, exc.code, str(exc))
