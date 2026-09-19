"""ONE resolver from a MineNetwork ``geometryRef`` to its owning centerline
(AC-01I, rule 68 / rule 93).

Every physical edge of ``network.json`` references the validated centerline
artifact that owns it — ``{"artifact": <file>, "segmentIndex": <int>}`` —
and never duplicates the polyline. Before AC-01I three consumers parsed
that reference with three private copies (the infrastructure domain, the
timeline builder and the capability graph's shaft slice) that disagreed on
strength: per-edge-type ownership here, a flat union there, a bare ``int()``
in the third. This module is the reference half of that resolution and
nothing more:

    typed ref (+ optional edge type) → validated ``OwningCenterline``

It validates the reference shape, the owning artifact (per edge type when
the caller names one, the flat union otherwise), the index range, and the
owning point list (flat, multiple of 3, ≥ 2 points, numeric, finite). It
computes NO geometry: chainage, length synchronization and endpoint
orientation stay with the consumer that needs them, exactly where they were.

Failures are typed ``GeometryRefError`` whose ``str()`` is the reason text
the consumer serializes (prefixed with the edge id by the consumer). A
malformed reference never escapes as KeyError / IndexError / TypeError /
ValueError. The resolver never reads a file: callers hand it the already
validated artifact payloads (rule 40 / AC-01F — the read authority stays
``services/artifact_reader.py``) and it never regenerates anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from minegen.core.artifacts import (
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    RAMP_OWNING_ARTIFACTS,
    SHAFTS_ARTIFACT,
)

#: Which artifact may own the geometry of each physical edge type (rule 68,
#: rule 160, rule 183). RAISE has no owner and is never resolved.
OWNING_ARTIFACTS_BY_EDGE_TYPE: dict[str, tuple[str, ...]] = {
    "RAMP": RAMP_OWNING_ARTIFACTS,
    "LEVEL_ACCESS": (LEVEL_ACCESSES_ARTIFACT,),
    "DRIFT": (LEVELS_ARTIFACT,),
    "CROSSCUT": (LEVELS_ARTIFACT,),
    "SHAFT": (SHAFTS_ARTIFACT,),
    "SHAFT_STATION_ACCESS": (SHAFTS_ARTIFACT,),
}

#: The flat union — a reference with no edge type context may point at any
#: owning artifact (the timeline builder's historical contract).
OWNING_ARTIFACTS: tuple[str, ...] = (
    *RAMP_OWNING_ARTIFACTS,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    SHAFTS_ARTIFACT,
)


class GeometryRefError(Exception):
    """Typed reference failure; ``str(exc)`` is the serializable reason."""


@dataclass(frozen=True)
class OwningCenterline:
    """A validated reference: the owning record and its raw point list."""

    artifact: str
    segment_index: int
    owner: dict[str, Any]
    #: the flat ``[x, y, z, …]`` list exactly as the artifact stores it
    points: list[float]
    #: the same points as an ``(N, 3)`` float64 array (validated finite)
    array: np.ndarray


def _owners(
    artifact: str,
    smoothed_payload: dict[str, Any] | None,
    levels_payload: dict[str, Any] | None,
    accesses_payload: dict[str, Any] | None,
    shafts_payload: dict[str, Any] | None,
) -> tuple[Any, str]:
    """The owning record list and the centerline container key per artifact."""
    if artifact in RAMP_OWNING_ARTIFACTS:
        return (smoothed_payload or {}).get("segments"), "effectiveCenterline"
    if artifact == LEVEL_ACCESSES_ARTIFACT:
        return (accesses_payload or {}).get("accesses"), "centerline"
    if artifact == SHAFTS_ARTIFACT:
        return (shafts_payload or {}).get("centerlines"), "centerline"
    return (levels_payload or {}).get("developments"), "centerline"


def resolve_owning_centerline(
    ref: Any,
    *,
    edge_type: str | None = None,
    smoothed_payload: dict[str, Any] | None = None,
    levels_payload: dict[str, Any] | None = None,
    accesses_payload: dict[str, Any] | None = None,
    shafts_payload: dict[str, Any] | None = None,
) -> OwningCenterline:
    """Resolve ``ref`` to its owning centerline or raise ``GeometryRefError``.

    ``edge_type`` narrows the accepted owner to that type's artifacts (the
    infrastructure-domain contract); without it any owning artifact is
    accepted (the timeline contract). Payloads the caller does not hold may
    be omitted — a reference into an absent artifact is then an out-of-range
    failure with ``0 entries``, never a KeyError.
    """
    if not isinstance(ref, dict):
        raise GeometryRefError("geometryRef is not an object")
    artifact = ref.get("artifact")
    if edge_type is not None:
        expected = OWNING_ARTIFACTS_BY_EDGE_TYPE.get(edge_type)
        if expected is None:
            raise GeometryRefError(f"edge type {edge_type!r} has no owning artifact")
        if artifact not in expected:
            raise GeometryRefError(
                f"of type {edge_type} must be owned by {' or '.join(expected)}, "
                f"geometryRef points to {artifact!r}"
            )
    elif artifact not in OWNING_ARTIFACTS:
        raise GeometryRefError(f"unknown owning artifact {artifact!r}")
    assert isinstance(artifact, str)  # narrowed by the membership tests above
    raw_index = ref.get("segmentIndex")
    if not isinstance(raw_index, int) or isinstance(raw_index, bool) or raw_index < 0:
        raise GeometryRefError(f"segmentIndex {raw_index!r} is not a non-negative integer")
    owners, container = _owners(
        artifact, smoothed_payload, levels_payload, accesses_payload, shafts_payload
    )
    if not isinstance(owners, list) or raw_index >= len(owners):
        count = len(owners) if isinstance(owners, list) else 0
        raise GeometryRefError(
            f"segmentIndex {raw_index} is out of range for {artifact} ({count} entries)"
        )
    owner = owners[raw_index]
    centerline = owner.get(container) if isinstance(owner, dict) else None
    raw_points = centerline.get("points") if isinstance(centerline, dict) else None
    # malformed owning geometry is a typed failure, never an unhandled
    # reshape/conversion exception
    if not isinstance(raw_points, list) or len(raw_points) < 6 or len(raw_points) % 3 != 0:
        raise GeometryRefError(
            "owning centerline is missing, has < 2 points or is not a flat "
            "multiple-of-3 coordinate list"
        )
    try:
        pts = np.asarray(raw_points, dtype=np.float64).reshape(-1, 3)
    except (TypeError, ValueError):
        raise GeometryRefError("owning centerline contains non-numeric values") from None
    if pts.shape[0] < 2:
        raise GeometryRefError("owning centerline has < 2 points")
    if not np.all(np.isfinite(pts)):
        raise GeometryRefError("owning centerline has non-finite points")
    assert isinstance(owner, dict)  # established by the container lookup above
    return OwningCenterline(
        artifact=artifact, segment_index=raw_index, owner=owner, points=raw_points, array=pts
    )
