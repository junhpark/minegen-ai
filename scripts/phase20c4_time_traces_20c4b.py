# ruff: noqa: E501  # diagnostic script (not production)
"""Stage-1 cost probe: building the WORLD-policy offset traces for every serviceable level BEFORE any candidate (what a shared ServiceReference would add to setup)."""

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend" / "src"))
from minegen.core.enums import ScenarioPreset
from minegen.core.models import Scenario
from minegen.layout.access import MIN_DEVELOPMENT_TRACE_LENGTH
from minegen.layout.families import build_footwall_track
from minegen.layout.levels import LevelSections
from minegen.layout.search import LayoutV2Search
from minegen.layout.sections import resolve_section_resolution
from minegen.services.scenario_realizer import realize_scenario
from minegen.world.synthetic_world import generate_world

seed = int(sys.argv[1])
create = realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, seed, 1)
sc = Scenario(**create.model_dump())
world = generate_world(sc)
search = LayoutV2Search(sc, world)
t0 = time.perf_counter()
res = search.run()  # includes setup + full search (baseline timing)
t_run = time.perf_counter() - t0
# now time ONLY the world-policy trace construction on a fresh LevelSections (cache-free)
sections = LevelSections(world.orebody, res.levels, sc.layout.section_sampling_spacing)
base_standoff = (
    sc.layout.access.anchor_standoff
    if sc.layout.access.anchor_standoff is not None
    else sc.ramp.footwall_access_offset
)
sections.set_resolution(
    resolve_section_resolution(float(sc.layout.section_sampling_spacing), float(base_standoff))
)
track = build_footwall_track(world.orebody, sections)
t1 = time.perf_counter()
n = 0
errs = 0
req = res.required_clearance
standoff = search.anchor_standoff(req, search.policy)
for lv in sections.serviceable():
    try:
        sections.offset_trace(
            lv,
            track.w_h,
            standoff,
            MIN_DEVELOPMENT_TRACE_LENGTH,
            search.policy.signed_clearance,
            "WORLD",
            req,
        )
        n += 1
    except Exception as exc:
        errs += 1
        print("trace error", lv.level_id, repr(exc)[:120])
t_tr = time.perf_counter() - t1
print(
    f"seed {seed}: full search {t_run:.1f} s | fresh sections + track + {n} world-policy offset traces ({errs} errors) = {t_tr:.2f} s",
    flush=True,
)
