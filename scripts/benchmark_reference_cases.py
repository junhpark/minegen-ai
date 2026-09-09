"""VA-01 benchmark: uncontended runtime split for TABULAR-REFERENCE and
WARPED_VEIN-301 (runtime observation only — never a correctness gate, never a
threshold input; scripts/verify.py benchmark wraps it).

Per case: (1) standalone section-geometry cost (occupancy + components +
contour, then footwall + offset traces per serviceable level, fresh caches) --
WARPED only, TABULAR uses the exact rule-43 line and never builds sections;
(2) the production LayoutV2Search stage split from its own perf dict (section
geometry is LAZY inside the stages, so the standalone number OVERLAPS the
stage numbers and is not additive with them); (3) level development via the
production service (activate winner -> level accesses -> generate_levels);
(4) peak RSS (resource.getrusage ru_maxrss). Run with the machine otherwise
idle; wall-clock numbers are meaningless under load.
"""

from __future__ import annotations

import json
import resource
import tempfile
import time
from pathlib import Path

from minegen.design.cost_field import clearance_policy_for
from minegen.design.profile import required_clearance
from minegen.layout.access import MIN_DEVELOPMENT_TRACE_LENGTH
from minegen.layout.families import build_footwall_track
from minegen.layout.levels import LevelSections, required_levels
from minegen.layout.search import LayoutV2Search
from minegen.layout.sections import resolve_section_resolution
from minegen.regression.layout_v2 import FULL_SUITE
from minegen.services.design_service import DesignService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from minegen.world.synthetic_world import generate_world

OUT = Path(__file__).resolve().parents[1] / "backend" / ".verification" / "runtime-summary.json"


def _rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _case(key: str):
    for c in FULL_SUITE:
        if c.key == key:
            return c
    raise KeyError(key)


def measure(key: str) -> dict:
    case = _case(key)
    sc = case.realize()
    out: dict = {"key": key}

    # ---- (1) standalone section geometry (WARPED only) ---------------------
    world = generate_world(sc)
    if sc.orebody.orebody_type.value != "TABULAR":
        levels = required_levels(
            world.orebody,
            sc.mining.sublevel_interval,
            sc.design.top_mining_margin,
            sc.design.bottom_mining_margin,
        )
        base = (
            sc.layout.access.anchor_standoff
            if sc.layout.access.anchor_standoff is not None
            else sc.ramp.footwall_access_offset
        )
        res = resolve_section_resolution(float(sc.layout.section_sampling_spacing), float(base))
        t0 = time.perf_counter()
        sections = LevelSections(
            world.orebody, levels, sc.layout.section_sampling_spacing, resolution=res
        )
        serviceable = sections.serviceable()
        for lv in serviceable:
            sections.geometry(lv)
        t_geom = time.perf_counter() - t0
        track = build_footwall_track(world.orebody, sections)
        assert track is not None
        policy = clearance_policy_for(world.orebody)
        req = required_clearance(sc.design, sc.ramp, sc.tunnel_profile)
        t1 = time.perf_counter()
        traced = 0
        for lv in serviceable:
            try:
                sections.footwall_trace(lv, track.w_h)
                sections.offset_trace(
                    lv,
                    track.w_h,
                    float(base),
                    MIN_DEVELOPMENT_TRACE_LENGTH,
                    policy.signed_clearance,
                    "WORLD",
                    req,
                )
                traced += 1
            except Exception as exc:
                out.setdefault("traceFailures", []).append(f"{lv.level_id}: {type(exc).__name__}")
        out["sectionGeometry"] = {
            "serviceableLevels": len(serviceable),
            "tracedLevels": traced,
            "occupancyComponentsContourSeconds": round(t_geom, 2),
            "footwallPlusOffsetTraceSeconds": round(time.perf_counter() - t1, 2),
            "effectiveSpacing": res.effective_spacing,
            "note": "standalone, fresh caches; OVERLAPS the search stage times below",
        }
    else:
        out["sectionGeometry"] = None

    # ---- (2) production search stage split ---------------------------------
    t0 = time.perf_counter()
    res2 = LayoutV2Search(sc, generate_world(sc)).run()
    search_wall = time.perf_counter() - t0
    perf = res2.performance
    out["search"] = {
        "winnerId": res2.winner_id,
        "setupSeconds": round(float(perf.get("setupSeconds", 0.0)), 2),
        "constructAndCheapSeconds": round(float(perf.get("constructAndCheapSeconds", 0.0)), 2),
        "detailedSeconds": round(float(perf.get("detailedSeconds", 0.0)), 2),
        "totalSeconds": round(float(perf.get("totalSeconds", 0.0)), 2),
        "wallSeconds": round(search_wall, 2),
    }
    out["peakRssMbAfterSearch"] = round(_rss_mb(), 1)

    # ---- (3) level development through the production service --------------
    with tempfile.TemporaryDirectory() as td:
        store = ScenarioStore(Path(td) / "scenarios")
        ws = WorldService(store)
        ds = DesignService(store, ws)
        stored = store.create(_create_of(case))
        ws.generate(stored.id)
        catalogue = ds.generate_layout_v2(stored.id)
        winner = catalogue["winnerId"]
        out["serviceCatalogueWinner"] = winner
        if winner is not None:
            ds.activate_layout_candidate(stored.id, winner)
            t0 = time.perf_counter()
            levels_payload = ds.generate_levels(stored.id)
            out["levelDevelopmentSeconds"] = round(time.perf_counter() - t0, 2)
            out["levelsStatus"] = levels_payload.status
            out["developmentGeometry"] = levels_payload.development_geometry
        else:
            out["levelDevelopmentSeconds"] = None
            out["levelsStatus"] = None
    out["peakRssMbFinal"] = round(_rss_mb(), 1)
    return out


def _create_of(case):
    from minegen.core.models import ScenarioCreate
    from minegen.services.scenario_realizer import realize_scenario

    create = realize_scenario(case.preset, case.seed, case.fault_count)
    raw = create.model_dump()
    for path, value in case.overrides:
        node = raw
        *parents, leaf = path.split(".")
        for k in parents:
            node = node[k]
        node[leaf] = value
    return ScenarioCreate(**raw)


def main() -> int:
    results = [measure("TABULAR-REFERENCE"), measure("WARPED_VEIN-301")]
    OUT.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
