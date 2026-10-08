"""Hardening H0 §3.4 regression — the RT-42 turnout (RAMP_JUNCTION:L02).

``tests/fixtures/h0_3_4/rt42_turnout.json`` is the RANDOM_TABULAR seed-42
scenario with its persisted Effective Ramp and level accesses (layout-v2
winner ``SWITCHBACK-k1-p+0-CCW-g0.100``). Before PR-2 the L02 turnout showed
a black floor sliver along the seam between the ramp floor and the clipped
access floor and wall fragments standing inside the opening
(``docs/findings/h0-3.4-junction-seam.md``). The ramp and the L02 access are
re-swept here exactly as the builders do and the seam is audited: every
clipped child floor chord is bridged to the parent floor edge by a sill and
every straddling child wall quad is clipped. Measured values are recorded as
properties; no threshold, gate or golden changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from minegen.core.models import Scenario
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator, clearance_policy_for
from minegen.design.development_mesh import DevelopmentMeshBuilder
from minegen.design.junctions import (
    JUNCTION_WINDOW_WIDTHS,
    JunctionCut,
    TubeEnvelope,
    find_junctions,
)
from minegen.design.profile import build_profile, secondary_profile
from minegen.design.tunnel_mesh import TunnelMeshBuilder, ramp_logical_sweep
from minegen.world.synthetic_world import generate_world
from tests.test_typed_junctions import _capture, _seam_audit

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "h0_3_4" / "rt42_turnout.json"
LEVEL = "L02"


@pytest.fixture(scope="module")
def rt42() -> dict[str, Any]:
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sc = Scenario(**fx["scenario"])
    world = generate_world(sc)
    ramp, accesses = fx["effectiveRamp"], fx["levelAccesses"]
    policy = clearance_policy_for(world.orebody)
    ev = DesignCostEvaluator(world, sc.design, clearance=policy)
    drift_ev = DesignCostEvaluator(
        world, sc.design, DesignContext.decline(sc.design), clearance=policy
    )
    cross_ev = DesignCostEvaluator(
        world, sc.design, DesignContext.crosscut(sc.design), clearance=policy
    )
    tunnel = TunnelMeshBuilder(ev, sc.ramp, sc.tunnel_profile).build(
        ramp, accesses_payload=accesses
    )
    only = {**accesses, "accesses": [a for a in accesses["accesses"] if a["levelId"] == LEVEL]}
    builder = DevelopmentMeshBuilder(drift_ev, cross_ev, sc.ramp, sc.tunnel_profile)
    cuts = _capture(lambda: builder.build(only, None, ramp_payload=ramp))
    dev = builder.build(only, None, ramp_payload=ramp)
    # the SAME envelopes the builder judges against
    sweep = ramp_logical_sweep(ramp, accesses, sc.ramp, sc.tunnel_profile)
    envs = {"RAMP": TubeEnvelope.build(sweep.chain.centers, sweep.chain.tangents, sweep.shape)}
    return {
        "sc": sc,
        "ramp": ramp,
        "accesses": accesses,
        "tunnel": tunnel,
        "dev": dev,
        "cuts": cuts,
        "envs": envs,
        "junctions": find_junctions(ramp, accesses, None),
        "dev_shape": build_profile(sc.ramp, secondary_profile(sc.tunnel_profile)),
    }


def test_rt42_fixture_is_the_captured_turnout(rt42: dict[str, Any]) -> None:
    assert rt42["ramp"]["candidateId"] == "SWITCHBACK-k1-p+0-CCW-g0.100"
    j = next(x for x in rt42["junctions"] if x.node_id == f"RAMP_JUNCTION:{LEVEL}")
    assert j.type == "RAMP_ACCESS" and j.child_id == f"LEVEL_ACCESS:{LEVEL}"
    assert rt42["tunnel"].status == "SUCCESS" and rt42["dev"].status == "SUCCESS"


def test_rt42_l02_floor_seam_is_closed_by_sills(rt42: dict[str, Any], record_property: Any) -> None:
    cuts: list[JunctionCut] = [
        c for c in rt42["cuts"] if c.junction.node_id == f"RAMP_JUNCTION:{LEVEL}"
    ]
    assert cuts
    audit = _seam_audit(cuts, rt42["envs"], float(rt42["sc"].ramp.tunnel_width))
    record_property("h0_34_seam_audit_rt42_L02", audit)
    assert audit["chords"] > 0 and audit["sills"] > 0
    assert audit["sills"] + audit["chordsOnFloorEdge"] == audit["chords"]
    # the measured seam the sills close (plan gap ≥ the union tolerance,
    # rise within the rule-188 honesty bound)
    assert audit["maxPlanGapClosedM"] >= 0.1 - 1e-6
    assert audit["maxRiseClosedM"] <= 0.3 * float(
        rt42["sc"].ramp.ramp_width
        if hasattr(rt42["sc"].ramp, "ramp_width")
        else rt42["sc"].ramp.tunnel_width
    )
    opening = next(
        o
        for o in rt42["dev"].report["junctions"]["openings"]
        if o["nodeId"] == f"RAMP_JUNCTION:{LEVEL}"
    )
    record_property("h0_34_rt42_L02_opening", opening)
    assert opening["childSillTriangles"] > 0
    assert opening["childClippedFloorQuads"] > 0


def test_rt42_l02_no_child_wall_quad_stands_inside_the_ramp(rt42: dict[str, Any]) -> None:
    width = float(rt42["sc"].ramp.tunnel_width)
    tol = 0.02 * width
    parent = rt42["envs"]["RAMP"]
    for c in rt42["cuts"]:
        if c.side != "CHILD":
            continue
        assert c.unclipped_wall_quads == 0
        assert c.clipped_wall_quads > 0
        window = parent.ring_window(c.junction.point, JUNCTION_WINDOW_WIDTHS * width + width)
        for clip in c.wall_clips:
            for poly in clip.polygons:
                sd = float(parent.signed_distance(poly.mean(axis=0)[None, :], window)[0])
                assert sd > -tol, (clip.interval, clip.edge, sd)
    opening = next(
        o
        for o in rt42["dev"].report["junctions"]["openings"]
        if o["nodeId"] == f"RAMP_JUNCTION:{LEVEL}"
    )
    assert opening["childClippedWallQuads"] > 0 and opening["childUnclippedWallQuads"] == 0
    # the ramp side is unchanged: the wall opens, the floor stays
    tunnel_opening = next(
        o
        for o in rt42["tunnel"].report["junctions"]["openings"]
        if o["nodeId"] == f"RAMP_JUNCTION:{LEVEL}"
    )
    assert tunnel_opening["parentWallTriangles"] > 0 and tunnel_opening["parentFloorTriangles"] == 0
