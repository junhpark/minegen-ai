"""Generic triangle-mesh QA (closed-solid contract) — the ONE implementation
lives in ``minegen.geometry.mesh_qa`` since Phase 21B/C (the production
generators judge their solids with the same code the exporter does); this
module keeps the MineExchange import path."""

from __future__ import annotations

from minegen.geometry.mesh_qa import DEGENERATE_AREA, FloatArray, IntArray, MeshQa, mesh_qa

__all__ = ["DEGENERATE_AREA", "FloatArray", "IntArray", "MeshQa", "mesh_qa"]
