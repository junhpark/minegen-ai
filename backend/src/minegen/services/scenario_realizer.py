"""Phase 17 — deterministic scenario realization (preset + seed → fully
resolved :class:`ScenarioCreate`).

Architecture (rule 119): all stochastic parameter draws happen HERE, in an
explicit, non-persistent realization step. The resolved ScenarioCreate is
what gets persisted, so ``generate_world`` keeps its pure contract
(resolved Scenario → SyntheticWorld) with zero hidden randomness, and a
persisted scenario alone reproduces its world forever.

RNG domains (rule 121) — independent named sub-streams of the scenario
seed, so changing one domain's draw count can never shift another:

    terrain  [seed, 0x7E44A1]   (existing — untouched)
    rock     [seed, 0x20C4]     (existing — untouched)
    grade    [seed, 0x6A4D]     (existing — untouched)
    orebody  [seed, 0x0B0D17]   (new, Phase 17; Phase 19 RANDOM_WARPED_VEIN
                                 draws its morphology from this SAME stream)
    faults   [seed, 0xFA0117]   (new, Phase 17)
"""

from __future__ import annotations

import numpy as np

from minegen.core.enums import OrebodyType, ScenarioPreset
from minegen.core.models import (
    FaultConfig,
    GeologyConfig,
    HarmonicMode,
    OrebodyConfig,
    Point3D,
    RockQualityConfig,
    ScenarioCreate,
    WarpedVeinConfig,
)
from minegen.world.geology import FaultPlane
from minegen.world.orebody import build_orebody
from minegen.world.warped_vein import (
    WarpedVeinGeometryBudgetError,
    WarpedVeinMorphology,
)

OREBODY_REALIZATION_STREAM = 0x0B0D17
FAULT_REALIZATION_STREAM = 0xFA0117

_FAULT_RETRIES = 8
_OREBODY_RETRIES = 64
#: horizontal safety margin and top (cover) margin applied to the ACTUAL
#: analytic orebody AABB, not to the centre (rule 125)
HORIZONTAL_MARGIN_M = 80.0
TOP_MARGIN_M = 40.0

#: Phase 19 warped-vein morphology acceptance (cheap 2-D diagnostics on the
#: authoritative implicit morphology; a candidate failing any check is
#: rejected whole and the next deterministic draw is tried)
MIN_PINCH_SWELL_RANGE = 0.15  # max − min interior thickness multiplier
MIN_WARP_FRACTION = 0.5  # (max − min mid-surface) / warp amplitude
MIN_EDGE_ASYMMETRY = 0.05  # relative difference between opposite edges
#: low-order 2-D modes the realizer may draw from (shape model 1, k ≤ 2)
_PLANE_MODE_PAIRS: tuple[tuple[int, int], ...] = (
    (1, 0),
    (0, 1),
    (1, 1),
    (2, 0),
    (0, 2),
    (2, 1),
    (1, 2),
)
#: down-dip-only modes for the lateral centreline deviation
_DEVIATION_MODE_PAIRS: tuple[tuple[int, int], ...] = ((0, 1), (0, 2), (0, 3))


class ScenarioRealizationError(ValueError):
    """Bounded deterministic retries exhausted or options invalid."""


def _baseline_geology() -> GeologyConfig:
    """EXACTLY the Phase 16 user-facing baseline (ScenarioPanel 'one fault'
    ON): explicit values, zero random draws. Do not drift these numbers —
    the UI-baseline regression pins them."""
    return GeologyConfig(
        rock_quality=RockQualityConfig(
            mean=65.0,
            std=12.0,
            correlation_length_xy=80.0,
            correlation_length_z=40.0,
            minimum=20.0,
            maximum=90.0,
        ),
        faults=[
            FaultConfig(
                origin=Point3D(x=-100.0, y=-200.0, z=0.0),
                strike_deg=120.0,
                dip_deg=65.0,
                core_half_width=2.5,
                influence_half_width=20.0,
                core_penalty=50.0,
                damage_zone_penalty=10.0,
            )
        ],
    )


