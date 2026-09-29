"""Engine import packages — Unity / Unreal (Phase 23B, directive §42–§50).

One common builder (``package.py``) normalizes every MineExchange GLB to
ONE consumer convention (glTF Y-up, metres, right-handed — exactly what
both engines' glTF importers expect), emits the mine semantics beside the
assets (entities, network, capability, timeline as documents — identity is
never trusted to importer-preserved ``extras``) and target-specific
manifest / README / import settings. No gameplay, physics, ventilation,
AI, NavMesh, runtime synchronization or result overlay; no ``.unitypackage``
/ ``.uasset`` — those are not interchange formats.
"""

from minegen.adapters.engine.package import (
    UNITY_ADAPTER_NAME,
    UNREAL_ADAPTER_NAME,
    build_unity_package,
    build_unreal_package,
)

__all__ = [
    "UNITY_ADAPTER_NAME",
    "UNREAL_ADAPTER_NAME",
    "build_unity_package",
    "build_unreal_package",
]
