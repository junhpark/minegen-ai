"""Layout-v2 section-geometry provider (AC-01G).

ONE named authority for the section geometry of one layout-v2 search run:
the level sections (with their offset-/footwall-trace caches), the footwall
track, the serviceable required levels and the Phase 20C.4 construction
``ServiceReference``. It replaces the run-owned ``LayoutV2Search._sections``
/ ``_track`` / ``_reference`` attributes, so no stage ever reaches back into
the search object for geometry.

``build_section_provider`` calls the unchanged shared setup
(``layout.setup.build_search_setup``) and then builds the ``ServiceReference``
under exactly the condition ``run()`` used to: a section-geometry failure, no
serviceable level or no footwall track leaves ``reference = None`` and the
search returns early. The setup products the search itself consumes (all
required levels, the section error, the portal, the required clearance) stay
on the returned ``SearchSetup``; the provider carries what the stages and the
``LayoutContext`` see.

The provider is frozen, but it is NOT immutable in the deep sense:
``LevelSections`` memoizes section geometry and traces. That is a cost
question, never a correctness one — every cached value (and every cached
typed failure) is a pure function of its key, so no contract may depend on
whether a fill has already happened. ``set_resolution`` is called exactly
once, inside ``build_search_setup``, BEFORE the provider exists.

Leaf module: it must not import ``layout.search``, ``layout.results``,
``layout.stages`` or ``minegen.services``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from minegen.core.models import Scenario
from minegen.design.cost_field import ClearancePolicy
from minegen.layout.access import BACKBONE_END_MARGIN, MIN_DEVELOPMENT_TRACE_LENGTH
from minegen.layout.certification import anchor_standoff
from minegen.layout.families import (
    RAMP_CORRIDOR_MARGIN_WIDTHS,
    FootwallTrack,
    effective_footwall_standoff,
)
from minegen.layout.levels import LevelSections, RequiredLevel
from minegen.layout.reference import ServiceReference, build_service_reference
from minegen.layout.setup import SearchSetup, build_search_setup
from minegen.world.synthetic_world import SyntheticWorld

FloatArray = npt.NDArray[np.float64]


class SectionProviderError(RuntimeError):
    """The provider was asked for geometry it does not have (no footwall
    track). Explicit, never an ``assert``: a stage precondition must survive
    ``python -O``."""


@dataclass(frozen=True)
class SectionProvider:
    """The section-geometry authority of ONE layout-v2 search run.

    ``sections``, ``track``, ``serviceable`` and ``reference`` are the very
    objects the stages, the ``LayoutContext`` and the post-run facade use —
    identity, not equality.

    The authority it carries is CONSTRUCTION, not access: it is the one place
    a run's ``LevelSections``, footwall track and ``ServiceReference`` are
    built, and consumers read them off it. AC-01G Stage D (D3) removed a set
    of delegating ``section`` / ``geometry`` / ``footwall_trace`` /
    ``offset_trace`` forwarders that had ZERO callers — every real consumer
    reaches ``provider.sections`` and calls ``LevelSections`` directly — and
    an unexercised second route into a cache whose KEY is what this step
    exists to protect is a liability, not a facade.

    Deep immutability is not claimed: ``LevelSections`` holds three lazy
    caches and ``serviceable`` is a list, so ``frozen=True`` here means the
    four references cannot be rebound, nothing more. Nor is the caches' own
    failure path a pure value: ``LevelSections`` re-raises the SAME cached
    exception object on every hit, so its traceback grows two frames per
    raise and its ``diagnostics`` dict is one object shared by every
    ``AnchorFailure`` built from it (AC-01G Stage D, D1 — measured, and left
    as a recorded residual because it predates this step and lives in a
    module AC-01G does not touch).
    """

    sections: LevelSections
    track: FootwallTrack | None
    serviceable: list[RequiredLevel]
    reference: ServiceReference | None

    @property
    def footwall_track(self) -> FootwallTrack:
        """The run's footwall track, or the explicit refusal."""
        if self.track is None:
            raise SectionProviderError("the section provider has no footwall track")
        return self.track