def _world_bounds(base: ScenarioCreate) -> tuple[np.ndarray, np.ndarray]:
    box = base.world.bounds(base.terrain.base_elevation)
    return (
        np.array(box.min.as_tuple(), dtype=np.float64),
        np.array(box.max.as_tuple(), dtype=np.float64),
    )


def orebody_within_world(cfg: OrebodyConfig, base: ScenarioCreate) -> bool:
    """Rule 125 acceptance gate: the ACTUAL analytic orebody solid — not its
    centre — must sit inside the model volume.

    A tabular slab or ellipsoid is rotated by strike/dip, so a centre-only
    test says nothing about where the body actually reaches; the world AABB
    of the built geometry is the only sound source. Horizontal edges keep
    the ``HORIZONTAL_MARGIN_M`` safety margin, the top keeps
    ``TOP_MARGIN_M`` of cover below the terrain reference elevation, and
    the bottom must stay above the model floor.
    """
    lo, hi = _world_bounds(base)
    bbox_min, bbox_max = build_orebody(cfg).bounding_box()
    return bool(
        bbox_min[0] >= lo[0] + HORIZONTAL_MARGIN_M
        and bbox_max[0] <= hi[0] - HORIZONTAL_MARGIN_M
        and bbox_min[1] >= lo[1] + HORIZONTAL_MARGIN_M
        and bbox_max[1] <= hi[1] - HORIZONTAL_MARGIN_M
        and bbox_min[2] >= lo[2]
        and bbox_max[2] <= hi[2] - TOP_MARGIN_M
    )


def _realize_orebody(seed: int, orebody_type: OrebodyType, base: ScenarioCreate) -> OrebodyConfig:
    """Deterministic orebody parameters whose BUILT geometry lies inside the
    model volume (rule 125): candidates are drawn from the orebody
    sub-stream and accepted or rejected whole — never clamped — with a
    bounded retry budget and an explicit typed failure on exhaustion.

    Sampling ranges are chosen so a rotated body of the largest sampled
    size still fits: the world is 1200 x 1200 m with an 80 m margin on each
    side, leaving a 1040 m usable span, so the centre range and the
    length/height ranges below keep the acceptance rate high while the AABB
    gate remains the authority.
    """
    rng = np.random.default_rng([seed, OREBODY_REALIZATION_STREAM])
    for _ in range(_OREBODY_RETRIES):
        cfg = OrebodyConfig(
            orebody_type=orebody_type,
            center=Point3D(
                x=float(rng.uniform(-180.0, 180.0)),
                y=float(rng.uniform(-180.0, 180.0)),
                z=float(rng.uniform(-150.0, -20.0)),
            ),
            strike_deg=float(rng.uniform(0.0, 360.0)),
            dip_deg=float(rng.uniform(45.0, 80.0)),
            length=float(rng.uniform(350.0, 650.0)),
            height=float(rng.uniform(200.0, 380.0)),
            thickness=float(rng.uniform(6.0, 25.0)),
            mean_grade=float(rng.uniform(2.5, 6.0)),
            grade_variability=float(rng.uniform(0.2, 0.45)),
        )
        if orebody_within_world(cfg, base):
            return cfg
    raise ScenarioRealizationError(
        "orebody realization exhausted bounded retries without a candidate whose "
        "geometry fits inside the model volume"
    )


def _draw_modes(
    rng: np.random.Generator, pairs: tuple[tuple[int, int], ...], count: int
) -> list[HarmonicMode]:
    """``count`` distinct low-order modes with random phases and weights of
    magnitude ≥ 0.25 (so every drawn mode actually shapes the body)."""
    picks = rng.choice(len(pairs), size=count, replace=False)
    modes: list[HarmonicMode] = []
    for idx in sorted(int(i) for i in picks):
        ku, kv = pairs[idx]
        sign = 1.0 if rng.uniform() < 0.5 else -1.0
        modes.append(
            HarmonicMode(
                ku=ku,
                kv=kv,
                phase_u=float(rng.uniform(0.0, 2.0 * np.pi)),
                phase_v=float(rng.uniform(0.0, 2.0 * np.pi)),
                weight=sign * float(rng.uniform(0.25, 1.0)),
            )
        )
    return modes


