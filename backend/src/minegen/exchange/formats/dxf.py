"""Minimal deterministic ASCII DXF writer (R12 / AC1009 entity set) for 3-D
polylines and planar faces, plus an independent tag-level reader for tests.

Entities written:

* ``POLYLINE`` (flag 70 = 8: 3-D polyline) with ``VERTEX`` (flag 70 = 32)
  children and ``SEQEND`` — one per centerline;
* ``3DFACE`` — one per triangle of a planar polygon fan (4th corner repeats
  the 3rd, the R12 triangle convention).

Every entity carries a deterministic handle (group 5, ``$HANDLING`` = 1)
so the manifest can map ``handle → entityId``; the layer (group 8) is the
entity KIND (RAMP / LEVEL_ACCESS / DRIFT / CROSSCUT / SHAFT / FAULT). The
writer implements only this documented subset — nothing is invented beyond
the group codes the R12 reference defines for these entities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class DxfPolyline:
    entity_id: str
    layer: str
    points: FloatArray  # (N, 3)


@dataclass(frozen=True)
class DxfPolygon:
    entity_id: str
    layer: str
    points: FloatArray  # (N ≥ 3, 3), planar, ordered


@dataclass
class DxfDocument:
    polylines: list[DxfPolyline] = field(default_factory=list)
    polygons: list[DxfPolygon] = field(default_factory=list)


def sanitize_layer(name: str) -> str:
    """DXF layer names: letters, digits, ``_`` / ``-`` / ``$``; ≤ 31 chars."""
    clean = re.sub(r"[^A-Za-z0-9_$-]", "_", name).strip("_") or "LAYER"
    return clean[:31]


def _f(value: float) -> str:
    return repr(float(value))


def _tag(code: int, value: Any) -> str:
    return f"{code:3d}\n{value}\n"


def write_dxf(doc: DxfDocument) -> tuple[str, list[dict[str, str]]]:
    """→ (DXF text, ``[{handle, entityId, layer, entityType}]``)."""
    out: list[str] = []
    mapping: list[dict[str, str]] = []
    handle = 0x100

    def next_handle() -> str:
        nonlocal handle
        handle += 1
        return f"{handle:X}"

    layers = sorted(
        {sanitize_layer(p.layer) for p in doc.polylines}
        | {sanitize_layer(p.layer) for p in doc.polygons}
    )
    out.append(_tag(0, "SECTION") + _tag(2, "HEADER"))
    out.append(_tag(9, "$ACADVER") + _tag(1, "AC1009"))
    out.append(_tag(9, "$HANDLING") + _tag(70, 1))
    out.append(_tag(9, "$INSUNITS") + _tag(70, 6))  # 6 = meters (informational)
    out.append(_tag(0, "ENDSEC"))
    out.append(_tag(0, "SECTION") + _tag(2, "TABLES"))
    out.append(_tag(0, "TABLE") + _tag(2, "LAYER") + _tag(70, len(layers)))
    for layer in layers:
        out.append(
            _tag(0, "LAYER") + _tag(2, layer) + _tag(70, 0) + _tag(62, 7) + _tag(6, "CONTINUOUS")
        )
    out.append(_tag(0, "ENDTAB") + _tag(0, "ENDSEC"))
    out.append(_tag(0, "SECTION") + _tag(2, "ENTITIES"))
    for pl in doc.polylines:
        layer = sanitize_layer(pl.layer)
        h = next_handle()
        mapping.append(
            {"handle": h, "entityId": pl.entity_id, "layer": layer, "entityType": "POLYLINE"}
        )
        out.append(
            _tag(0, "POLYLINE")
            + _tag(5, h)
            + _tag(8, layer)
            + _tag(66, 1)
            + _tag(10, 0.0)
            + _tag(20, 0.0)
            + _tag(30, 0.0)
            + _tag(70, 8)
        )
        for x, y, z in np.asarray(pl.points, dtype=np.float64).tolist():
            out.append(
                _tag(0, "VERTEX")
                + _tag(5, next_handle())
                + _tag(8, layer)
                + _tag(10, _f(x))
                + _tag(20, _f(y))
                + _tag(30, _f(z))
                + _tag(70, 32)
            )
        out.append(_tag(0, "SEQEND") + _tag(5, next_handle()) + _tag(8, layer))
    for pg in doc.polygons:
        layer = sanitize_layer(pg.layer)
        pts = np.asarray(pg.points, dtype=np.float64)
        for k in range(1, int(pts.shape[0]) - 1):
            h = next_handle()
            mapping.append(
                {"handle": h, "entityId": pg.entity_id, "layer": layer, "entityType": "3DFACE"}
            )
            a, b, c = pts[0], pts[k], pts[k + 1]
            corners = [a, b, c, c]
            tags = _tag(0, "3DFACE") + _tag(5, h) + _tag(8, layer)
            for n, p in enumerate(corners):
                tags += _tag(10 + n, _f(p[0])) + _tag(20 + n, _f(p[1])) + _tag(30 + n, _f(p[2]))
            out.append(tags)
    out.append(_tag(0, "ENDSEC") + _tag(0, "EOF"))
    return "".join(out), mapping


# --------------------------------------------------------------------------- #
# independent reader (tests): group-code pairs → entities
# --------------------------------------------------------------------------- #


def read_dxf_entities(text: str) -> list[dict[str, Any]]:
    """Parse the ENTITIES section into ``{type, handle, layer, points}``
    records: POLYLINE records collect their VERTEX children's (x, y, z);
    3DFACE records carry their four corners. Written independently of the
    writer (pure group-code walk), so a writer defect cannot hide."""
    lines = text.splitlines()
    if len(lines) % 2 != 0:
        raise ValueError("DXF tag stream must be code/value pairs")
    pairs = [(int(lines[i].strip()), lines[i + 1]) for i in range(0, len(lines), 2)]
    entities: list[dict[Any, Any]] = []
    in_entities = False
    current: dict[Any, Any] | None = None
    i = 0
    while i < len(pairs):
        code, value = pairs[i]
        if (
            code == 0
            and value == "SECTION"
            and i + 1 < len(pairs)
            and pairs[i + 1] == (2, "ENTITIES")
        ):
            in_entities = True
            i += 2
            continue
        if in_entities and code == 0 and value == "ENDSEC":
            if current is not None:
                entities.append(current)
            break
        if in_entities and code == 0:
            if value == "VERTEX" and current is not None and current["type"] == "POLYLINE":
                current["_vertex"] = {}
                current.setdefault("points", []).append(current["_vertex"])
            elif value == "SEQEND":
                pass
            else:
                if current is not None:
                    entities.append(current)
                current = {"type": value, "points": []}
            i += 1
            continue
        if in_entities and current is not None:
            target = (
                current.get("_vertex")
                if current["type"] == "POLYLINE" and "_vertex" in current
                else current
            )
            if code == 5 and (current["type"] != "POLYLINE" or "_vertex" not in current):
                current["handle"] = value
            elif code == 8 and (current["type"] != "POLYLINE" or "_vertex" not in current):
                current["layer"] = value
            elif code == 70 and current["type"] == "POLYLINE" and "_vertex" not in current:
                current["flags"] = int(value)
            elif 10 <= code <= 13 or 20 <= code <= 23 or 30 <= code <= 33:
                assert target is not None
                target[code] = float(value)
        i += 1
    out: list[dict[str, Any]] = []
    for e in entities:
        if e["type"] == "POLYLINE":
            pts = [[v.get(10, 0.0), v.get(20, 0.0), v.get(30, 0.0)] for v in e["points"]]
            out.append(
                {
                    "type": "POLYLINE",
                    "handle": e.get("handle"),
                    "layer": e.get("layer"),
                    "flags": e.get("flags"),
                    "points": np.asarray(pts, dtype=np.float64).reshape(-1, 3),
                }
            )
        elif e["type"] == "3DFACE":
            pts = [[e.get(10 + n, 0.0), e.get(20 + n, 0.0), e.get(30 + n, 0.0)] for n in range(4)]
            out.append(
                {
                    "type": "3DFACE",
                    "handle": e.get("handle"),
                    "layer": e.get("layer"),
                    "points": np.asarray(pts, dtype=np.float64),
                }
            )
    return out
