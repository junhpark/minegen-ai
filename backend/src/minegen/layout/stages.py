"""Layout-v2 stage context and anchor lens (AC-01G).

The state a layout-v2 stage needs, as ONE explicit frozen argument instead of
nine reach-ins into ``LayoutV2Search`` (Stage A §A4). A stage function takes a
``StageContext`` and nothing else from the search object; there is no ``self``
to reach through, so the invariant is carried by the type, not by discipline.

``AnchorLens`` names the three values that distinguish a stage-2 screen anchor
from a stage-4 planning anchor (rules 172 / 176): the level-entry stand-off,
the clearance field the offset backbone is a level set of, and the
offset-trace cache token that names that field. The screen lens always uses
the WORLD policy, the coarse stand-off and the ``"WORLD"`` token; the detailed
lens takes them from the candidate's own certification. ``build_anchors``
performs the one anchor loop both stages share.

Leaf module: it must not import ``layout.search`` or ``minegen.services``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from minegen.core.models import LayoutV2Config, RampConstraints, Scenario
from minegen.design.cost_field import ClearancePolicy, DesignCostEvaluator
from minegen.layout.access import AnchorFailure, LevelDevelopmentAnchor, build_anchor
from minegen.layout.certification import CandidateClearance, anchor_standoff
from minegen.layout.families import FootwallTrack, LayoutContext
from minegen.layout.levels import LevelSections, RequiredLevel
from minegen.layout.provider import SectionProvider
from minegen.world.synthetic_world import SyntheticWorld

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class StageContext:
    """Everything a layout-v2 stage reads that is not the candidate itself.

    ``world_policy`` / ``world_evaluator`` are the CONSTRUCTOR objects of the
    search (``LayoutV2Search.policy`` / ``.evaluator``) — identity matters:
    the offset-trace cache token is decided by ``policy is world_policy``
    inside the certification recipe (rule 172 / census O10). ``provider`` is
    the run's section-geometry authority and ``ctx`` the unchanged
    ``LayoutContext`` the families construct against; its ``sections`` /
    ``track`` / ``levels`` / ``reference`` are the provider's objects.
    """

    scenario: Scenario
    world: SyntheticWorld
    cfg: LayoutV2Config
    world_policy: ClearancePolicy
    world_evaluator: DesignCostEvaluator
    shape: Any
    station_merge_bound: float | None
    required_clearance: float
    provider: SectionProvider
    ctx: LayoutContext

    @property
    def ramp(self) -> RampConstraints:
        return self.scenario.ramp

    @property
    def mining_method(self) -> str:
        return str(self.scenario.mining.method.value)

    @property
    def levels(self) -> list[RequiredLevel]:
        """The SERVICEABLE required levels the stages iterate (rule 141)."""
        return self.ctx.levels

    @property
    def sections(self) -> LevelSections:
        return self.provider.sections

    @property
    def track(self) -> FootwallTrack:
        return self.provider.footwall_track


@dataclass(frozen=True)
class AnchorLens:
    """How ONE stage looks at the level-development anchors: the level-entry
    stand-off, the clearance measure the offset backbone is a level set of,
    and the deterministic cache token naming that measure."""

    standoff: float
    clearance: Callable[[FloatArray], FloatArray]
    trace_token: str


def screen_lens(sc: StageContext) -> AnchorLens:
    """Stage-2 geometric access screen (rule 176): the WORLD clearance
    policy, its coarse stand-off, the ``"WORLD"`` token — the same key the
    construction ``ServiceReference`` filled, so the screen never builds a
    second clearance field. It takes no candidate, by type."""
    return AnchorLens(
        standoff=anchor_standoff(sc.cfg, sc.scenario.ramp, sc.required_clearance, sc.world_policy),
        clearance=sc.world_policy.signed_clearance,
        trace_token="WORLD",
    )


def detailed_lens(sc: StageContext, clearance: CandidateClearance) -> AnchorLens:
    """Stage-4 level-access planning (rule 172): the CANDIDATE's certified
    policy, the stand-off that policy's error bound implies, and the token
    the certification recipe derived — ``"WORLD"`` for a non-refined
    candidate, the candidate id for a refined one."""
    return AnchorLens(
        standoff=anchor_standoff(sc.cfg, sc.scenario.ramp, sc.required_clearance, clearance.policy),
        clearance=clearance.policy.signed_clearance,
        trace_token=clearance.trace_token,
    )


def build_anchors(
    sc: StageContext, lens: AnchorLens, points: FloatArray
) -> list[LevelDevelopmentAnchor | AnchorFailure | None]:
    """The level-development anchors of one delivered centerline under one
    lens — the single definition of the loop the screen and the detailed
    stage both run (they differed only in the lens)."""
    return [
        build_anchor(
            sc.world.orebody,
            lv,
            sc.provider.sections,
            sc.track,
            points,
            lens.standoff,
            sc.mining_method,
            clearance=lens.clearance,
            policy_token=lens.trace_token,
            minimum_clearance=sc.required_clearance,
        )
        for lv in sc.ctx.levels
    ]
