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
    #: Phase 19: deterministic synthetic irregular implicit orebody
    RANDOM_WARPED_VEIN = "RANDOM_WARPED_VEIN"


class RampFamily(StrEnum):
    """Layout-v2 parametric ramp families (rule 142). Lives in the
    dependency-neutral core so schema validation can size the shortlist
    floor from ``FAMILY_ORDER`` without importing the layout package
    (Phase 20B.1-v2 1.3); ``layout/families.py`` re-exports both names."""

    SPIRAL = "SPIRAL"
    LONGITUDINAL = "LONGITUDINAL"
    SWITCHBACK = "SWITCHBACK"


#: frozen family enumeration order (rule 142); its length is the shortlist
#: floor — every declared family holds one reserved slot (rule 165)
FAMILY_ORDER: tuple[RampFamily, ...] = (
    RampFamily.SPIRAL,
    RampFamily.LONGITUDINAL,
    RampFamily.SWITCHBACK,
)


class OrebodyType(StrEnum):
    TABULAR = "TABULAR"
    ELLIPSOID = "ELLIPSOID"
    PIPE = "PIPE"
    LENS = "LENS"
    #: Phase 19: warped-vein implicit solid (rule 133). PIPE and LENS keep
    #: their own reserved future semantics and are NOT aliases of it.
    WARPED_VEIN = "WARPED_VEIN"


class DistanceContract(StrEnum):
    """How an orebody answers distance queries (Phase 19, rule 134).

    EXACT_METRIC_SDF
        ``signed_distance`` is the exact Euclidean signed distance to the
        solid's surface (TABULAR, ELLIPSOID).
    DERIVED_APPROXIMATE_CLEARANCE
        the solid is defined by an implicit membership function; only a
        lattice-derived, explicitly approximate signed clearance exists
        (WARPED_VEIN). It never drives hard engineering buffers (rule 135).
    """

    EXACT_METRIC_SDF = "EXACT_METRIC_SDF"
    DERIVED_APPROXIMATE_CLEARANCE = "DERIVED_APPROXIMATE_CLEARANCE"


class NodeType(StrEnum):
    PORTAL = "PORTAL"
    JUNCTION = "JUNCTION"
    LEVEL_ENTRY = "LEVEL_ENTRY"
    #: Phase 20B: turnout on the main ramp where a level access leaves it
    RAMP_JUNCTION = "RAMP_JUNCTION"
    #: Phase 20B: terminal of the main ramp below the last turnout
    RAMP_END = "RAMP_END"
    STOPE_ACCESS = "STOPE_ACCESS"
    SHAFT_STATION = "SHAFT_STATION"
    CRUSHER = "CRUSHER"
    REFUGE = "REFUGE"
    FAN = "FAN"
    ROUTER = "ROUTER"
    SENSOR = "SENSOR"


class EdgeType(StrEnum):
    RAMP = "RAMP"
    #: Phase 20B: branch drive from a RAMP_JUNCTION to a LEVEL_ENTRY
    LEVEL_ACCESS = "LEVEL_ACCESS"
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
    #: Phase 20B: ramp-junction → level-entry branch drive
    DEVELOP_LEVEL_ACCESS = "DEVELOP_LEVEL_ACCESS"
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
