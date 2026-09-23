"""Individual CLOSED excavation solids — the CAP-CAP logical sweep of every
RAMP / LEVEL_ACCESS / DRIFT / CROSSCUT on its authoritative centerline,
built by the SAME pure helpers the production mesh builders continue from
(``tunnel_mesh.ramp_logical_sweep``, ``development_mesh.closed_sweep``).
No second sweep algorithm, no redesign: the persisted centerline and the
scenario profile go in, the closed logical mesh comes out.

These bodies are the sweep BEFORE the typed junction apertures: they are
closed individually and OVERLAP each other at junctions. They are never a
Boolean union.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import RampConstraints, TunnelProfile
from minegen.design.development_mesh import closed_sweep, specs_from_artifacts
from minegen.design.junctions import find_junctions
from minegen.design.profile import build_profile, secondary_profile
from minegen.design.tunnel_mesh import RingTurnError, ramp_logical_sweep
from minegen.exchange.geometry.centerlines import RAMP_ENTITY_ID, development_entity_id
from minegen.exchange.geometry.qa import MeshQa, mesh_qa

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


class ExcavationSweepError(RuntimeError):
    """A solid could not be swept from its authoritative centerline (the
    same typed reason the production builder would report)."""


@dataclass
class ExcavationSolid:
    entity_id: str
    kind: str  # RAMP | LEVEL_ACCESS | DRIFT | CROSSCUT
    level_id: str | None
    source_artifact: str
    source_id: str
    positions: FloatArray
    triangles: IntArray
    ring_count: int
    qa: MeshQa
    #: the spec / segment ids this solid is swept from (drift pieces …)
    member_source_ids: list[str]


def ramp_solid(
    ramp_payload: dict[str, Any],
    accesses_payload: dict[str, Any] | None,
    ramp: RampConstraints,
    profile: TunnelProfile,
    owning_artifact: str,
) -> ExcavationSolid:
    if ramp_payload.get("status") == "FAILED" or not ramp_payload.get("segments"):
        raise ExcavationSweepError("the Effective Ramp artifact has no sweepable segments")
    try:
        sweep = ramp_logical_sweep(ramp_payload, accesses_payload, ramp, profile)
    except RingTurnError as err:
        raise ExcavationSweepError(f"{RAMP_ENTITY_ID}: {err}") from err
    mesh = sweep.mesh
    return ExcavationSolid(
        entity_id=RAMP_ENTITY_ID,
        kind="RAMP",
        level_id=None,
        source_artifact=owning_artifact,
        source_id="segments[*]",
        positions=np.asarray(mesh.positions, dtype=np.float64),
        triangles=np.asarray(mesh.triangles, dtype=np.int64),
        ring_count=mesh.ring_count,
        qa=mesh_qa(mesh.positions, mesh.triangles),
        member_source_ids=[
            str(s.get("segmentId") or s.get("levelId") or f"segment-{i:02d}")
            for i, s in enumerate(ramp_payload["segments"])
        ],
    )


def development_solids(
    ramp_payload: dict[str, Any] | None,
    accesses_payload: dict[str, Any] | None,
    levels_payload: dict[str, Any] | None,
    ramp: RampConstraints,
    profile: TunnelProfile,
) -> list[ExcavationSolid]:
    """Every LEVEL_ACCESS / DRIFT / CROSSCUT of the owning artifacts, swept
    exactly as ``DevelopmentMeshBuilder.build`` sweeps them (same specs,
    same junction refinement points, same secondary profile)."""
    specs = specs_from_artifacts(accesses_payload, levels_payload)
    junctions = find_junctions(ramp_payload, accesses_payload, levels_payload)
    junction_points: dict[str, list[FloatArray]] = {}
    for j in junctions:
        junction_points.setdefault(j.parent_id, []).append(j.point)
        junction_points.setdefault(j.child_id, []).append(j.point)
    dev_profile = secondary_profile(profile)
    shape = build_profile(ramp, dev_profile)
    width = float(ramp.tunnel_width)
    out: list[ExcavationSolid] = []
    for spec in specs:
        near = junction_points.get(spec.development_id)
        try:
            _chain, closed = closed_sweep(
                spec,
                shape,
                dev_profile,
                width,
                np.asarray(near, dtype=np.float64) if near else None,
            )
        except ValueError as err:
            raise ExcavationSweepError(str(err)) from err
        out.append(
            ExcavationSolid(
                entity_id=development_entity_id(spec.development_id),
                kind=str(spec.kind),
                level_id=spec.level_id,
                source_artifact=str(spec.geometry_ref["artifact"]),
                source_id=spec.development_id,
                positions=np.asarray(closed.positions, dtype=np.float64),
                triangles=np.asarray(closed.triangles, dtype=np.int64),
                ring_count=closed.ring_count,
                qa=mesh_qa(closed.positions, closed.triangles),
                member_source_ids=[piece_id for piece_id, _ in spec.pieces],
            )
        )
    return out