def context_provider(
    sections: LevelSections,
    track: FootwallTrack,
    serviceable: list[RequiredLevel],
    reference: ServiceReference | None,
) -> SectionProvider:
    """The post-run provider view over the objects a ``LayoutContext``
    already carries (AC-01G Q6): the run's sections, footwall track,
    serviceable levels and construction reference, by identity. Nothing is
    recomputed, nothing is invented — this is why ``_ctx`` alone is enough to
    re-enter the stage-4 certification path after ``run()``."""
    return SectionProvider(
        sections=sections, track=track, serviceable=serviceable, reference=reference
    )


def build_section_provider(
    scenario: Scenario, world: SyntheticWorld, world_policy: ClearancePolicy
) -> tuple[SearchSetup, SectionProvider]:
    """The setup products of one search plus its section-geometry provider.

    ONE measured consequence of the move, recorded because the characterization
    freeze is structurally unable to see it (its mask drops every ``*Seconds``
    key): the ``ServiceReference`` build now happens BEFORE ``run()`` starts its
    setup clock, so its cost is billed to ``performance.setupSeconds`` instead
    of ``performance.constructAndCheapSeconds``. Both keys are persisted in
    ``layout_v2.json``. Measured on WARPED_VEIN-301: 7.876 s of a 10.842 s
    ``setupSeconds`` is work that used to be billed to the other key; TABULAR is
    unaffected (the reference is inactive there). No engineering quantity moves
    and the ``performance`` key INSERTION ORDER is unchanged, but a historical
    comparison of those two fields across this commit is invalid.

    The ``ServiceReference`` build is the block ``LayoutV2Search.run()``
    carried before the extraction, moved verbatim — including BOTH stand-offs
    it takes: ``standoff`` is the ramp CORRIDOR stand-off
    (``effective_footwall_standoff``, rule 170) and ``anchor_standoff`` is the
    level-development ANCHOR stand-off (rule 158 / 146 honesty), which is also
    what the WORLD-token offset-trace cache key is built from. Confusing the
    two changes both the cache key and the delivered trace geometry.
    """
    setup = build_search_setup(scenario, world)
    serviceable = setup.sections.serviceable()
    reference: ServiceReference | None = None
    if setup.section_error is None and serviceable and setup.track is not None:
        # Phase 20C.4: the conservative construction ServiceReference — the
        # WORLD-policy offset traces stage 4 builds for coarse anchors (same
        # cache token), read once here so the ramp corridor and the level
        # anchors share ONE spacing reference (rule 170 vs rules 158 / 178).
        # Inactive (delta ≡ 0, bit-identical) on TABULAR and for an explicit
        # footwallStandoff; per-level trace failures are reported, never hidden.
        cfg = scenario.layout
        standoff_value, standoff_source = effective_footwall_standoff(cfg, scenario.ramp)
        reference = build_service_reference(
            setup.sections,
            serviceable,
            setup.track.w_h,
            orebody=world.orebody,
            clearance=world_policy.signed_clearance,
            basis=world_policy.basis,
            standoff=standoff_value,
            standoff_source=standoff_source,
            margin=RAMP_CORRIDOR_MARGIN_WIDTHS * float(scenario.ramp.tunnel_width),
            anchor_standoff=anchor_standoff(
                cfg, scenario.ramp, setup.required_clearance, world_policy
            ),
            min_trace_length=MIN_DEVELOPMENT_TRACE_LENGTH,
            end_margin=BACKBONE_END_MARGIN,
            required_clearance=setup.required_clearance,
        )
    return setup, SectionProvider(
        sections=setup.sections,
        track=setup.track,
        serviceable=serviceable,
        reference=reference,
    )
