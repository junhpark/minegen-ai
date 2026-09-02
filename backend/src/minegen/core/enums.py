"""Shared enumerations.

These names are part of the API contract and are mirrored in
``frontend/src/types/enums.ts``. Add values, do not rename them.
"""

from __future__ import annotations

from enum import StrEnum


class ScenarioPreset(StrEnum):
    """Phase 17 scenario-realization presets (rule 119): realization happens
    BEFORE persistence; generate_world never draws hidden randomness."""

    BASELINE = "BASELINE"
    RANDOM_TABULAR = "RANDOM_TABULAR"
    RANDOM_ELLIPSOID = "RANDOM_ELLIPSOID"


class OrebodyType(StrEnum):
    TABULAR = "TABULAR"
    ELLIPSOID = "ELLIPSOID"
    PIPE = "PIPE"
    LENS = "LENS"


class NodeType(StrEnum):
    PORTAL = "PORTAL"
    JUNCTION = "JUNCTION"
    LEVEL_ENTRY = "LEVEL_ENTRY"
    STOPE_ACCESS = "STOPE_ACCESS"
    SHAFT_STATION = "SHAFT_STATION"
    CRUSHER = "CRUSHER"
    REFUGE = "REFUGE"
    FAN = "FAN"
    ROUTER = "ROUTER"
    SENSOR = "SENSOR"


class EdgeType(StrEnum):
    RAMP = "RAMP"
    DRIFT = "DRIFT"
    CROSSCUT = "CROSSCUT"
    RAISE = "RAISE"
    SHAFT = "SHAFT"


class ObjectState(StrEnum):
    """Temporal state of an excavation / stope at a given time."""

    NOT_BUILT = "NOT_BUILT"
    PLANNED = "PLANNED"
    DEVELOPING = "DEVELOPING"
    ACTIVE = "ACTIVE"
    MINED = "MINED"
    VOID = "VOID"
    BACKFILLED = "BACKFILLED"
    CLOSED = "CLOSED"


class TaskType(StrEnum):
    DEVELOP_RAMP = "DEVELOP_RAMP"
    DEVELOP_LEVEL = "DEVELOP_LEVEL"
    DEVELOP_CROSSCUT = "DEVELOP_CROSSCUT"
    DEVELOP_RAISE = "DEVELOP_RAISE"
    STOPE_PREPARATION = "STOPE_PREPARATION"
    STOPING = "STOPING"
    MUCKING = "MUCKING"
    BACKFILL = "BACKFILL"
    CURE_BACKFILL = "CURE_BACKFILL"


class MiningMethodType(StrEnum):
    LONGHOLE_OPEN_STOPING = "LONGHOLE_OPEN_STOPING"
    CUT_AND_FILL = "CUT_AND_FILL"
    ROOM_AND_PILLAR = "ROOM_AND_PILLAR"
    SUBLEVEL_CAVING = "SUBLEVEL_CAVING"
    SHRINKAGE_STOPING = "SHRINKAGE_STOPING"


class AssetType(StrEnum):
    """Placeable infrastructure assets for OSP."""

    WIFI_AP = "WIFI_AP"
    MESH_ROUTER = "MESH_ROUTER"
    UWB_ANCHOR = "UWB_ANCHOR"
    LORA_GATEWAY = "LORA_GATEWAY"
    REPEATER = "REPEATER"
    GAS_SENSOR = "GAS_SENSOR"
    TEMPERATURE_SENSOR = "TEMPERATURE_SENSOR"
    HUMIDITY_SENSOR = "HUMIDITY_SENSOR"
    AIR_VELOCITY_SENSOR = "AIR_VELOCITY_SENSOR"
    CONVERGENCE_SENSOR = "CONVERGENCE_SENSOR"
    SEISMIC_SENSOR = "SEISMIC_SENSOR"
    DUST_SENSOR = "DUST_SENSOR"
    CAMERA = "CAMERA"
    RTLS_ANCHOR = "RTLS_ANCHOR"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
