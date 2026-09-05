"""Names of the derived artifacts that OWN development geometry (rule 68).

Shared by the builders that resolve ``geometryRef.artifact`` (network,
scheduling, infrastructure) and by the services that persist them, so a
RAMP owner added by a later phase is declared in exactly one place.
"""

from __future__ import annotations

LEGACY_RAMP_ARTIFACT = "decline_smoothed.json"
LAYOUT_V2_ARTIFACT = "layout_v2.json"
LAYOUT_V2_SELECTED_ARTIFACT = "layout_v2_selected.json"
#: Phase 20B: ramp junctions + level-access branches of the selected candidate
LEVEL_ACCESSES_ARTIFACT = "level_accesses.json"
LEVELS_ARTIFACT = "levels.json"
RAMP_SOURCE_FILE = "ramp_source.json"

#: every artifact that may own RAMP geometry (Phase 05 legacy smoothed
#: decline, Phase 20A layout-v2 selected effective ramp); RAMP owners store
#: their polylines under ``segments[].effectiveCenterline``
RAMP_OWNING_ARTIFACTS: tuple[str, ...] = (LEGACY_RAMP_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT)