def warped_vein_morphology_valid(cfg: OrebodyConfig) -> tuple[bool, str]:
    """Rule 139 acceptance on the ACTUAL implicit morphology: one connected
    planform, the guaranteed thickness floor, a real pinch/swell range, a
    real warp and an asymmetric outline, all finite, within the derived
    geometry budget. Returns ``(ok, reason)``."""
    try:
        ob = build_orebody(cfg)
    except WarpedVeinGeometryBudgetError as exc:
        return False, f"geometry budget: {exc}"
    assert cfg.warped_vein is not None
    d = WarpedVeinMorphology(cfg).diagnostics()
    values = [v for v in d.values() if isinstance(v, float)]
    if not all(np.isfinite(values)):
        return False, "non-finite morphology diagnostics"
    if d["planformConnectedComponents"] != 1:
        return False, f"planform has {d['planformConnectedComponents']} components"
    if d["minInteriorThicknessMultiplier"] is None:
        return False, "no interior samples"
    if d["minInteriorThicknessMultiplier"] < cfg.warped_vein.pinch_floor_ratio - 1e-9:
        return False, "interior thickness below the pinch floor"
    swell = d["maxInteriorThicknessMultiplier"] - d["minInteriorThicknessMultiplier"]
    if swell < MIN_PINCH_SWELL_RANGE:
        return False, f"pinch/swell range {swell:.3f} too small"
    warp = d["midSurfaceMax"] - d["midSurfaceMin"]
    if cfg.warped_vein.warp_amplitude > 0 and warp < MIN_WARP_FRACTION * (
        cfg.warped_vein.warp_amplitude
    ):
        return False, f"warp range {warp:.1f} m too small"
    if max(d["strikeEdgeAsymmetry"], d["dipEdgeAsymmetry"]) < MIN_EDGE_ASYMMETRY:
        return False, "outline not asymmetric"
    lo, hi = ob.bounding_box()
    if not (np.all(np.isfinite(lo)) and np.all(np.isfinite(hi))):
        return False, "non-finite bounding box"
    return True, "ok"


def _realize_warped_vein(seed: int, base: ScenarioCreate) -> OrebodyConfig:
    """RANDOM_WARPED_VEIN: same orebody sub-stream (rule 121 — no new key),
    same world-fit gate as the analytic presets (rule 125) plus the
    morphology acceptance above. Every control AND every mode coefficient
    is drawn here and persisted resolved (rule 136); nothing is regenerated
    from the seed later. Candidates are accepted or rejected whole."""
    rng = np.random.default_rng([seed, OREBODY_REALIZATION_STREAM])
    for _ in range(_OREBODY_RETRIES):
        length = float(rng.uniform(350.0, 650.0))
        height = float(rng.uniform(200.0, 380.0))
        thickness = float(rng.uniform(8.0, 25.0))
        pinch_floor = float(rng.uniform(0.3, 0.55))
        vein = WarpedVeinConfig(
            shape_model_version=1,
            warp_amplitude=float(rng.uniform(0.03, 0.09)) * height,
            centerline_deviation=float(rng.uniform(0.05, 0.15)) * length,
            outline_irregularity=float(rng.uniform(0.15, 0.4)),
            thickness_variability=float(rng.uniform(0.25, 1.0 - pinch_floor)),
            pinch_floor_ratio=pinch_floor,
            edge_taper=float(rng.uniform(0.3, 0.8)),
            geometry_resolution=5.0,
            warp_modes=_draw_modes(rng, _PLANE_MODE_PAIRS, 3),
            deviation_modes=_draw_modes(rng, _DEVIATION_MODE_PAIRS, 2),
            outline_modes=_draw_modes(rng, _PLANE_MODE_PAIRS, 3),
            thickness_modes=_draw_modes(rng, _PLANE_MODE_PAIRS, 3),
        )
        cfg = OrebodyConfig(
            orebody_type=OrebodyType.WARPED_VEIN,
            center=Point3D(
                x=float(rng.uniform(-180.0, 180.0)),
                y=float(rng.uniform(-180.0, 180.0)),
                z=float(rng.uniform(-150.0, -20.0)),
            ),
            strike_deg=float(rng.uniform(0.0, 360.0)),
            dip_deg=float(rng.uniform(45.0, 80.0)),
            length=length,
            height=height,
            thickness=thickness,
            mean_grade=float(rng.uniform(2.5, 6.0)),
            grade_variability=float(rng.uniform(0.2, 0.45)),
            warped_vein=vein,
        )
        if not orebody_within_world(cfg, base):
            continue
        ok, _reason = warped_vein_morphology_valid(cfg)
        if ok:
            return cfg
    raise ScenarioRealizationError(
        "warped-vein realization exhausted bounded retries without a candidate that "
        "fits the model volume and passes the morphology acceptance checks"
    )


