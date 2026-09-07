"""Deterministic summary of the WARPED-301 section(z) / trace layer under the
WORLD clearance policy (no layout search) — shared by the fixture generator,
the FAST cached canary and the FULL freshness test (VA-01 §18/§23)."""

from __future__ import annotations

from typing import Any

import numpy as np

from minegen.core.models import Scenario
from minegen.design.cost_field import clearance_policy_for
from minegen.design.profile import required_clearance
from minegen.layout.access import MIN_DEVELOPMENT_TRACE_LENGTH
from minegen.layout.families import build_footwall_track
from minegen.layout.levels import LevelSections, required_levels
from minegen.layout.sections import SectionGeometryError, resolve_section_resolution
from minegen.world.synthetic_world import SyntheticWorld


def warped_sections_summary(sc: Scenario, world: SyntheticWorld) -> dict[str, Any]:
    base = (
        sc.layout.access.anchor_standoff
        if sc.layout.access.anchor_standoff is not None
        else sc.ramp.footwall_access_offset
    )
    resolution = resolve_section_resolution(float(sc.layout.section_sampling_spacing), float(base))
    levels = required_levels(
        world.orebody,
        sc.mining.sublevel_interval,
        sc.design.top_mining_margin,
        sc.design.bottom_mining_margin,
    )
    sections = LevelSections(
        world.orebody, levels, float(sc.layout.section_sampling_spacing), resolution=resolution
    )
    track = build_footwall_track(world.orebody, sections)
    assert track is not None
    policy = clearance_policy_for(world.orebody)
    req = required_clearance(sc.design, sc.ramp, sc.tunnel_profile)
    rows: list[dict[str, Any]] = []
    for lv in sections.serviceable():
        geom = sections.geometry(lv)
        row: dict[str, Any] = {
            "levelId": lv.level_id,
            "elevation": round(lv.elevation, 6),
            "componentCount": geom.component_count,
            "selectedComponentId": geom.selected_component_id,
            "selectedSamples": int(geom.selected_mask.sum()),
            "outerContourVertices": int(geom.outer_contour_xy.shape[0]),
        }
        try:
            trace = sections.footwall_trace(lv, track.w_h)
            off = sections.offset_trace(
                lv,
                track.w_h,
                float(base),
                MIN_DEVELOPMENT_TRACE_LENGTH,
                policy.signed_clearance,
                "WORLD",
                req,
            )
            row.update(
                {
                    "footwallTraceLength": round(float(trace.total_length), 6),
                    "offsetTraceLength": round(float(off.total_length), 6),
                    "offsetVertexCount": int(off.points.shape[0]),
                    "minContactDistance": round(float(off.ore_contact_distance.min()), 6),
                    "minClearance": round(float(np.min(policy.signed_clearance(off.points))), 6),
                    "midpoint": [round(float(v), 6) for v in off.point_at(0.5 * off.total_length)],
                }
            )
        except SectionGeometryError as err:
            row["traceFailure"] = err.code
        rows.append(row)
    return {
        "policyBasis": policy.basis,
        "requiredClearance": round(float(req), 6),
        "effectiveSpacing": resolution.effective_spacing,
        "serviceableLevels": len(rows),
        "levels": rows,
    }
