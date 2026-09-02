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
    orebody  [seed, 0x0B0D17]   (new, Phase 17)
    faults   [seed, 0xFA0117]   (new, Phase 17)
"""

from __future__ import annotations

import numpy as np

from minegen.core.enums import OrebodyType, ScenarioPreset
from minegen.core.models import (
    FaultConfig,
    GeologyConfig,
    OrebodyConfig,
    Point3D,
    RockQualityConfig,
    ScenarioCreate,
)
from minegen.world.geology import FaultPlane

OREBODY_REALIZATION_STREAM = 0x0B0D17
FAULT_REALIZATION_STREAM = 0xFA0117

_FAULT_RETRIES = 8
_OREBODY_RETRIES = 16


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


def _realize_orebody(seed: int, orebody_type: OrebodyType, base: ScenarioCreate) -> OrebodyConfig:
    """Deterministic orebody parameters, substantially inside the model
    volume (rule: bounded retries, explicit failure — never silent
    clipping)."""
    rng = np.random.default_rng([seed, OREBODY_REALIZATION_STREAM])
    lo, hi = _world_bounds(base)
    margin = 80.0
    for _ in range(_OREBODY_RETRIES):
        cfg = OrebodyConfig(
            orebody_type=orebody_type,
            center=Point3D(
                x=float(rng.uniform(-250.0, 250.0)),
                y=float(rng.uniform(-250.0, 250.0)),
                z=float(rng.uniform(-150.0, 50.0)),
            ),
            strike_deg=float(rng.uniform(0.0, 360.0)),
            dip_deg=float(rng.uniform(45.0, 80.0)),
            length=float(rng.uniform(350.0, 700.0)),
            height=float(rng.uniform(200.0, 400.0)),
            thickness=float(rng.uniform(6.0, 25.0)),
            mean_grade=float(rng.uniform(2.5, 6.0)),
            grade_variability=float(rng.uniform(0.2, 0.45)),
        )
        c = np.array(cfg.center.as_tuple())
        if (
            lo[0] + margin <= c[0] <= hi[0] - margin
            and lo[1] + margin <= c[1] <= hi[1] - margin
            and lo[2] + cfg.vertical_extent / 2.0 <= c[2] <= hi[2] - 40.0
        ):
            return cfg
    raise ScenarioRealizationError("orebody realization exhausted bounded retries")


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
    orebody_type = (
        OrebodyType.ELLIPSOID if preset is ScenarioPreset.RANDOM_ELLIPSOID else OrebodyType.TABULAR
    )
    count = 2 if fault_count is None else fault_count
    orebody = _realize_orebody(seed, orebody_type, base)
    faults = _realize_faults(seed, count, base)
    return ScenarioCreate(
        name=f"{preset.value.title().replace('_', ' ')} mine",
        seed=seed,
        orebody=orebody,
        geology=GeologyConfig(rock_quality=RockQualityConfig(), faults=faults),
    )
