"""Declarative artifact dependency registry (AC-01E).

ONE declaration of the derived-artifact graph — which file(s) every artifact
owns, which inputs it is fingerprinted over (ORDERED), and which ramp source
a ramp-OWNING artifact belongs to — from which two projections are derived
by one algorithm:

* ``fingerprint_files`` / ``fingerprint_paths``: the ordered input list a
  service captures before a build and re-checks under the store lock
  (rule 60). The ORDER is persisted: nine builders hash
  ``json.dumps(fingerprint.entries, sort_keys=True)`` into ``sourceRevision``
  (and the selection ``revision``), and ``sort_keys`` never reorders the
  entry list. Every list below is therefore declared in TODAY's per-artifact
  order (timeline puts the ramp bundle in the middle, network omits
  ``arrays.npz``, …) — never a topological or alphabetical order.
* ``invalidation_edges`` / ``invalidated_by``: the delete cascade a writer
  runs immediately after persisting an artifact, as the transitive closure
  over the dependency edges.

Two modelling rules make the fingerprint projection and the invalidation
projection two views of the SAME declaration instead of two lists:

1. ``INPUTS_OF(Y)`` contributes Y's expanded input list to the FINGERPRINT of
   the consumer but ONLY the edge ``Y → consumer`` to invalidation — never
   Y's own inputs. This is what keeps ``targets.json`` / ``decline.json`` in
   the tunnel fingerprint (a running mesh job still fails
   ``JOB_INPUTS_CHANGED`` on a concurrent legacy regeneration) WITHOUT a
   delete edge that would fire under LAYOUT_V2 (a legacy regeneration while
   the layout-v2 ramp is active never touches the LAYOUT_V2-derived chain,
   rules 151 / 169).
2. The ramp-source condition sits on the ramp-OWNING artifact, never on
   individual edges: the out-edges of ``decline_smoothed.json`` are traversed
   only while LEGACY is the active source, those of
   ``layout_v2_selected.json`` / ``level_accesses.json`` only while
   LAYOUT_V2 is. ``ramp_source.json`` is an unconditional root of the ramp
   downstream (a source switch invalidates the whole chain, rule 151) and is
   never itself invalidated (rule 162 — a switch keeps the selection).

What the registry does NOT do: scenario mutation / world regeneration stay
``WorldService.invalidate`` → ``ScenarioStore.clear_derived`` (a directory
walk that also removes ``derived/world.json`` and unknown files, rules
40 / 46) — the registry is never used for that; ``derived/world.json`` is
unregistered. ``targets.json``, ``level_accesses.json`` and
``ramp_source.json`` carry inputs for EDGES only: no fingerprint capture
exists for them today and none is added. The registry expresses the source
gate SYMBOLICALLY (``ArtifactSpec.ramp_source``); the service evaluates
``read_ramp_source`` inside its own store lock and passes the value in.

This module is a LEAF: it imports the standard library and
``minegen.core.artifacts`` only — nothing from ``services/`` or ``layout/``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from minegen.core.artifacts import (
    ARRAYS_FILE,
    CAPABILITY_GRAPH_ARTIFACT,
    COMMUNICATION_ARTIFACT,
    DECLINE_ARTIFACT,
    DEVELOPMENT_MESH_ARTIFACT,
    DEVELOPMENT_MESH_GLB,
    LAYOUT_V2_ARTIFACT,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEGACY_RAMP_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    LEVELS_ARTIFACT,
    NETWORK_ARTIFACT,
    RAMP_SOURCE_FILE,
    SCENARIO_FILE,
    SENSORS_ARTIFACT,
    SHAFTS_ARTIFACT,
    STOPES_ARTIFACT,
    TARGETS_ARTIFACT,
    TIMELINE_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
    TUNNEL_MESH_GLB,
    RampSource,
)

__all__ = [
    "ARTIFACTS",
    "EFFECTIVE_RAMP_GROUP",
    "GROUPS",
    "ArtifactFile",
    "ArtifactSpec",
    "Dependency",
    "DependencyKind",
    "Location",
    "derived_artifacts",
    "fingerprint_files",
    "fingerprint_paths",
    "invalidated_by",
    "invalidation_edges",
    "spec",
]

#: where a file lives: ``scenario.json`` / ``arrays.npz`` in the scenario
#: directory, every derived artifact under ``derived/``. Paths must stay
#: rooted: ``InputFingerprint`` keys on ``path.name`` + stat, so a mis-rooted
#: path silently degrades to ``(name, False, 0, 0)`` forever.
Location = Literal["SCENARIO", "DERIVED"]
DependencyKind = Literal["FILE", "INPUTS_OF", "GROUP"]

LOCATION_SCENARIO: Final[Location] = "SCENARIO"
LOCATION_DERIVED: Final[Location] = "DERIVED"
KIND_FILE: Final[DependencyKind] = "FILE"
KIND_INPUTS_OF: Final[DependencyKind] = "INPUTS_OF"
KIND_GROUP: Final[DependencyKind] = "GROUP"

#: the Effective Ramp input bundle (rule 150): every file that decides the
#: active ramp, in the order every downstream fingerprint expands it
EFFECTIVE_RAMP_GROUP: Final = "EFFECTIVE_RAMP"


@dataclass(frozen=True)
class ArtifactFile:
    name: str
    location: Location


@dataclass(frozen=True)
class Dependency:
    """One ordered input of an artifact.

    ``FILE(Y)``       the fingerprint file of artifact Y; edge Y → consumer.
    ``INPUTS_OF(Y)``  Y's expanded fingerprint list (recursive) in the
                      fingerprint; edge Y → consumer ONLY (never Y's inputs).
    ``GROUP(g)``      the members of group g, each expanded like ``FILE``.
    """

    kind: DependencyKind
    target: str


@dataclass(frozen=True)
class ArtifactSpec:
    """One derived artifact: the registry key is its fingerprint file name."""

    name: str
    #: EVERY file the artifact owns (fingerprint file first, a GLB second) —
    #: the delete unit of a cascade
    files: tuple[ArtifactFile, ...]
    #: ORDERED inputs — the order reaches persisted bytes
    inputs: tuple[Dependency, ...]
    #: set ONLY on ramp-owning artifacts: their downstream edges are
    #: traversed only while this is the ACTIVE ramp source
    ramp_source: RampSource | None = None

    @property
    def fingerprint_file(self) -> ArtifactFile:
        return self.files[0]


def _file(name: str) -> Dependency:
    return Dependency(KIND_FILE, name)


def _inputs_of(name: str) -> Dependency:
    return Dependency(KIND_INPUTS_OF, name)


def _group(name: str) -> Dependency:
    return Dependency(KIND_GROUP, name)


def _scenario(name: str) -> ArtifactFile:
    return ArtifactFile(name, LOCATION_SCENARIO)


def _derived(name: str) -> ArtifactFile:
    return ArtifactFile(name, LOCATION_DERIVED)


GROUPS: Final[Mapping[str, tuple[Dependency, ...]]] = {
    EFFECTIVE_RAMP_GROUP: (
        _file(LEGACY_RAMP_ARTIFACT),
        _file(LAYOUT_V2_SELECTED_ARTIFACT),
        _file(LEVEL_ACCESSES_ARTIFACT),
        _file(RAMP_SOURCE_FILE),
    ),
}

#: declaration order == deterministic cascade unlink order
ARTIFACTS: Final[tuple[ArtifactSpec, ...]] = (
    # -- roots (scenario directory): invalidated by clear_derived only ------ #
    ArtifactSpec(SCENARIO_FILE, (_scenario(SCENARIO_FILE),), ()),
    ArtifactSpec(ARRAYS_FILE, (_scenario(ARRAYS_FILE),), (_file(SCENARIO_FILE),)),
    # -- legacy Phase 03–05 chain (Hybrid-A*) -------------------------------- #
    # dependency only: no fingerprint capture exists for the targets today
    ArtifactSpec(
        TARGETS_ARTIFACT,
        (_derived(TARGETS_ARTIFACT),),
        (_file(SCENARIO_FILE), _file(ARRAYS_FILE)),
    ),
    ArtifactSpec(
        DECLINE_ARTIFACT,
        (_derived(DECLINE_ARTIFACT),),
        (_file(SCENARIO_FILE), _file(ARRAYS_FILE), _file(TARGETS_ARTIFACT)),
    ),
    ArtifactSpec(
        LEGACY_RAMP_ARTIFACT,
        (_derived(LEGACY_RAMP_ARTIFACT),),
        (_inputs_of(DECLINE_ARTIFACT), _file(DECLINE_ARTIFACT)),
        ramp_source="LEGACY",
    ),
    # -- layout-v2 catalogue + selection (Phase 20A/B) ---------------------- #
    ArtifactSpec(
        LAYOUT_V2_ARTIFACT,
        (_derived(LAYOUT_V2_ARTIFACT),),
        (_file(SCENARIO_FILE), _file(ARRAYS_FILE)),
    ),
    ArtifactSpec(
        LAYOUT_V2_SELECTED_ARTIFACT,
        (_derived(LAYOUT_V2_SELECTED_ARTIFACT),),
        (_inputs_of(LAYOUT_V2_ARTIFACT), _file(LAYOUT_V2_ARTIFACT)),
        ramp_source="LAYOUT_V2",
    ),
    # co-written with the selection under the selection's capture (rule 157);
    # no capture of its own — inputs declared for the edges only
    ArtifactSpec(
        LEVEL_ACCESSES_ARTIFACT,
        (_derived(LEVEL_ACCESSES_ARTIFACT),),
        (_inputs_of(LAYOUT_V2_ARTIFACT), _file(LAYOUT_V2_ARTIFACT)),
        ramp_source="LAYOUT_V2",
    ),
    # explicit user choice (rule 150): a root of the ramp downstream
    ArtifactSpec(RAMP_SOURCE_FILE, (_derived(RAMP_SOURCE_FILE),), ()),
    # -- everything derived from the Effective Ramp (rule 151 order) -------- #
    ArtifactSpec(
        TUNNEL_MESH_ARTIFACT,
        (_derived(TUNNEL_MESH_ARTIFACT), _derived(TUNNEL_MESH_GLB)),
        (_inputs_of(LEGACY_RAMP_ARTIFACT), _group(EFFECTIVE_RAMP_GROUP)),
    ),
    ArtifactSpec(
        LEVELS_ARTIFACT,
        (_derived(LEVELS_ARTIFACT),),
        (_file(SCENARIO_FILE), _file(ARRAYS_FILE), _group(EFFECTIVE_RAMP_GROUP)),
    ),
    ArtifactSpec(
        DEVELOPMENT_MESH_ARTIFACT,
        (_derived(DEVELOPMENT_MESH_ARTIFACT), _derived(DEVELOPMENT_MESH_GLB)),
        (_inputs_of(LEVELS_ARTIFACT), _file(LEVELS_ARTIFACT)),
    ),
    ArtifactSpec(
        SHAFTS_ARTIFACT,
        (_derived(SHAFTS_ARTIFACT),),
        (_inputs_of(LEVELS_ARTIFACT), _file(LEVELS_ARTIFACT)),
    ),
    ArtifactSpec(
        STOPES_ARTIFACT,
        (_derived(STOPES_ARTIFACT),),
        (_file(SCENARIO_FILE), _file(ARRAYS_FILE), _file(LEVELS_ARTIFACT)),
    ),
    ArtifactSpec(
        TIMELINE_ARTIFACT,
        (_derived(TIMELINE_ARTIFACT),),
        (
            _file(SCENARIO_FILE),
            _file(NETWORK_ARTIFACT),
            _file(STOPES_ARTIFACT),
            _group(EFFECTIVE_RAMP_GROUP),
            _file(LEVELS_ARTIFACT),
            _file(SHAFTS_ARTIFACT),
        ),
    ),
    ArtifactSpec(
        COMMUNICATION_ARTIFACT,
        (_derived(COMMUNICATION_ARTIFACT),),
        (
            _file(SCENARIO_FILE),
            _file(NETWORK_ARTIFACT),
            _group(EFFECTIVE_RAMP_GROUP),
            _file(LEVELS_ARTIFACT),
            _file(SHAFTS_ARTIFACT),
        ),
    ),
    ArtifactSpec(
        SENSORS_ARTIFACT,
        (_derived(SENSORS_ARTIFACT),),
        (
            _file(SCENARIO_FILE),
            _file(NETWORK_ARTIFACT),
            _group(EFFECTIVE_RAMP_GROUP),
            _file(LEVELS_ARTIFACT),
            _file(SHAFTS_ARTIFACT),
        ),
    ),
    ArtifactSpec(
        NETWORK_ARTIFACT,
        (_derived(NETWORK_ARTIFACT),),
        (
            _file(SCENARIO_FILE),
            _group(EFFECTIVE_RAMP_GROUP),
            _file(LEVELS_ARTIFACT),
            _file(SHAFTS_ARTIFACT),
        ),
    ),
    ArtifactSpec(
        CAPABILITY_GRAPH_ARTIFACT,
        (_derived(CAPABILITY_GRAPH_ARTIFACT),),
        (_file(SCENARIO_FILE), _file(NETWORK_ARTIFACT), _file(SHAFTS_ARTIFACT)),
    ),
)

_BY_NAME: Final[Mapping[str, ArtifactSpec]] = {a.name: a for a in ARTIFACTS}
_ORDER: Final[Mapping[str, int]] = {a.name: i for i, a in enumerate(ARTIFACTS)}


def spec(name: str) -> ArtifactSpec:
    """The declaration of the artifact whose fingerprint file is ``name``."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"'{name}' is not a registered artifact") from None


def derived_artifacts() -> tuple[ArtifactSpec, ...]:
    """Every registered artifact that lives under ``derived/`` (declaration
    order)."""
    return tuple(a for a in ARTIFACTS if a.fingerprint_file.location == LOCATION_DERIVED)


def _expand(dep: Dependency) -> tuple[ArtifactFile, ...]:
    if dep.kind == KIND_FILE:
        return (spec(dep.target).fingerprint_file,)
    if dep.kind == KIND_INPUTS_OF:
        return fingerprint_files(dep.target)
    return tuple(f for member in GROUPS[dep.target] for f in _expand(member))


def fingerprint_files(name: str) -> tuple[ArtifactFile, ...]:
    """The ORDERED fingerprint input files of ``name`` (projection 1)."""
    return tuple(f for dep in spec(name).inputs for f in _expand(dep))


def fingerprint_paths(name: str, *, scenario_dir: Path, derived_dir: Path) -> list[Path]:
    """The rooted paths of ``fingerprint_files(name)``: scenario-directory
    files under ``scenario_dir``, everything else under ``derived_dir`` —
    the very paths ``store.scenario_path`` / ``store.arrays_path`` /
    ``derived_dir / name`` produce."""
    return [
        (scenario_dir if f.location == LOCATION_SCENARIO else derived_dir) / f.name
        for f in fingerprint_files(name)
    ]


def _edge_sources(dep: Dependency) -> tuple[str, ...]:
    if dep.kind == KIND_GROUP:
        return tuple(m.target for m in GROUPS[dep.target])
    return (dep.target,)  # FILE and INPUTS_OF alike: the consumed artifact only


def invalidation_edges() -> tuple[tuple[str, str], ...]:
    """Every (upstream, downstream) edge: "regenerating upstream invalidates
    downstream". ``INPUTS_OF`` contributes ONLY the consumed artifact, never
    its inputs (modelling rule 1). Deduplicated, declaration order."""
    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for a in ARTIFACTS:
        for dep in a.inputs:
            for upstream in _edge_sources(dep):
                edge = (upstream, a.name)
                if edge not in seen:
                    seen.add(edge)
                    edges.append(edge)
    return tuple(edges)


def invalidated_by(written: Iterable[str], active_source: RampSource) -> tuple[ArtifactSpec, ...]:
    """The artifacts a writer of ``written`` must delete right after
    persisting them (projection 2): the transitive closure over
    ``invalidation_edges()`` where the out-edges of a node are traversed only
    if it is not a ramp owner or its ``ramp_source`` IS the active source
    (modelling rule 2). The written artifacts themselves are excluded; the
    result is in ARTIFACTS declaration order (deterministic unlink order)."""
    roots = tuple(written)
    for name in roots:
        spec(name)  # unknown names are an error, never an empty closure
    edges = invalidation_edges()
    reached: set[str] = set()
    stack: list[str] = list(roots)
    while stack:
        node = stack.pop()
        gate = spec(node).ramp_source
        if gate is not None and gate != active_source:
            continue  # an inactive ramp owner's downstream edges are dead
        for upstream, downstream in edges:
            if upstream == node and downstream not in reached and downstream not in roots:
                reached.add(downstream)
                stack.append(downstream)
    return tuple(a for a in ARTIFACTS if a.name in reached)
