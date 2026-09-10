"""Layout-v2 search setup (AC-01D).

ONE definition of the pre-stage-1 setup of the layout-v2 search — the
required levels, their numerical sections (with the Phase 20C.2A resolution
for implicit bodies), the footwall track, the authoritative portal and the
required centerline clearance — shared by ``LayoutV2Search.run()`` and by the
search-object-free certification restore
(``layout.certification.restore_candidate_policy``). The body of
``build_search_setup`` is the setup block ``run()`` carried before the
extraction, moved verbatim; a second copy anywhere else can drift and is a
defect. The only ordering difference: ``run()`` now records
``self._sections`` / ``self._track`` after the portal and required-clearance
statements instead of between the track and the portal — observable only if
one of those raised, and still before the section-error early return.

Leaf module: it must not import ``layout.search``, ``layout.results``,
``layout.certification`` or ``minegen.services``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from minegen.core.models import Scenario
from minegen.design.profile import required_clearance
from minegen.design.targets import default_portal
from minegen.layout.families import FootwallTrack, build_footwall_track
from minegen.layout.levels import LevelSections, RequiredLevel, required_levels
from minegen.layout.sections import SectionGeometryError, resolve_section_resolution
from minegen.world.orebody import TabularOrebody
from minegen.world.synthetic_world import SyntheticWorld

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class SearchSetup:
    """The setup products of one layout-v2 search over one generated world."""

    levels: list[RequiredLevel]
    sections: LevelSections
    section_error: SectionGeometryError | None
    track: FootwallTrack | None
    portal: FloatArray
    portal_generated: bool
    required_clearance: float


def build_search_setup(scenario: Scenario, world: SyntheticWorld) -> SearchSetup:
    """The setup block of ``LayoutV2Search.run()`` (verbatim): required
    levels, level sections (resolution attached for non-TABULAR bodies; a
    typed ``SectionGeometryError`` is CAPTURED, never raised — the search
    fails every candidate closed on it), footwall track, portal and the
    required clearance."""
    sc = scenario
    cfg = scenario.layout
    levels = required_levels(
        world.orebody,
        sc.mining.sublevel_interval,
        sc.design.top_mining_margin,
        sc.design.bottom_mining_margin,
    )
    sections = LevelSections(world.orebody, levels, cfg.section_sampling_spacing)
    # Phase 20C.2A: non-TABULAR level development anchors come from the
    # section(z) geometry, which needs a resolved sampling resolution.
    # Base stand-off = explicit access.anchorStandoff else the configured
    # footwall access offset (never the honesty-raised value). A typed
    # resolution/budget failure fails EVERY candidate closed below.
    section_error: SectionGeometryError | None = None
    if not isinstance(world.orebody, TabularOrebody):
        base_standoff = (
            cfg.access.anchor_standoff
            if cfg.access.anchor_standoff is not None
            else sc.ramp.footwall_access_offset
        )
        try:
            sections.set_resolution(
                resolve_section_resolution(
                    float(cfg.section_sampling_spacing), float(base_standoff)
                )
            )
        except SectionGeometryError as err:
            section_error = err
    track = build_footwall_track(world.orebody, sections)
    if sc.portal is not None:
        portal = np.array(sc.portal.as_tuple(), dtype=np.float64)
        generated = False
    else:
        portal = default_portal(sc, world.orebody, world.terrain)  # generic frame use
        generated = True
    req_clear = required_clearance(sc.design, sc.ramp, sc.tunnel_profile)
    return SearchSetup(
        levels=levels,
        sections=sections,
        section_error=section_error,
        track=track,
        portal=portal,
        portal_generated=generated,
        required_clearance=req_clear,
    )
