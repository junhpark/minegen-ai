"""Phase 19 — WARPED_VEIN: deterministic synthetic irregular implicit orebody.

Architecture (rules 133–139)::

    resolved WarpedVeinConfig (persisted, shapeModelVersion = 1)
            ↓
    smooth low-order morphology fields on the strike/dip frame
            ↓
    authoritative implicit function φ(u, v, w)        contains := φ <= 0
            │
            ├── conservative analytic bounding box       (cheap, constructor-time)
            ├── deterministic numerical volume           (2-D midpoint quadrature)
            ├── DERIVED approximate signed clearance     (lazy: lattice + EDT)
            └── DERIVED render mesh                      (lazy: marching cubes)

The implicit function is the ONLY membership authority. The mesh and the
clearance field are derivatives and never define membership (rule 133); the
clearance is explicitly approximate and is never called an SDF (rule 134).
This is a synthetic geological-morphology model — not a measured orebody,
not resource estimation, not kriging, not an imported block model.

Shape model 1 (all in the local frame ``u`` along strike, ``v`` down dip,
``w`` normal; nominal length L, down-dip height H, thickness T;
``s = u/(L/2)``, ``t = v/(H/2)``):

    g_X(s, t)   = Σ wᵢ cos(π kuᵢ s/2 + φuᵢ) cos(π kvᵢ t/2 + φvᵢ) / Σ|wᵢ|     ∈ [−1, 1]

    u_c(t)      = D · g_dev(0, t)                          lateral centre shift
    a±(t)       = (L/2) (1 + I · g_out(±1, t))             strike half-extents
    b±(s)       = (H/2) (1 + I · g_out(s, ±1))             down-dip half-extents
    ξ           = (u − u_c) / a_sign(u − u_c)(t),   η = v / b_sign(v)(s)
    P           = (ξ⁴ + η⁴)^{1/4}                          planform coordinate
    w_mid(s, t) = A · g_warp(s, t)                         warped mid-surface
    m(s, t)     = 1 + V · g_th(s, t)     (≥ pinch floor by construction)
    k           = 2 / edge_taper

    φ(u, v, w)  = ((w − w_mid) / (T/2 · m))² + P^k − 1

so the body is the single-valued vein  |w − w_mid| < (T/2)·m·sqrt(1 − P^k)
over the smooth asymmetric planform P < 1, with tapered terminations
(thickness → 0 at P = 1), pinch-and-swell through m, a warped mid-surface,
a laterally deviating centre and one connected principal solid (the
planform is verified connected at realization).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import ndimage

from minegen.core.coordinates import strike_dip_frame
from minegen.core.enums import DistanceContract, OrebodyType
from minegen.core.models import HarmonicMode, OrebodyConfig, WarpedVeinConfig
from minegen.world.orebody import ImplicitOrebody

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]
IntArray = npt.NDArray[np.int32]

SHAPE_MODEL_VERSION = 1
#: 2-D midpoint quadrature step of the deterministic volume (m)
VOLUME_QUADRATURE_SPACING = 1.0
#: documented relative tolerance of the volume estimate at that spacing
VOLUME_RELATIVE_TOLERANCE = 5e-3
#: derived geometry lattice: cells padded around the local bounding box so
#: the zero level set is closed inside the lattice
LATTICE_PADDING_CELLS = 2
#: hard cap on derived-geometry lattice cells (rule: explicit failure, never
#: silent coarsening that changes the shape)
MAX_GEOMETRY_CELLS = 6_000_000
#: planform coordinate below which a location counts as "interior" for the
#: thickness-floor diagnostics (the taper only acts near P → 1)
INTERIOR_PLANFORM_LIMIT = 0.8
#: 2-D diagnostics lattice spacing (m) used by the realizer's cheap checks
DIAGNOSTIC_SPACING = 4.0


class WarpedVeinGeometryBudgetError(ValueError):
    """The configured body cannot be resolved within the supported derived
    geometry budget. Explicit failure — the shape is never coarsened."""


# --------------------------------------------------------------------------- #
# Morphology (shape model 1)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Modes:
    ku: FloatArray
    kv: FloatArray
    phase_u: FloatArray
    phase_v: FloatArray
    weight: FloatArray
    norm: float

    @classmethod
    def from_config(cls, modes: list[HarmonicMode]) -> _Modes:
        w = np.array([m.weight for m in modes], dtype=np.float64)
        return cls(
            ku=np.array([m.ku for m in modes], dtype=np.float64),
            kv=np.array([m.kv for m in modes], dtype=np.float64),
            phase_u=np.array([m.phase_u for m in modes], dtype=np.float64),
            phase_v=np.array([m.phase_v for m in modes], dtype=np.float64),
            weight=w,
            norm=float(np.sum(np.abs(w))),
        )

    def field(self, s: FloatArray, t: FloatArray) -> FloatArray:
        """Weight-normalized mode sum on broadcastable ``s``, ``t`` → [−1, 1]."""
        s_ = np.asarray(s, dtype=np.float64)[..., None]
        t_ = np.asarray(t, dtype=np.float64)[..., None]
        terms = (
            self.weight
            * np.cos(0.5 * math.pi * self.ku * s_ + self.phase_u)
            * np.cos(0.5 * math.pi * self.kv * t_ + self.phase_v)
        )
        return np.asarray(np.sum(terms, axis=-1) / self.norm)


class WarpedVeinMorphology:
    """Pure, vectorized shape-model-1 mathematics in the LOCAL frame. No
    randomness, no lattice, no state beyond the resolved configuration."""

    def __init__(self, config: OrebodyConfig) -> None:
        if config.orebody_type is not OrebodyType.WARPED_VEIN or config.warped_vein is None:
            raise ValueError("WarpedVeinMorphology requires a WARPED_VEIN config with warpedVein")
        vein: WarpedVeinConfig = config.warped_vein
        if vein.shape_model_version != SHAPE_MODEL_VERSION:
            raise ValueError(
                f"unsupported warped-vein shapeModelVersion {vein.shape_model_version}"
            )
        self.vein = vein
        self.half_length = config.length / 2.0
        self.half_height = config.height / 2.0
        self.half_thickness_nominal = config.thickness / 2.0
        self.amplitude = vein.warp_amplitude
        self.deviation = vein.centerline_deviation
        self.irregularity = vein.outline_irregularity
        self.variability = vein.thickness_variability
        self.taper_exponent = 2.0 / vein.edge_taper
        self._warp = _Modes.from_config(vein.warp_modes)
        self._dev = _Modes.from_config(vein.deviation_modes)
        self._out = _Modes.from_config(vein.outline_modes)
        self._th = _Modes.from_config(vein.thickness_modes)

    # -- component fields (all on normalized s, t) -------------------------- #

    def centerline_u(self, t: FloatArray) -> FloatArray:
        zeros = np.zeros_like(np.asarray(t, dtype=np.float64))
        return np.asarray(self.deviation * self._dev.field(zeros, t))

    def half_extents_u(self, t: FloatArray) -> tuple[FloatArray, FloatArray]:
        """(a₋, a₊) strike half-extents at down-dip coordinate ``t``."""
        t_ = np.asarray(t, dtype=np.float64)
        plus = self.half_length * (1.0 + self.irregularity * self._out.field(np.ones_like(t_), t_))
        minus = self.half_length * (
            1.0 + self.irregularity * self._out.field(-np.ones_like(t_), t_)
        )
        return np.asarray(minus), np.asarray(plus)

    def half_extents_v(self, s: FloatArray) -> tuple[FloatArray, FloatArray]:
        """(b₋, b₊) down-dip half-extents at strike coordinate ``s``."""
        s_ = np.asarray(s, dtype=np.float64)
        plus = self.half_height * (1.0 + self.irregularity * self._out.field(s_, np.ones_like(s_)))
        minus = self.half_height * (
            1.0 + self.irregularity * self._out.field(s_, -np.ones_like(s_))
        )
        return np.asarray(minus), np.asarray(plus)

    def mid_surface(self, s: FloatArray, t: FloatArray) -> FloatArray:
        return np.asarray(self.amplitude * self._warp.field(s, t))

    def thickness_multiplier(self, s: FloatArray, t: FloatArray) -> FloatArray:
        return np.asarray(1.0 + self.variability * self._th.field(s, t))

    def planform(self, u: FloatArray, v: FloatArray) -> FloatArray:
        """P(u, v): < 1 inside the outline, = 1 on it, > 1 outside."""
        u_ = np.asarray(u, dtype=np.float64)
        v_ = np.asarray(v, dtype=np.float64)
        s = u_ / self.half_length
        t = v_ / self.half_height
        du = u_ - self.centerline_u(t)
        a_minus, a_plus = self.half_extents_u(t)
        b_minus, b_plus = self.half_extents_v(s)
        xi = du / np.where(du >= 0.0, a_plus, a_minus)
        eta = v_ / np.where(v_ >= 0.0, b_plus, b_minus)
        return np.asarray((xi**4 + eta**4) ** 0.25)

    def plane_terms(
        self, u: FloatArray, v: FloatArray
    ) -> tuple[FloatArray, FloatArray, FloatArray]:
        """``(w_mid, h_scale, P^k)`` on broadcastable ``u``, ``v`` — everything
        φ needs that does not depend on ``w``."""
        u_ = np.asarray(u, dtype=np.float64)
        v_ = np.asarray(v, dtype=np.float64)
        s = u_ / self.half_length
        t = v_ / self.half_height
        w_mid = self.mid_surface(s, t)
        h_scale = self.half_thickness_nominal * self.thickness_multiplier(s, t)
        pk = self.planform(u_, v_) ** self.taper_exponent
        return w_mid, np.asarray(h_scale), np.asarray(pk)

    def half_thickness(self, u: FloatArray, v: FloatArray) -> FloatArray:
        """Actual local half-thickness (m); 0 outside the planform."""
        _, h_scale, pk = self.plane_terms(u, v)
        return np.asarray(h_scale * np.sqrt(np.clip(1.0 - pk, 0.0, None)))

    def level_local(self, local: FloatArray) -> FloatArray:
        """φ for local points of shape ``(..., 3)``."""
        p = np.asarray(local, dtype=np.float64)
        w_mid, h_scale, pk = self.plane_terms(p[..., 0], p[..., 1])
        return np.asarray(((p[..., 2] - w_mid) / h_scale) ** 2 + pk - 1.0)

    # -- conservative envelope ---------------------------------------------- #

    def local_bounds(self) -> tuple[FloatArray, FloatArray]:
        """Analytic envelope of the solid in the local frame: every inside
        point has |ξ| < 1, |η| < 1 and |w − w_mid| < h_scale, and each of
        those factors is bounded by the configured amplitudes."""
        u_half = self.deviation + self.half_length * (1.0 + self.irregularity)
        v_half = self.half_height * (1.0 + self.irregularity)
        w_half = self.amplitude + self.half_thickness_nominal * (1.0 + self.variability)
        lo = np.array([-u_half, -v_half, -w_half])
        return lo, -lo

    # -- deterministic volume ----------------------------------------------- #

    def volume(self, spacing: float = VOLUME_QUADRATURE_SPACING) -> float:
        """∫∫ 2·h(u, v) du dv by a deterministic 2-D midpoint quadrature over
        the local envelope. The w-extent at (u, v) is exactly 2·h by the
        model definition, so this integrates the authoritative morphology —
        no Monte Carlo, no lattice cells, no grade or field involvement."""
        lo, hi = self.local_bounds()
        u = _midpoints(float(lo[0]), float(hi[0]), spacing)
        v = _midpoints(float(lo[1]), float(hi[1]), spacing)
        du = (hi[0] - lo[0]) / len(u)
        dv = (hi[1] - lo[1]) / len(v)
        h = self.half_thickness(u[:, None], v[None, :])
        return float(2.0 * np.sum(h) * du * dv)

    # -- cheap 2-D diagnostics (realizer validation, reports) --------------- #

    def diagnostics(self, spacing: float = DIAGNOSTIC_SPACING) -> dict[str, Any]:
        lo, hi = self.local_bounds()
        u = _midpoints(float(lo[0]), float(hi[0]), spacing)
        v = _midpoints(float(lo[1]), float(hi[1]), spacing)
        uu, vv = u[:, None], v[None, :]
        w_mid, h_scale, pk = self.plane_terms(uu, vv)
        p = pk ** (1.0 / self.taper_exponent)
        inside = p < 1.0
        interior = p < INTERIOR_PLANFORM_LIMIT
        _labels, n_components = ndimage.label(inside)
        thickness = 2.0 * h_scale * np.sqrt(np.clip(1.0 - pk, 0.0, None))
        interior_thickness = thickness[interior]
        interior_multiplier = (h_scale / self.half_thickness_nominal)[interior]
        planform_area = float(np.count_nonzero(inside)) * spacing * spacing
        a_minus, a_plus = self.half_extents_u(v / self.half_height)
        b_minus, b_plus = self.half_extents_v(u / self.half_length)
        # asymmetry: how different the two strike (resp. dip) edges are
        u_asym = float(np.max(np.abs(a_plus - a_minus)) / self.half_length)
        v_asym = float(np.max(np.abs(b_plus - b_minus)) / self.half_height)
        return {
            "diagnosticSpacing": spacing,
            "planformConnectedComponents": int(n_components),
            "planformAreaM2": planform_area,
            "interiorSampleCount": int(interior_thickness.size),
            "minInteriorThickness": _f(np.min(interior_thickness))
            if interior_thickness.size
            else None,
            "maxInteriorThickness": _f(np.max(interior_thickness))
            if interior_thickness.size
            else None,
            "minInteriorThicknessMultiplier": _f(np.min(interior_multiplier))
            if interior_multiplier.size
            else None,
            "maxInteriorThicknessMultiplier": _f(np.max(interior_multiplier))
            if interior_multiplier.size
            else None,
            "midSurfaceMin": _f(np.min(w_mid[inside])) if inside.any() else None,
            "midSurfaceMax": _f(np.max(w_mid[inside])) if inside.any() else None,
            "centerlineShiftMin": _f(np.min(self.centerline_u(v / self.half_height))),
            "centerlineShiftMax": _f(np.max(self.centerline_u(v / self.half_height))),
            "strikeEdgeAsymmetry": u_asym,
            "dipEdgeAsymmetry": v_asym,
            "pinchFloorRatio": self.vein.pinch_floor_ratio,
            "guaranteedMultiplierFloor": 1.0 - self.variability,
        }


def _midpoints(lo: float, hi: float, spacing: float) -> FloatArray:
    n = max(1, math.ceil((hi - lo) / spacing))
    step = (hi - lo) / n
    return np.asarray(lo + (np.arange(n) + 0.5) * step, dtype=np.float64)


def _f(x: Any) -> float:
    return float(x)


# --------------------------------------------------------------------------- #
# Derived geometry (lazy): lattice → clearance (EDT) → mesh (marching cubes)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GeometryLattice:
    """Local-frame DERIVED geometry lattice (distinct from the Phase 18
    field-sampling lattice): in-plane spacing from the configuration,
    across-thickness spacing fine enough to resolve the thickness floor."""

    origin: FloatArray  # local coords of node (0, 0, 0)
    spacing: FloatArray  # (su, sv, sw)
    shape: tuple[int, int, int]

    @property
    def cell_count(self) -> int:
        return math.prod(self.shape)

    def axis(self, i: int) -> FloatArray:
        return np.asarray(self.origin[i] + np.arange(self.shape[i]) * self.spacing[i])

    @property
    def max_corner(self) -> FloatArray:
        return np.asarray(self.origin + (np.asarray(self.shape) - 1) * self.spacing)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spacing": self.spacing.tolist(),
            "shape": list(self.shape),
            "cellCount": self.cell_count,
            "originLocal": self.origin.tolist(),
        }


def plan_lattice(morph: WarpedVeinMorphology) -> GeometryLattice:
    """Deterministic lattice from the configuration alone (cheap)."""
    vein = morph.vein
    s_plane = vein.geometry_resolution
    min_thickness = 2.0 * morph.half_thickness_nominal * (1.0 - morph.variability)
    s_normal = max(0.25, min(s_plane / 4.0, min_thickness / 3.0))
    spacing = np.array([s_plane, s_plane, s_normal], dtype=np.float64)
    lo, hi = morph.local_bounds()
    pad = LATTICE_PADDING_CELLS * spacing
    origin = lo - pad
    extent = (hi + pad) - origin
    shape = tuple(math.ceil(e / s) + 1 for e, s in zip(extent, spacing, strict=True))
    lattice = GeometryLattice(origin=origin, spacing=spacing, shape=(shape[0], shape[1], shape[2]))
    if lattice.cell_count > MAX_GEOMETRY_CELLS:
        raise WarpedVeinGeometryBudgetError(
            f"derived geometry lattice needs {lattice.cell_count} cells "
            f"(> {MAX_GEOMETRY_CELLS}); reduce the body size or raise geometryResolution"
        )
    return lattice


class WarpedVeinDerivedGeometry:
    """Everything derived FROM the implicit solid on one local lattice.
    Built lazily once per orebody instance; deterministic for a given
    configuration. Nothing here defines membership."""

    def __init__(self, morph: WarpedVeinMorphology) -> None:
        self.morph = morph
        self.lattice = plan_lattice(morph)

    @cached_property
    def level_values(self) -> npt.NDArray[np.float32]:
        """φ sampled on the lattice, shape ``lattice.shape`` (u, v, w order).
        Broadcast from the 2-D plane terms so no (N, 3) point array is
        materialized. Exact zeros are nudged outside so the level set never
        passes exactly through a node (keeps marching cubes non-degenerate)."""
        lat = self.lattice
        u, v, w = lat.axis(0), lat.axis(1), lat.axis(2)
        w_mid, h_scale, pk = self.morph.plane_terms(u[:, None], v[None, :])
        phi = ((w[None, None, :] - w_mid[..., None]) / h_scale[..., None]) ** 2 + (
            pk[..., None] - 1.0
        )
        phi = np.where(phi == 0.0, 1e-9, phi)
        return np.asarray(phi, dtype=np.float32)

    @cached_property
    def inside(self) -> BoolArray:
        return np.asarray(self.level_values <= 0.0)

    @cached_property
    def clearance_values(self) -> npt.NDArray[np.float32]:
        """Signed Euclidean distance transform of the lattice classification
        (metres): negative inside, positive outside. Approximate by
        construction — it measures distance between lattice cells, not to
        the analytic zero level set; the error is bounded by about one
        cell diagonal (see ``clearance_info``)."""
        sampling = tuple(float(s) for s in self.lattice.spacing)
        inside = self.inside
        d_out = ndimage.distance_transform_edt(~inside, sampling=sampling)
        d_in = ndimage.distance_transform_edt(inside, sampling=sampling)
        return np.asarray(d_out - d_in, dtype=np.float32)

    def clearance_info(self) -> dict[str, Any]:
        sp = self.lattice.spacing
        return {
            "contract": DistanceContract.DERIVED_APPROXIMATE_CLEARANCE.value,
            "exact": False,
            "method": (
                "signed Euclidean distance transform of the lattice-classified "
                "implicit solid, trilinear interpolation; sign forced to agree "
                "with contains()"
            ),
            "latticeSpacing": sp.tolist(),
            "maxAbsErrorEstimateM": float(np.linalg.norm(sp)),
            "usableForHardEngineeringBuffers": False,
        }

    def clearance(self, local: FloatArray) -> FloatArray:
        """Trilinear clearance at local points ``(N, 3)``. Outside the
        lattice box the point is clamped to the box (``q``) and the result is
        ``sqrt(clearance(q)² + ‖p − q‖²)``: ``p − q`` is normal to the box
        faces and every solid point lies on the far side of them, so this
        never exceeds the true clearance (a plain sum would over-estimate it
        by the triangle inequality) while staying exact when the nearest
        solid point lies straight below ``q``."""
        p = np.asarray(local, dtype=np.float64).reshape(-1, 3)
        lat = self.lattice
        frac = (p - lat.origin) / lat.spacing
        upper = np.asarray(lat.shape, dtype=np.float64) - 1.0
        clamped = np.clip(frac, 0.0, upper)
        values = ndimage.map_coordinates(
            self.clearance_values, clamped.T, order=1, mode="nearest"
        ).astype(np.float64)
        outside_box = np.linalg.norm((frac - clamped) * lat.spacing, axis=1)
        return np.asarray(np.hypot(np.maximum(values, 0.0), outside_box) + np.minimum(values, 0.0))

    @cached_property
    def mesh_local(self) -> tuple[FloatArray, IntArray]:
        """Zero isosurface of φ on the lattice (marching cubes, scikit-image
        Lewiner) in LOCAL coordinates; outward orientation (skimage's "descent"
        convention yields outward normals for φ < 0 inside — verified by the
        signed-volume test). Vertices are welded so the surface is edge-manifold."""
        from skimage import measure  # heavy import kept lazy

        lat = self.lattice
        verts, faces, _normals, _values = measure.marching_cubes(  # type: ignore[no-untyped-call]
            self.level_values,
            level=0.0,
            spacing=tuple(float(s) for s in lat.spacing),
            gradient_direction="descent",
            allow_degenerate=False,
        )
        verts = np.asarray(verts, dtype=np.float64) + lat.origin
        faces = np.asarray(faces, dtype=np.int64)
        return weld_mesh(verts, faces)


def weld_mesh(verts: FloatArray, faces: npt.NDArray[np.int64]) -> tuple[FloatArray, IntArray]:
    """Merge coincident vertices (exact float equality — marching cubes
    emits identical coordinates for shared edge crossings) and drop
    triangles that became degenerate. Deterministic: first-occurrence
    ordering."""
    _, first, inverse = np.unique(verts, axis=0, return_index=True, return_inverse=True)
    order = np.argsort(first)
    remap = np.empty_like(order)
    remap[order] = np.arange(order.size)
    new_index = remap[inverse.reshape(-1)]
    new_verts = verts[first[order]]
    f = new_index[faces]
    keep = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
    return np.asarray(new_verts, dtype=np.float64), np.asarray(f[keep], dtype=np.int32)


# --------------------------------------------------------------------------- #
# Locally refined clearance window (Phase 20B.1 C-2)
# --------------------------------------------------------------------------- #


class RefinedClearanceWindow:
    """One LOCAL clearance lattice at ``base spacing / factor`` over a window
    of the derived-geometry box, built for one stage-4 layout candidate.

    The certified query is a LOWER bound of the true signed clearance:

        certified(p) = min(EDT_window(p), d_face(p)) − 1.5 × ‖refined spacing‖

    * ``EDT_window`` is the signed Euclidean distance transform of the
      φ-classified REFINED window cells (same construction and therefore the
      same 1.5 × ‖spacing‖ derivation as the coarse field — boundary
      discretization ≤ 1 diagonal, trilinear interpolation of a 1-Lipschitz
      field ≤ 0.5 diagonal);
    * ``d_face`` clamps against solid OUTSIDE the window: any such solid lies
      beyond a window face, so the distance to the nearest CLAMPED face is a
      valid lower bound of the distance to it. Faces at or beyond the
      analytic local bounds of the solid are never clamped (no solid exists
      beyond them). ``min`` keeps whichever certificate is weaker, so the
      result never exceeds the true clearance; for a point inside the solid
      the EDT term is negative and wins.

    Queries outside the window return NaN — the caller falls back to the
    coarse certification there (``RefinedConservativeClearance``)."""

    def __init__(
        self,
        morph: WarpedVeinMorphology,
        base: GeometryLattice,
        lo_local: FloatArray,
        hi_local: FloatArray,
        factor: int,
    ) -> None:
        self.morph = morph
        spacing = base.spacing / float(factor)
        base_max = base.max_corner
        lo = np.maximum(np.asarray(lo_local, dtype=np.float64), base.origin)
        hi = np.minimum(np.asarray(hi_local, dtype=np.float64), base_max)
        shape = tuple(math.ceil((h - g) / s) + 2 for g, h, s in zip(lo, hi, spacing, strict=True))
        self.lattice = GeometryLattice(
            origin=lo, spacing=np.asarray(spacing), shape=(shape[0], shape[1], shape[2])
        )
        self.error_bound = 1.5 * float(np.linalg.norm(spacing))
        # faces beyond which no solid exists (analytic local bounds)
        solid_lo, solid_hi = morph.local_bounds()
        self._clamp_lo = self.lattice.origin > solid_lo + 1e-9
        self._clamp_hi = self.lattice.max_corner < solid_hi - 1e-9

    @property
    def cell_count(self) -> int:
        return self.lattice.cell_count

    @cached_property
    def _signed_edt(self) -> npt.NDArray[np.float32]:
        lat = self.lattice
        u, v, w = lat.axis(0), lat.axis(1), lat.axis(2)
        w_mid, h_scale, pk = self.morph.plane_terms(u[:, None], v[None, :])
        phi = ((w[None, None, :] - w_mid[..., None]) / h_scale[..., None]) ** 2 + (
            pk[..., None] - 1.0
        )
        inside = phi <= 0.0
        sampling = tuple(float(s) for s in lat.spacing)
        d_out = ndimage.distance_transform_edt(~inside, sampling=sampling)
        d_in = ndimage.distance_transform_edt(inside, sampling=sampling)
        return np.asarray(d_out - d_in, dtype=np.float32)

    def certified_clearance(self, local: FloatArray) -> FloatArray:
        """Certified lower-bound clearance at LOCAL points; NaN outside the
        window (the caller keeps its coarse certification there)."""
        p = np.asarray(local, dtype=np.float64).reshape(-1, 3)
        lat = self.lattice
        upper = lat.origin + (np.asarray(lat.shape, dtype=np.float64) - 1.0) * lat.spacing
        inside_window = np.all((p >= lat.origin) & (p <= upper), axis=1)
        out = np.full(p.shape[0], np.nan)
        if not np.any(inside_window):
            return out
        q = p[inside_window]
        frac = (q - lat.origin) / lat.spacing
        edt = ndimage.map_coordinates(self._signed_edt, frac.T, order=1, mode="nearest").astype(
            np.float64
        )
        d_face = np.full(q.shape[0], np.inf)
        for axis in range(3):
            if self._clamp_lo[axis]:
                d_face = np.minimum(d_face, q[:, axis] - lat.origin[axis])
            if self._clamp_hi[axis]:
                d_face = np.minimum(d_face, upper[axis] - q[:, axis])
        out[inside_window] = np.minimum(edt, d_face) - self.error_bound
        return out

    def info(self) -> dict[str, Any]:
        return {
            "latticeSpacing": self.lattice.spacing.tolist(),
            "shape": list(self.lattice.shape),
            "cellCount": self.cell_count,
            "errorBound": self.error_bound,
        }


# --------------------------------------------------------------------------- #
# Orebody
# --------------------------------------------------------------------------- #


class WarpedVeinOrebody(ImplicitOrebody):
    """Authoritative implicit warped-vein solid. Construction is cheap (frame
    + morphology coefficients + lattice plan); clearance and mesh are
    derived lazily on first use (rule 138) and cached on the instance."""

    config: OrebodyConfig

    def __init__(self, config: OrebodyConfig) -> None:
        if config.orebody_type is not OrebodyType.WARPED_VEIN:
            raise ValueError(f"WarpedVeinOrebody requires WARPED_VEIN, got {config.orebody_type}")
        self.config = config
        self.frame = strike_dip_frame(
            np.array(config.center.as_tuple()), config.strike_deg, config.dip_deg
        )
        self.morphology = WarpedVeinMorphology(config)
        # validates the geometry budget up front (typed failure, rule 14 §)
        self.lattice = plan_lattice(self.morphology)

    @cached_property
    def derived(self) -> WarpedVeinDerivedGeometry:
        return WarpedVeinDerivedGeometry(self.morphology)

    # -- authoritative solid -------------------------------------------------- #

    def level(self, points: FloatArray) -> FloatArray:
        return self.morphology.level_local(self.to_local(np.asarray(points, dtype=np.float64)))

    def contains(self, points: FloatArray) -> BoolArray:
        return np.asarray(self.level(points) <= 0.0)

    def bounding_box(self) -> tuple[FloatArray, FloatArray]:
        _lo, hi = self.morphology.local_bounds()
        signs = np.array(
            [[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)],
            dtype=np.float64,
        )
        corners = self.to_world(signs * hi)
        return corners.min(axis=0), corners.max(axis=0)

    def volume(self) -> float:
        return self.morphology.volume()

    # -- derived geometry ----------------------------------------------------- #

    def approximate_clearance(self, points: FloatArray) -> FloatArray:
        pts = np.asarray(points, dtype=np.float64)
        local = self.to_local(pts).reshape(-1, 3)
        d = self.derived.clearance(local)
        inside = self.morphology.level_local(local) <= 0.0
        # membership wins near the boundary: a disagreeing sample lies within
        # a cell of the surface, so its magnitude is capped at half a cell
        cap = 0.5 * float(np.min(self.lattice.spacing))
        wrong = (d > 0.0) & inside | (d <= 0.0) & ~inside
        fixed = np.where(inside, -np.minimum(np.abs(d), cap), np.minimum(np.abs(d), cap))
        d = np.where(wrong, fixed, d)
        return np.asarray(d.reshape(pts.shape[:-1]))

    def clearance_info(self) -> dict[str, Any]:
        return self.derived.clearance_info()

    def refined_clearance_window(
        self, world_points: FloatArray, padding: float, factor: int, max_cells: int
    ) -> RefinedClearanceWindow | None:
        """Phase 20B.1 C-2: one LOCAL clearance window at ``base spacing /
        factor`` covering ``world_points`` plus ``padding`` (m, every local
        axis), clipped to the derived-geometry box. ``None`` when the window
        would exceed ``max_cells`` — the caller keeps the coarse
        certification and reports the skip; never a failure."""
        local = self.to_local(np.asarray(world_points, dtype=np.float64)).reshape(-1, 3)
        lo = local.min(axis=0) - padding
        hi = local.max(axis=0) + padding
        window = RefinedClearanceWindow(self.morphology, self.derived.lattice, lo, hi, factor)
        if window.cell_count > max_cells:
            return None
        return window

    def mesh(self) -> tuple[FloatArray, IntArray]:
        """Derived render mesh in world coordinates, vertices rounded to
        1 mm (a transport-size measure far below the lattice resolution)."""
        verts_local, faces = self.derived.mesh_local
        # rounding can make two very close vertices coincide: weld again so
        # the output stays edge-manifold with no zero-area triangle
        return weld_mesh(np.round(self.to_world(verts_local), 3), faces.astype(np.int64))

    def to_dict(self) -> dict[str, Any]:
        lo, hi = self.bounding_box()
        vein = self.morphology.vein
        return {
            "type": self.config.orebody_type.value,
            "center": self.center.tolist(),
            "u": self.u.tolist(),
            "v": self.v.tolist(),
            "w": self.w.tolist(),
            "nominalHalfExtents": [
                self.morphology.half_length,
                self.morphology.half_height,
                self.morphology.half_thickness_nominal,
            ],
            "shapeModelVersion": vein.shape_model_version,
            "volumeM3": self.volume(),
            "volumeMethod": {
                "method": "deterministic 2-D midpoint quadrature of the implicit morphology",
                "spacingM": VOLUME_QUADRATURE_SPACING,
                "relativeTolerance": VOLUME_RELATIVE_TOLERANCE,
                "semantics": "geometric synthetic-solid volume only",
            },
            "distanceContract": self.distance_contract.value,
            "clearance": self.derived_clearance_metadata(),
            "geometryLattice": self.lattice.to_dict(),
            "morphology": {
                "warpAmplitude": vein.warp_amplitude,
                "centerlineDeviation": vein.centerline_deviation,
                "outlineIrregularity": vein.outline_irregularity,
                "thicknessVariability": vein.thickness_variability,
                "pinchFloorRatio": vein.pinch_floor_ratio,
                "edgeTaper": vein.edge_taper,
                "geometryResolution": vein.geometry_resolution,
                **self.morphology.diagnostics(),
            },
            "bboxMin": lo.tolist(),
            "bboxMax": hi.tolist(),
            "bboxSemantics": "conservative analytic envelope of the implicit solid",
        }

    def derived_clearance_metadata(self) -> dict[str, Any]:
        """Clearance metadata WITHOUT building the clearance field (the
        lattice plan alone determines it)."""
        sp = self.lattice.spacing
        return {
            "contract": DistanceContract.DERIVED_APPROXIMATE_CLEARANCE.value,
            "exact": False,
            "latticeSpacing": sp.tolist(),
            "maxAbsErrorEstimateM": float(np.linalg.norm(sp)),
            "usableForHardEngineeringBuffers": False,
        }
