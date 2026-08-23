from __future__ import annotations

import math

import pytest

from minegen.core.units import (
    degrees_to_gradient,
    gradient_to_degrees,
    gradient_to_ratio,
    horseshoe_area,
)


def test_gradient_degree_roundtrip() -> None:
    for g in (0.0, 0.04, 0.12, 0.15):
        assert degrees_to_gradient(gradient_to_degrees(g)) == pytest.approx(g)


def test_gradient_ratio_string() -> None:
    assert gradient_to_ratio(0.125) == "1:8.0"
    assert gradient_to_ratio(0.0) == "flat"


def test_horseshoe_area_semicircular_crown() -> None:
    w, h, r = 5.0, 2.5, 2.5
    assert horseshoe_area(w, h, r) == pytest.approx(w * h + math.pi * r**2 / 2)


def test_horseshoe_area_rejects_flat_crown() -> None:
    with pytest.raises(ValueError):
        horseshoe_area(5.0, 2.5, 2.0)
