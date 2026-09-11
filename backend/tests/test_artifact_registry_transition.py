"""AC-01E COMMIT 1 ONLY — the OLD hand-maintained lifecycle helpers of
``DesignService`` / ``InfrastructureService`` against the registry, executed
LIVE before the helpers are removed (commit 2 deletes this module together
with the helpers; the PR history carries the proof).

Two halves:

* every ``_*_input_paths`` list (12 in ``design_service.py``, the shared
  ``_communication_input_paths`` of ``infrastructure_service.py`` and the
  INLINE selection list) equals ``fingerprint_paths`` — same rooted paths,
  same order (list equality);
* every ``_delete_*`` helper and every inline cascade block (mirrored
  verbatim as the sequence of old helper calls it consists of, with the
  file:line it was transcribed from) removes exactly ``invalidated_by``'s
  closure, under both ramp sources, on a derived directory holding every
  registered file.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from minegen.core.artifact_registry import (
    ARTIFACTS,
    derived_artifacts,
    fingerprint_paths,
    invalidated_by,
)
from minegen.core.artifacts import RampSource
from minegen.services.design_service import DesignService, InputFingerprint
from minegen.services.effective_ramp import write_ramp_source
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from tests.test_artifact_registry import (
    CG,
    CM,
    DM,
    LA,
    LS,
    LV,
    RS,
    SH,
    SM,
    SN,
    SOURCES,
    ST,
    TL,
    TM,
    D,
    L,
    N,
    T,
)

SID = "transition"


@pytest.fixture
def services(tmp_path: Path) -> tuple[ScenarioStore, DesignService, InfrastructureService]:
    store = ScenarioStore(tmp_path / "scenarios")
    design = DesignService(store, WorldService(store))
    return store, design, InfrastructureService(store, design)


def _touch_everything(store: ScenarioStore) -> Path:
    derived = store.derived_dir(SID)
    derived.mkdir(parents=True, exist_ok=True)
    store.scenario_path(SID).write_text("{}", encoding="utf-8")
    store.arrays_path(SID).write_bytes(b"npz")
    for a in derived_artifacts():
        for f in a.files:
            (derived / f.name).write_text(f.name, encoding="utf-8")
    (derived / "world.json").write_text("{}", encoding="utf-8")  # unregistered, never cascaded
    return derived


# -- half 1: the 14 ordered input lists ------------------------------------- #


def test_old_input_lists_equal_the_registry_paths_in_order(
    services: tuple[ScenarioStore, DesignService, InfrastructureService],
) -> None:
    store, design, infra = services
    scenario_dir, derived_dir = store.scenario_dir(SID), store.derived_dir(SID)

    def reg(name: str) -> list[Path]:
        return fingerprint_paths(name, scenario_dir=scenario_dir, derived_dir=derived_dir)

    old: dict[str, list[Path]] = {
        D: design._input_paths(SID),  # design_service.py:366-371
        SM: design._smoothing_input_paths(SID),  # :413-414
        L: design._layout_input_paths(SID),  # :509-510
        # the INLINE selection list :602-604 / :640-642
        LS: [*design._layout_input_paths(SID), design.layout_path(SID)],
        LV: design._levels_input_paths(SID),  # :829-836
        ST: design._stopes_input_paths(SID),  # :905-910
        TL: design._timeline_input_paths(SID),  # :982-991
        SH: design._shafts_input_paths(SID),  # :1070-1073
        CG: design._capability_input_paths(SID),  # :1135-1142
        N: design._network_input_paths(SID),  # :1205-1214
        TM: design._tunnel_input_paths(SID),  # :1281-1282
        DM: design._development_mesh_input_paths(SID),  # :1369-1370
        CM: infra._communication_input_paths(SID),  # infrastructure_service.py:41-50
        SN: infra._communication_input_paths(SID),  # :104-105 (sensors reuses it)
    }
    for name, paths in old.items():
        assert paths == reg(name), (name, [p.name for p in paths], [p.name for p in reg(name)])
    # the ramp bundle itself (:497-507) is the registry's EFFECTIVE_RAMP group,
    # expanded at its declared position inside every consumer list
    assert [p.name for p in design._ramp_input_paths(SID)] == [SM, LS, LA, RS]
    # every list is rooted exactly as the store roots it
    for paths in old.values():
        for p in paths:
            rooted_in = scenario_dir if p.name in ("scenario.json", "arrays.npz") else derived_dir
            assert p.parent == rooted_in, p


def test_selection_revision_from_the_inline_capture_equals_the_registry_capture(
    services: tuple[ScenarioStore, DesignService, InfrastructureService],
) -> None:
    store, design, _ = services
    derived = _touch_everything(store)
    inline = InputFingerprint.capture(
        [*design._layout_input_paths(SID), design.layout_path(SID)]  # :602-604
    )
    via_registry = InputFingerprint.capture(
        fingerprint_paths(LS, scenario_dir=store.scenario_dir(SID), derived_dir=derived)
    )
    assert inline.entries == via_registry.entries
    layout_rev, candidate_id = "0123456789abcdef", "SPIRAL-CW-g0.125"

    def revision(fp: InputFingerprint) -> str:  # design_service.py:622-624 verbatim
        return hashlib.sha256(
            json.dumps([fp.entries, layout_rev, candidate_id], sort_keys=True).encode()
        ).hexdigest()[:16]

    assert revision(inline) == revision(via_registry)


# -- half 2: the old cascades vs the registry closure ----------------------- #


def _unlink(path: Path) -> None:
    if path.exists():
        path.unlink()


def _cascades(design: DesignService) -> dict[tuple[str, ...], Callable[[], None]]:
    """Every old cascade as the exact sequence of old calls it consists of."""
    sid = SID
    return {
        # set_ramp_source :791-793 — unconditional `_delete_ramp_downstream` :521-531
        (RS,): lambda: design._delete_ramp_downstream(sid),
        # generate_smoothed :468
        (SM,): lambda: design._delete_ramp_downstream_if_active(sid, "LEGACY"),
        # select_layout_candidate :648 (LS + LA written together :645-647)
        (LS, LA): lambda: design._delete_ramp_downstream_if_active(sid, "LAYOUT_V2"),
        # generate_layout_v2 :559-560
        (L,): lambda: (
            design._delete_layout_selection(sid),
            design._delete_ramp_downstream_if_active(sid, "LAYOUT_V2"),
        ),
        # generate_targets :329-337
        (T,): lambda: (
            _unlink(design.decline_path(sid)),  # :329-331
            _unlink(design.smoothed_path(sid)),  # :332-334
            design._delete_ramp_downstream_if_active(sid, "LEGACY"),  # :337
        ),
        # generate_decline :402-405
        (D,): lambda: (
            _unlink(design.smoothed_path(sid)),  # :402-404
            design._delete_ramp_downstream_if_active(sid, "LEGACY"),  # :405
        ),
        # generate_levels :879-885
        (LV,): lambda: (
            design._delete_shafts_artifact(sid),  # :879
            design._delete_network_artifact(sid),  # :880 (→ capability :1050)
            design._delete_stopes_artifact(sid),  # :881
            design._delete_timeline_artifact(sid),  # :882
            design._delete_communication_artifact(sid),  # :883
            design._delete_sensors_artifact(sid),  # :884
            design._delete_development_mesh_artifacts(sid),  # :885
        ),
        # generate_stopes :948
        (ST,): lambda: design._delete_timeline_artifact(sid),
        # generate_shafts :1108-1111
        (SH,): lambda: (
            design._delete_network_artifact(sid),  # :1108 (→ capability :1050)
            design._delete_timeline_artifact(sid),  # :1109
            design._delete_communication_artifact(sid),  # :1110
            design._delete_sensors_artifact(sid),  # :1111
        ),
        # generate_network :1255-1258
        (N,): lambda: (
            design._delete_timeline_artifact(sid),  # :1255
            design._delete_communication_artifact(sid),  # :1256
            design._delete_sensors_artifact(sid),  # :1257
            design._delete_capability_graph_artifact(sid),  # :1258
        ),
        # generate_timeline :1026-1031, generate_capability_graph :1167-1172,
        # generate_tunnel :1340-1350, generate_development_mesh :1456-1466,
        # infra generate_communication :82-87, generate_sensors :134-139: no cascade
        (TL,): lambda: None,
        (CG,): lambda: None,
        (TM,): lambda: None,
        (DM,): lambda: None,
        (CM,): lambda: None,
        (SN,): lambda: None,
    }


@pytest.mark.parametrize("source", SOURCES)
def test_old_cascades_remove_exactly_the_registry_closure(
    services: tuple[ScenarioStore, DesignService, InfrastructureService], source: RampSource
) -> None:
    store, design, _ = services
    cascades = _cascades(design)
    # every derived artifact is covered (the pair stands for its two members)
    assert {n for key in cascades for n in key} == {a.name for a in derived_artifacts()}
    for written, cascade in cascades.items():
        derived = _touch_everything(store)
        write_ramp_source(derived, source)  # the gate `_if_active` reads at write time (:534)
        before = {p.name for p in derived.iterdir()}
        cascade()
        after = {p.name for p in derived.iterdir()}
        expected = {f.name for s in invalidated_by(written, source) for f in s.files}
        assert before - after == expected, (written, source, sorted((before - after) ^ expected))
        assert (derived / "world.json").is_file()  # never part of a cascade
        assert store.arrays_path(SID).is_file() and store.scenario_path(SID).is_file()


def test_the_gate_helper_itself_is_the_ramp_owner_condition(
    services: tuple[ScenarioStore, DesignService, InfrastructureService],
) -> None:
    """`_delete_ramp_downstream_if_active(sid, X)` :533-535 fires iff the
    persisted source is X — the registry expresses the same condition as the
    `ramp_source` attribute of the ramp-OWNING artifacts."""
    store, design, _ = services
    owners = {a.name: a.ramp_source for a in ARTIFACTS if a.ramp_source is not None}
    assert owners == {SM: "LEGACY", LS: "LAYOUT_V2", LA: "LAYOUT_V2"}
    for owner, gate in owners.items():
        for source in SOURCES:
            derived = _touch_everything(store)
            write_ramp_source(derived, source)
            before = {p.name for p in derived.iterdir()}
            design._delete_ramp_downstream_if_active(SID, gate)
            removed = before - {p.name for p in derived.iterdir()}
            expected = {f.name for s in invalidated_by((owner,), source) for f in s.files}
            assert removed == expected, (owner, source)
            assert bool(removed) == (gate == source)
