"""Names of the derived artifacts that OWN development geometry (rule 68).

Shared by the builders that resolve ``geometryRef.artifact`` (network,
scheduling, infrastructure) and by the services that persist them, so a
RAMP owner added by a later phase is declared in exactly one place.
"""

from __future__ import annotations

from typing import Literal

#: the two files of the scenario directory that root every derived artifact
SCENARIO_FILE = "scenario.json"
ARRAYS_FILE = "arrays.npz"

#: legacy Phase 03–05 chain (Hybrid-A*): access targets and the raw decline
TARGETS_ARTIFACT = "targets.json"
DECLINE_ARTIFACT = "decline.json"
LEGACY_RAMP_ARTIFACT = "decline_smoothed.json"
LAYOUT_V2_ARTIFACT = "layout_v2.json"
LAYOUT_V2_SELECTED_ARTIFACT = "layout_v2_selected.json"
#: Phase 20B: ramp junctions + level-access branches of the selected candidate
LEVEL_ACCESSES_ARTIFACT = "level_accesses.json"
LEVELS_ARTIFACT = "levels.json"
#: Phase 20C.2B: shaft axes, stations and station drives (rule 182)
SHAFTS_ARTIFACT = "shafts.json"
#: Phase 20C.2B: capability semantics over MineNetwork ids (rule 185) —
#: owns NO geometry, so it is not a geometryRef owner
CAPABILITY_GRAPH_ARTIFACT = "capability_graph.json"
RAMP_SOURCE_FILE = "ramp_source.json"
#: Phase 06 ramp tunnel sweep: typed report + GLB (one artifact, two files)
TUNNEL_MESH_ARTIFACT = "tunnel_mesh.json"
TUNNEL_MESH_GLB = "tunnel_mesh.glb"
#: Phase 20B closeout v3 §4 development sweep: typed report + GLB
DEVELOPMENT_MESH_ARTIFACT = "development_mesh.json"
DEVELOPMENT_MESH_GLB = "development_mesh.glb"
NETWORK_ARTIFACT = "network.json"
STOPES_ARTIFACT = "stopes.json"
TIMELINE_ARTIFACT = "timeline.json"
COMMUNICATION_ARTIFACT = "communication.json"
SENSORS_ARTIFACT = "sensors.json"

#: the explicit, persisted active-source choice of the Effective Ramp
#: (rule 150); ``services.effective_ramp`` re-exports it unchanged
RampSource = Literal["LEGACY", "LAYOUT_V2"]

#: every artifact that may own RAMP geometry (Phase 05 legacy smoothed
#: decline, Phase 20A layout-v2 selected effective ramp); RAMP owners store
#: their polylines under ``segments[].effectiveCenterline``
RAMP_OWNING_ARTIFACTS: tuple[str, ...] = (LEGACY_RAMP_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT)
