"""AC-01E — the artifact dependency registry against the FROZEN census.

The oracle is the census of the hand-maintained lifecycle code (the
``_*_input_paths`` lists, the inline selection capture and the ``_delete_*``
cascades of ``services/design_service.py`` / ``services/infrastructure_service.py``
at the AC-01E base), transcribed below as literal tables with the file:line
each row came from. The registry derivation must reproduce every ORDERED
input list (order reaches persisted ``sourceRevision`` / selection
``revision`` bytes) and every delete set for every artifact under BOTH ramp
sources. The live public ``*_fingerprint()`` methods are checked against the
same tables, so the registry and the services are both held to the census —
never to each other.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from minegen.core import artifact_registry as registry
from minegen.core import artifacts as core_artifacts
from minegen.core.artifact_registry import (
    ARTIFACTS,
    EFFECTIVE_RAMP_GROUP,
    GROUPS,
    derived_artifacts,
    fingerprint_files,
    fingerprint_paths,
    invalidated_by,
    invalidation_edges,
    spec,
)
from minegen.core.artifacts import RampSource
from minegen.services import effective_ramp
from minegen.services.design_service import DesignService, InputFingerprint
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService

# -- file names (the census abbreviations) ---------------------------------- #
S, W = "scenario.json", "arrays.npz"
T, D, SM = "targets.json", "decline.json", "decline_smoothed.json"
L, LS, LA = "layout_v2.json", "layout_v2_selected.json", "level_accesses.json"
RS = "ramp_source.json"
TM, TM_GLB = "tunnel_mesh.json", "tunnel_mesh.glb"
LV, DM, DM_GLB = "levels.json", "development_mesh.json", "development_mesh.glb"
SH, N, CG = "shafts.json", "network.json", "capability_graph.json"
ST, TL, CM, SN = "stopes.json", "timeline.json", "communication.json", "sensors.json"
SOURCES: tuple[RampSource, ...] = ("LEGACY", "LAYOUT_V2")

#: ``_ramp_input_paths`` design_service.py:497-507 — that order
RAMP: tuple[str, ...] = (SM, LS, LA, RS)

#: FROZEN ordered fingerprint input lists (14 fingerprinted artifacts).
#: Each row: the ``_*_input_paths`` site → the public ``*_fingerprint()`` it feeds.
EXPECTED_INPUTS: dict[str, tuple[str, ...]] = {
    D: (S, W, T),  # `_input_paths` :366-371 → `input_fingerprint` :373-374
    SM: (S, W, T, D),  # `_smoothing_input_paths` :413-414 → `smoothing_fingerprint` :416-417
    L: (S, W),  # `_layout_input_paths` :509-510 → `layout_fingerprint` :512-513
    LS: (S, W, L),  # INLINE `[*_layout_input_paths, layout_path]` :602-604 and :640-642
    LV: (S, W, *RAMP),  # `_levels_input_paths` :829-836 → `levels_fingerprint` :838-839
    ST: (S, W, LV),  # `_stopes_input_paths` :905-910 → `stopes_fingerprint` :912-913
    TL: (S, N, ST, *RAMP, LV, SH),  # `_timeline_input_paths` :982-991 → :993-994
    SH: (S, W, *RAMP, LV),  # `_shafts_input_paths` :1070-1073 (= levels + LV) → :1075-1076
    CG: (S, N, SH),  # `_capability_input_paths` :1135-1142 → `capability_fingerprint` :1144-1145
    N: (S, *RAMP, LV, SH),  # `_network_input_paths` :1205-1214 → `network_fingerprint` :1216-1217
    TM: (S, W, T, D, *RAMP),  # `_tunnel_input_paths` :1281-1282 (= smoothing + RAMP) → :1284-1285
    DM: (S, W, *RAMP, LV),  # `_development_mesh_input_paths` :1369-1370 (= levels + LV) → :1372
    CM: (S, N, *RAMP, LV, SH),  # infra `_communication_input_paths` :41-50 → :52-53
    SN: (S, N, *RAMP, LV, SH),  # infra `sensors_fingerprint` :104-105 REUSES the communication list
}

#: `_delete_ramp_downstream` design_service.py:521-531 — the 12 files, in its
#: unlink order: tunnel (:525 → `_delete_tunnel_artifacts` :1276-1279), levels
#: (:526 → `_delete_levels_artifact` :821-827 → `_delete_development_mesh_artifacts`
#: :1361-1367 + `_delete_shafts_artifact` :1060-1063), stopes (:527 → :900-903),
#: timeline (:528 → :963-966), communication (:529 → :975-980), sensors
#: (:530 → :968-973), network (:531 → `_delete_network_artifact` :1046-1050 →
#: `_delete_capability_graph_artifact` :1065-1068)
RAMP_DOWN: frozenset[str] = frozenset({TM, TM_GLB, LV, DM, DM_GLB, SH, ST, TL, CM, SN, N, CG})
LEVELS_DOWN: frozenset[str] = frozenset({SH, N, CG, ST, TL, CM, SN, DM, DM_GLB})
NOTHING: frozenset[str] = frozenset()

#: FROZEN delete sets: (written artifacts, active source) → file names removed.
#: `_delete_ramp_downstream_if_active` :533-535 fires RAMP_DOWN iff
#: ``read_ramp_source(derived) == source`` — evaluated at write time.
EXPECTED_DELETES: dict[tuple[tuple[str, ...], str], frozenset[str]] = {
    # generate_targets :329-337: unlink decline, unlink smoothed, cascade iff LEGACY
    ((T,), "LEGACY"): frozenset({D, SM}) | RAMP_DOWN,
    ((T,), "LAYOUT_V2"): frozenset({D, SM}),
    # generate_decline :402-405: unlink smoothed, cascade iff LEGACY
    ((D,), "LEGACY"): frozenset({SM}) | RAMP_DOWN,
    ((D,), "LAYOUT_V2"): frozenset({SM}),
    # generate_smoothed :468: cascade iff LEGACY
    ((SM,), "LEGACY"): RAMP_DOWN,
    ((SM,), "LAYOUT_V2"): NOTHING,
    # generate_layout_v2 :559-560: `_delete_layout_selection` :515-519, cascade iff LAYOUT_V2
    ((L,), "LEGACY"): frozenset({LS, LA}),
    ((L,), "LAYOUT_V2"): frozenset({LS, LA}) | RAMP_DOWN,
    # select_layout_candidate :645-648: writes LS + LA together, cascade iff LAYOUT_V2
    ((LS, LA), "LEGACY"): NOTHING,
    ((LS, LA), "LAYOUT_V2"): RAMP_DOWN,
    # no writer writes one of the pair alone; each alone must agree with the pair
    ((LS,), "LEGACY"): NOTHING,
    ((LS,), "LAYOUT_V2"): RAMP_DOWN,
    ((LA,), "LEGACY"): NOTHING,
    ((LA,), "LAYOUT_V2"): RAMP_DOWN,
    # set_ramp_source :791-793: on an actual change, UNCONDITIONAL `_delete_ramp_downstream`
    ((RS,), "LEGACY"): RAMP_DOWN,
    ((RS,), "LAYOUT_V2"): RAMP_DOWN,
    # generate_tunnel :1340-1350: nothing (the FAILED-report GLB unlink is writer logic)
    ((TM,), "LEGACY"): NOTHING,
    ((TM,), "LAYOUT_V2"): NOTHING,
    # generate_levels :879-885: shafts, network(+capability), stopes, timeline,
    # communication, sensors, development mesh — NOT the tunnel (rule 74)
    ((LV,), "LEGACY"): LEVELS_DOWN,
    ((LV,), "LAYOUT_V2"): LEVELS_DOWN,
    # generate_development_mesh :1456-1466: nothing (own stale GLB only)
    ((DM,), "LEGACY"): NOTHING,
    ((DM,), "LAYOUT_V2"): NOTHING,
    # generate_shafts :1108-1111: network(+capability), timeline, communication, sensors
    ((SH,), "LEGACY"): frozenset({N, CG, TL, CM, SN}),
    ((SH,), "LAYOUT_V2"): frozenset({N, CG, TL, CM, SN}),
    # generate_stopes :948: timeline only
    ((ST,), "LEGACY"): frozenset({TL}),
    ((ST,), "LAYOUT_V2"): frozenset({TL}),
    # generate_timeline :1026-1031: nothing
    ((TL,), "LEGACY"): NOTHING,
    ((TL,), "LAYOUT_V2"): NOTHING,
    # infra generate_communication :82-87 / generate_sensors :134-139: nothing (siblings)
    ((CM,), "LEGACY"): NOTHING,
    ((CM,), "LAYOUT_V2"): NOTHING,
    ((SN,), "LEGACY"): NOTHING,
    ((SN,), "LAYOUT_V2"): NOTHING,
    # generate_network :1255-1258: timeline, communication, sensors, capability — shafts kept
    ((N,), "LEGACY"): frozenset({TL, CM, SN, CG}),
    ((N,), "LAYOUT_V2"): frozenset({TL, CM, SN, CG}),
    # generate_capability_graph :1167-1172: nothing
    ((CG,), "LEGACY"): NOTHING,
    ((CG,), "LAYOUT_V2"): NOTHING,
}

#: every derived file the registry knows, grouped by artifact (delete units)
EXPECTED_FILES: dict[str, tuple[str, ...]] = {
    T: (T,),
    D: (D,),
    SM: (SM,),
    L: (L,),
    LS: (LS,),
    LA: (LA,),
    RS: (RS,),
    TM: (TM, TM_GLB),  # `tunnel_report_path` :1270-1271, `tunnel_glb_path` :1273-1274
    LV: (LV,),
    DM: (DM, DM_GLB),  # `development_mesh_report_path` :1355-1356, `_glb_path` :1358-1359
    SH: (SH,),
    ST: (ST,),
    TL: (TL,),
    CM: (CM,),
    SN: (SN,),
    N: (N,),
    CG: (CG,),
}


def _closure(written: tuple[str, ...], source: str) -> frozenset[str]:
    assert source in SOURCES
    return frozenset(f.name for s in invalidated_by(written, source) for f in s.files)


# -- projection 1: ordered fingerprint lists -------------------------------- #


@pytest.mark.parametrize("name", sorted(EXPECTED_INPUTS))
def test_frozen_census_inputs_equal_the_derivation(name: str) -> None:
    assert tuple(f.name for f in fingerprint_files(name)) == EXPECTED_INPUTS[name]


def test_fingerprint_lists_are_duplicate_free() -> None:
    for a in ARTIFACTS:
        names = [f.name for f in fingerprint_files(a.name)]
        assert len(names) == len(set(names)), (a.name, names)


def test_the_effective_ramp_group_is_the_ramp_input_bundle_in_order() -> None:
    assert tuple(d.target for d in GROUPS[EFFECTIVE_RAMP_GROUP]) == RAMP


def test_sensors_declares_the_same_list_as_communication() -> None:
    # infrastructure_service.py:104-105 reuses `_communication_input_paths`
    assert fingerprint_files(SN) == fingerprint_files(CM)


def test_level_accesses_carries_the_selection_inputs_and_no_capture_exists() -> None:
    # co-written under the selection's capture (:647); the registry gives it
    # the selection's list for its EDGES only (equivalence risk 4)
    assert fingerprint_files(LA) == fingerprint_files(LS)
    assert not hasattr(DesignService, "level_accesses_fingerprint")
    assert not hasattr(DesignService, "targets_fingerprint")


def test_fingerprint_paths_stay_rooted(tmp_path: Path) -> None:
    scenario_dir, derived_dir = tmp_path / "s", tmp_path / "s" / "derived"
    for a in ARTIFACTS:
        for p in fingerprint_paths(a.name, scenario_dir=scenario_dir, derived_dir=derived_dir):
            if p.name in (S, W):
                assert p.parent == scenario_dir, p
            else:
                assert p.parent == derived_dir, p


# -- projection 2: delete cascades ------------------------------------------ #


@pytest.mark.parametrize("cell", sorted(EXPECTED_DELETES, key=lambda c: (c[0], c[1])))
def test_frozen_census_deletes_equal_the_closure(cell: tuple[tuple[str, ...], str]) -> None:
    written, source = cell
    assert _closure(written, source) == EXPECTED_DELETES[cell], cell


def test_every_derived_artifact_has_a_delete_cell_under_both_sources() -> None:
    singles = {c[0][0] for c in EXPECTED_DELETES if len(c[0]) == 1}
    assert singles == {a.name for a in derived_artifacts()}
    for a in derived_artifacts():
        for source in SOURCES:
            assert ((a.name,), source) in EXPECTED_DELETES


def test_closure_is_returned_in_declaration_order_and_excludes_the_written() -> None:
    order = {a.name: i for i, a in enumerate(ARTIFACTS)}
    for source in SOURCES:
        for a in derived_artifacts():
            closure = invalidated_by((a.name,), source)
            idx = [order[s.name] for s in closure]
            assert idx == sorted(idx)
            assert a.name not in {s.name for s in closure}


def test_inputs_of_contributes_the_fingerprint_expansion_but_only_one_edge() -> None:
    edges = set(invalidation_edges())
    # tunnel fingerprint carries targets / decline (:1281-1282) …
    assert T in EXPECTED_INPUTS[TM] and D in EXPECTED_INPUTS[TM]
    # … but they reach the tunnel only through the LEGACY-gated smoothed artifact
    assert (T, TM) not in edges and (D, TM) not in edges and (SM, TM) in edges
    # registry-derived change detector (the census has no edge-count row): a new
    # or removed edge must be a deliberate registry edit visible in the diff
    assert len(invalidation_edges()) == 61


def test_unknown_artifact_is_an_error_never_an_empty_closure() -> None:
    with pytest.raises(KeyError):
        spec("nope.json")
    with pytest.raises(KeyError):
        invalidated_by(("nope.json",), "LEGACY")


# -- rule-anchored named cases ---------------------------------------------- #


def test_rule_74_levels_regeneration_keeps_the_tunnel() -> None:
    for source in SOURCES:
        assert not _closure((LV,), source) & {TM, TM_GLB}


def test_rule_162_a_source_switch_keeps_the_ramps_and_the_level_accesses() -> None:
    for source in SOURCES:
        assert not _closure((RS,), source) & {T, D, SM, L, LS, LA}


def test_rule_184_network_regeneration_keeps_the_shafts() -> None:
    for source in SOURCES:
        assert SH not in _closure((N,), source)


def test_rule_151_169_the_source_gate_isolates_the_two_chains() -> None:
    # selection alone is inert under LEGACY (test_layout_v2_api: 'selection alone is inert')
    assert _closure((LS, LA), "LEGACY") == NOTHING
    # a legacy re-smooth / targets regen under LAYOUT_V2 never touches the v2 chain
    assert _closure((SM,), "LAYOUT_V2") == NOTHING
    assert _closure((T,), "LAYOUT_V2") == {D, SM}
    # generating the catalogue under LEGACY deletes only the stale selection pair
    assert _closure((L,), "LEGACY") == {LS, LA}


def test_the_source_condition_sits_on_the_ramp_owning_artifacts_only() -> None:
    owners = {a.name: a.ramp_source for a in ARTIFACTS if a.ramp_source is not None}
    assert owners == {SM: "LEGACY", LS: "LAYOUT_V2", LA: "LAYOUT_V2"}
    assert set(core_artifacts.RAMP_OWNING_ARTIFACTS) <= set(owners)


# -- coverage / consistency with the world choke point ---------------------- #


def test_every_registered_derived_file_lives_under_derived() -> None:
    for a in ARTIFACTS:
        assert tuple(f.name for f in a.files) == EXPECTED_FILES.get(a.name, (a.name,))
        expected_location = "SCENARIO" if a.name in (S, W) else "DERIVED"
        assert all(f.location == expected_location for f in a.files), a.name
    assert {a.name for a in derived_artifacts()} == set(EXPECTED_FILES)


def test_world_closure_plus_ramp_source_covers_every_derived_artifact() -> None:
    # a consistency fact about `clear_derived` (rule 40 directory walk), NOT
    # the mechanism: world.json and unknown files are outside the registry
    every = {a.name for a in derived_artifacts()}
    for source in SOURCES:
        from_arrays = {a.name for a in invalidated_by((W,), source)}
        assert from_arrays | {RS} == every
        # scenario.json additionally reaches arrays.npz (a scenario-directory root)
        from_scenario = {a.name for a in invalidated_by((S,), source)}
        assert from_scenario == from_arrays | {W}
    assert "world.json" not in every


# -- the live services against the same census ------------------------------ #


def _services(tmp_path: Path) -> tuple[ScenarioStore, DesignService, InfrastructureService]:
    store = ScenarioStore(tmp_path / "scenarios")
    design = DesignService(store, WorldService(store))
    return store, design, InfrastructureService(store, design)


def test_live_public_fingerprint_methods_match_the_census(tmp_path: Path) -> None:
    _, design, infra = _services(tmp_path)
    sid = "empty"
    methods: dict[str, InputFingerprint] = {
        D: design.input_fingerprint(sid),
        SM: design.smoothing_fingerprint(sid),
        L: design.layout_fingerprint(sid),
        LV: design.levels_fingerprint(sid),
        ST: design.stopes_fingerprint(sid),
        TL: design.timeline_fingerprint(sid),
        SH: design.shafts_fingerprint(sid),
        CG: design.capability_fingerprint(sid),
        N: design.network_fingerprint(sid),
        TM: design.tunnel_fingerprint(sid),
        DM: design.development_mesh_fingerprint(sid),
        CM: infra.communication_fingerprint(sid),
        SN: infra.sensors_fingerprint(sid),
    }
    assert set(methods) | {LS} == set(EXPECTED_INPUTS)
    for name, fp in methods.items():
        assert tuple(e[0] for e in fp.entries) == EXPECTED_INPUTS[name], name


def test_selection_revision_bytes_are_identical(tmp_path: Path) -> None:
    store, design, _ = _services(tmp_path)
    sid = "s"
    derived = store.derived_dir(sid)
    derived.mkdir(parents=True)
    for n in (S, W):
        (store.scenario_dir(sid) / n).write_text(n)
    (derived / L).write_text("catalogue")
    # design_service.py:602-604 (and :640-642): the inline selection capture
    inline = InputFingerprint.capture(
        [store.scenario_path(sid), store.arrays_path(sid), design.layout_path(sid)]
    )
    via_registry = InputFingerprint.capture(
        fingerprint_paths(LS, scenario_dir=store.scenario_dir(sid), derived_dir=derived)
    )
    assert inline == via_registry and inline.entries == via_registry.entries
    layout_rev, cid = "abc123", "SPIRAL-x"

    def revision(fp: InputFingerprint) -> str:  # :622-624 verbatim
        return hashlib.sha256(
            json.dumps([fp.entries, layout_rev, cid], sort_keys=True).encode()
        ).hexdigest()[:16]

    assert revision(inline) == revision(via_registry)


def test_path_accessors_bind_to_the_registered_file_names(tmp_path: Path) -> None:
    store, design, infra = _services(tmp_path)
    sid = "s"
    derived = store.derived_dir(sid)
    accessors: dict[str, Path] = {
        T: Path(design.targets_path(sid)),
        D: Path(design.decline_path(sid)),
        SM: design.smoothed_path(sid),
        L: design.layout_path(sid),
        LS: design.layout_selected_path(sid),
        LA: design.level_accesses_path(sid),
        RS: design.ramp_source_path(sid),
        TM: design.tunnel_report_path(sid),
        TM_GLB: design.tunnel_glb_path(sid),
        LV: design.levels_path(sid),
        DM: design.development_mesh_report_path(sid),
        DM_GLB: design.development_mesh_glb_path(sid),
        SH: design.shafts_path(sid),
        ST: design.stopes_path(sid),
        TL: design.timeline_path(sid),
        CM: infra.communication_path(sid),
        SN: infra.sensors_path(sid),
        N: design.network_path(sid),
        CG: design.capability_graph_path(sid),
    }
    registered = {f.name for a in derived_artifacts() for f in a.files}
    assert set(accessors) == registered
    for name, path in accessors.items():
        assert path == derived / name, name
    assert store.scenario_path(sid) == store.scenario_dir(sid) / S
    assert store.arrays_path(sid) == store.scenario_dir(sid) / W


# -- leaf placement --------------------------------------------------------- #


def test_registry_is_a_leaf_module() -> None:
    source = Path(registry.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    first_party = {m for m in imported if m.startswith("minegen")}
    assert first_party == {"minegen.core.artifacts"}
    stdlib = {m for m in imported if not m.startswith("minegen")}
    assert stdlib <= {"__future__", "collections.abc", "dataclasses", "pathlib", "typing"}
    code = (
        "import sys, minegen.core.artifact_registry; "
        "bad = sorted(m for m in sys.modules if m.startswith(('minegen.services', "
        "'minegen.layout', 'minegen.design', 'minegen.api'))); "
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_effective_ramp_re_exports_the_core_ramp_source_literal() -> None:
    assert effective_ramp.RampSource is core_artifacts.RampSource
    assert "RampSource" in effective_ramp.__all__
    assert effective_ramp.RAMP_SOURCES == SOURCES