def _realize_faults(seed: int, count: int, base: ScenarioCreate) -> list[FaultConfig]:
    """Deterministic fault set; every generated plane must actually cut the
    model volume (verified with FaultPlane.clip_to_box) within bounded
    per-fault retries."""
    if count < 0 or count > 6:
        raise ScenarioRealizationError("fault count must be between 0 and 6")
    rng = np.random.default_rng([seed, FAULT_REALIZATION_STREAM])
    lo, hi = _world_bounds(base)
    faults: list[FaultConfig] = []
    for index in range(count):
        for _ in range(_FAULT_RETRIES):
            core = float(rng.uniform(1.5, 4.0))
            cfg = FaultConfig(
                origin=Point3D(
                    x=float(rng.uniform(-400.0, 400.0)),
                    y=float(rng.uniform(-400.0, 400.0)),
                    z=float(rng.uniform(-200.0, 100.0)),
                ),
                strike_deg=float(rng.uniform(0.0, 360.0)),
                dip_deg=float(rng.uniform(45.0, 85.0)),
                core_half_width=core,
                influence_half_width=float(rng.uniform(max(12.0, core * 3.0), 30.0)),
            )
            if FaultPlane.from_config(cfg).clip_to_box(lo, hi).shape[0] >= 3:
                faults.append(cfg)
                break
        else:
            raise ScenarioRealizationError(
                f"fault {index + 1}/{count} exhausted bounded retries without "
                "intersecting the model volume"
            )
    return faults


def realize_scenario(
    preset: ScenarioPreset, seed: int, fault_count: int | None = None
) -> ScenarioCreate:
    """preset + seed (+ options) → fully resolved ScenarioCreate.

    BASELINE ignores randomization entirely and reproduces the Phase 16
    user-facing baseline mine. RANDOM_* presets draw orebody and fault
    parameters from their OWN independent sub-streams (rule 121), so e.g.
    changing the fault count never changes the realized orebody.
    """
    base = ScenarioCreate(seed=seed)
    if preset is ScenarioPreset.BASELINE:
        if fault_count is not None and fault_count != 1:
            raise ScenarioRealizationError("BASELINE has exactly one fixed fault")
        return ScenarioCreate(
            name="Baseline synthetic mine", seed=seed, geology=_baseline_geology()
        )
    count = 2 if fault_count is None else fault_count
    if preset is ScenarioPreset.RANDOM_WARPED_VEIN:
        orebody = _realize_warped_vein(seed, base)
    else:
        orebody_type = (
            OrebodyType.ELLIPSOID
            if preset is ScenarioPreset.RANDOM_ELLIPSOID
            else OrebodyType.TABULAR
        )
        orebody = _realize_orebody(seed, orebody_type, base)
    faults = _realize_faults(seed, count, base)
    return ScenarioCreate(
        name=f"{preset.value.title().replace('_', ' ')} mine",
        seed=seed,
        orebody=orebody,
        geology=GeologyConfig(rock_quality=RockQualityConfig(), faults=faults),
    )
