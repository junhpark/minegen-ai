"""Engineering unit helpers.

Internal units: meters, tonnes, days, degrees for angles in schemas,
radians inside numerical code. Gradient is always vertical/horizontal.
"""

from __future__ import annotations

import math

TONNES_PER_M3_WATER = 1.0


def gradient_to_degrees(gradient: float) -> float:
    """0.12 → 6.84°"""
    return math.degrees(math.atan(gradient))


def degrees_to_gradient(angle_deg: float) -> float:
    return math.tan(math.radians(angle_deg))


def gradient_to_percent(gradient: float) -> float:
    return gradient * 100.0


def percent_to_gradient(percent: float) -> float:
    return percent / 100.0


def gradient_to_ratio(gradient: float) -> str:
    """0.12 → '1:8.3' (mining convention: 1 vertical in N horizontal)."""
    if gradient == 0:
        return "flat"
    return f"1:{1.0 / abs(gradient):.1f}"


def volume_to_tonnes(volume_m3: float, density_t_per_m3: float) -> float:
    return volume_m3 * density_t_per_m3


def horseshoe_area(width: float, wall_height: float, crown_radius: float) -> float:
    """Cross-section area of a horseshoe profile: rectangle plus a circular
    segment crown. For ``crown_radius == width / 2`` the crown is a semicircle."""
    half = width / 2.0
    if crown_radius < half:
        raise ValueError("crown_radius must be >= width / 2 for a valid arch")
    # circular segment with chord = width and radius = crown_radius
    theta = 2.0 * math.asin(half / crown_radius)  # central angle
    segment = 0.5 * crown_radius**2 * (theta - math.sin(theta))
    return width * wall_height + segment
