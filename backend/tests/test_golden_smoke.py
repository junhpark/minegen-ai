"""Golden-scenario SMOKE subset (Phase 18 task 0, rule 132).

Runs the representative subset of the golden suite end-to-end and pins the
HARD CONTRACT (stage success + integer structure) against the committed
Phase-17 baseline. Quality metrics are NOT asserted here — they are compared
and reported by the explicit command:

    python -m minegen.regression run --suite full --label <name>
    python -m minegen.regression compare golden/phase17_baseline.json golden/<name>.json
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from minegen.regression.golden import (
    SMOKE_KEYS,
    case_by_key,
    load_report,
    measure_exposure,
    resample_polyline,
    run_case,
)

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
BASELINE = GOLDEN_DIR / "phase17_baseline.json"


def test_baseline_report_is_committed_and_complete() -> None:
    report = load_report(BASELINE)
    keys = {c["key"] for c in report["cases"]}
    assert set(SMOKE_KEYS) <= keys
    assert report["caseCount"] == len(report["cases"]) >= 20
    assert report["poorRockThreshold"] == 40.0


@pytest.mark.parametrize("key", SMOKE_KEYS)
def test_golden_smoke_contract_matches_baseline(key: str, tmp_path: Path) -> None:
    baseline = {c["key"]: c for c in load_report(BASELINE)["cases"]}[key]
    record = run_case(case_by_key(key), tmp_path / key)
    assert record["contract"] == baseline["contract"], record["notes"]
    for name, value in record["metrics"].items():
        if isinstance(value, float):
            assert math.isfinite(value), name


def test_resample_and_exposure_are_exact_on_a_synthetic_line() -> None:
    import numpy as np

    from minegen.core.models import FaultConfig, Point3D
    from minegen.world.geology import FaultPlane

    line = np.array([[0.0, 0.0, 0.0], [100.0, 0.0, 0.0]])
    mids, lens = resample_polyline(line, 2.0)
    assert mids.shape == (50, 3) and lens.sum() == pytest.approx(100.0)
    # vertical fault plane x = 50 with 2.5 m core and 10 m influence half-widths
    fault = FaultPlane.from_config(
        FaultConfig(
            origin=Point3D(x=50.0, y=0.0, z=0.0),
            strike_deg=0.0,
            dip_deg=90.0,
            core_half_width=2.5,
            influence_half_width=10.0,
        )
    )
    exposure = measure_exposure([line], [fault], lambda p: np.full(p.shape[0], 30.0))
    assert exposure.fault_crossings == 1
    assert exposure.length_fault_core == pytest.approx(4.0, abs=2.0)
    assert exposure.length_fault_damage == pytest.approx(16.0, abs=2.0)
    assert exposure.length_poor_rock == pytest.approx(100.0)
    assert exposure.total_length == pytest.approx(100.0)
