from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from minegen.core.models import (
    BoundingBox,
    FaultConfig,
    GeologyConfig,
    OrebodyConfig,
    Point3D,
    RockQualityConfig,
    ScenarioCreate,
    TerrainConfig,
    WorldConfig,
)


def test_scenario_defaults_are_valid_and_camel_case_on_wire() -> None:
    s = ScenarioCreate()
    data = s.model_dump(by_alias=True)
    assert data["orebody"]["strikeDeg"] == 35.0
    assert data["ramp"]["maxGradient"] == 0.12
    assert data["ramp"]["footwallAccessOffset"] == 20.0
    # round-trip through camelCase JSON
    again = ScenarioCreate.model_validate(data)
    assert again == s


def test_orebody_height_is_down_dip_length() -> None:
    ob = OrebodyConfig(
        center=Point3D(x=0, y=0, z=0),
        strike_deg=35,
        dip_deg=70,
        length=600,
        height=350,
        thickness=12,
    )
    assert ob.vertical_extent == pytest.approx(350 * math.sin(math.radians(70)))
    wire = ob.model_dump(by_alias=True)
    assert wire["gradeCorrelationLengthXy"] == 80.0 and wire["gradeCorrelationLengthZ"] == 40.0


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Point3D.model_validate({"x": 0, "y": 0, "z": 0, "w": 1})


def test_fault_half_widths_validated() -> None:
    with pytest.raises(ValidationError):
        FaultConfig(
            origin=Point3D(x=0, y=0, z=0),
            strike_deg=10,
            dip_deg=60,
            core_half_width=50,
            influence_half_width=10,
        )


def test_fault_half_width_wire_names() -> None:
    f = FaultConfig(origin=Point3D(x=0, y=0, z=0), strike_deg=10, dip_deg=60)
    data = f.model_dump(by_alias=True)
    assert "coreHalfWidth" in data and "influenceHalfWidth" in data
    assert "coreWidth" not in data


def test_rock_quality_config_validated() -> None:
    with pytest.raises(ValidationError):
        RockQualityConfig(minimum=80, maximum=40)
    with pytest.raises(ValidationError):
        RockQualityConfig(mean=95, minimum=20, maximum=90)


def test_scenario_nests_geology() -> None:
    s = ScenarioCreate()
    data = s.model_dump(by_alias=True)
    assert "faults" not in data
    assert data["geology"]["faults"] == []
    assert data["geology"]["rockQuality"]["mean"] == 65.0
    assert isinstance(s.geology, GeologyConfig)


# -- world depth semantics (rule 35) -----------------------------------------


def test_world_depth_is_measured_below_reference_elevation() -> None:
    w = WorldConfig(size_x=1200, size_y=1200, depth=600)
    t = TerrainConfig(base_elevation=300.0)
    assert w.bottom_elevation(t.base_elevation) == -300.0

    b = w.bounds(t.base_elevation)
    assert b.min == Point3D(x=-600, y=-600, z=-300)
    assert b.max == Point3D(x=600, y=600, z=300)
    assert b.max.z - b.min.z == 600.0  # vertical span equals depth

    # terrain relief may lift the top without changing the bottom
    b2 = w.bounds(t.base_elevation, top_z=380.0)
    assert b2.min.z == -300 and b2.max.z == 380
    assert b2.contains(Point3D(x=0, y=0, z=0))
    assert not b2.contains(Point3D(x=0, y=0, z=-301))


def test_bounding_box_rejects_inverted() -> None:
    with pytest.raises(ValidationError):
        BoundingBox(min=Point3D(x=1, y=0, z=0), max=Point3D(x=0, y=0, z=0))


# -- finite-only API floats (rule 34) -----------------------------------------


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_api_models_reject_non_finite_point(bad: float) -> None:
    with pytest.raises(ValidationError):
        Point3D(x=bad, y=0.0, z=0.0)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_api_models_reject_non_finite_json_tokens(token: str) -> None:
    with pytest.raises(ValidationError):
        Point3D.model_validate_json(f'{{"x": {token}, "y": 0, "z": 0}}')


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_api_models_reject_non_finite_nested(bad: float) -> None:
    base = ScenarioCreate().model_dump(by_alias=True)
    base["orebody"]["center"]["z"] = bad
    with pytest.raises(ValidationError):
        ScenarioCreate.model_validate(base)
    base = ScenarioCreate().model_dump(by_alias=True)
    base["ramp"]["minTurnRadius"] = bad
    with pytest.raises(ValidationError):
        ScenarioCreate.model_validate(base)
