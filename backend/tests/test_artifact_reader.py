"""AC-01F — unit contract of the validated read authority.

FAST tier: no world, no search, no API. Every document is HAND-WRITTEN under a
throwaway ``ScenarioStore`` and every expected revision is computed
INDEPENDENTLY of the production code — ``hashlib.sha256(f"{name}:{size}:
{mtime_ns}")[:16]`` straight from ``os.stat`` (never ``file_revision``), the
§29 no-self-fulfilling-oracle rule. Staleness is produced the way the Stage A
probes produced it: ``os.utime`` on the pinned input, byte appends, ``"{"``,
``{"hello":"world"}``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from minegen.core.artifact_registry import derived_artifacts, invalidated_by, spec
from minegen.core.artifacts import (
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
    SENSORS_ARTIFACT,
    SHAFTS_ARTIFACT,
    STOPES_ARTIFACT,
    TARGETS_ARTIFACT,
    TIMELINE_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
    TUNNEL_MESH_GLB,
)
from minegen.core.world_record import WORLD_RECORD_FILE, build_world_record
from minegen.layout.certification import ClearancePolicyReconstructionError
from minegen.services.artifact_errors import (
    ArtifactMalformedError,
    ArtifactStaleError,
    CapabilityGraphStaleError,
    LayoutSelectionStaleError,
    ShaftsStaleError,
    WorldNotGeneratedError,
    WorldPublicationStaleError,
)
from minegen.services.artifact_reader import READ_SPECS, ArtifactReader
from minegen.services.scenario_service import ScenarioNotFoundError, ScenarioStore

SID = "reader"
GLB_BYTES = b"glTF-not-really-but-bytes"
GLB_DIGEST = hashlib.sha256(GLB_BYTES).hexdigest()


# --------------------------------------------------------------------------- #
# independent revision oracle (§29: never file_revision)
# --------------------------------------------------------------------------- #


def expected_revision(path: Path) -> str:
    st = os.stat(path)
    return hashlib.sha256(f"{path.name}:{st.st_size}:{st.st_mtime_ns}".encode()).hexdigest()[:16]


def bump_mtime(path: Path, seconds: float = 5.0) -> None:
    """The Stage A §4 recipe: change ONLY the revision of an input."""
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + int(seconds * 1e9)))


@contextmanager
def mutated(path: Path) -> Iterator[None]:
    """Restore the ORIGINAL bytes AND ``st_mtime_ns`` — the discipline the
    commit-1 characterization module established before it was deleted with
    the consumers it characterized. Stage A C-12: rewriting the bytes alone
    silently changes ``file_revision`` (``name:size:mtime_ns``) and
    contaminates every later case in the same loop."""
    data = path.read_bytes()
    st = os.stat(path)
    try:
        yield
    finally:
        path.write_bytes(data)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))


def assert_reads_valid(reader: ArtifactReader, name: str) -> None:
    """The restore actually restored: the artifact reads VALID again, so a
    contaminated revision cannot hide behind a later assertion."""
    read_spec = READ_SPECS[name]
    snapshot = reader.snapshot(
        SID,
        [name, *read_spec.provenance_inputs, *read_spec.agreement_inputs],
        glb_bytes=True,
    )
    read = reader.read(snapshot, name)
    assert read.state == "VALID", (name, read.state, read.error)


# --------------------------------------------------------------------------- #
# minimal VALID documents (one per registered derived artifact)
# --------------------------------------------------------------------------- #


def _payload(**extra: Any) -> dict[str, Any]:
    return {"status": "FAILED", "failureReason": None, "sourceRevision": "src", **extra}


CLEARANCE_BASIS = "EXACT"
CLEARANCE_BOUND = 0.0
REQUIRED_CLEARANCE = 12.5
CANDIDATE_ID = "SWITCHBACK-k1-p+20-CW-g0.120"
SELECTION_REVISION = "0123456789abcdef"


def _selection(layout_revision: str) -> dict[str, Any]:
    return {
        "candidateId": CANDIDATE_ID,
        "sourceRevision": SELECTION_REVISION,
        "layoutRevision": layout_revision,
        "segments": [],
        "clearance": {
            "clearanceBasis": CLEARANCE_BASIS,
            "requiredClearance": REQUIRED_CLEARANCE,
            "conservativeMinimumClearance": 20.0,
            "approximateMinimumClearance": None,
            "clearanceErrorBound": CLEARANCE_BOUND,
            "satisfied": True,
            "refinement": None,
        },
    }


def _accesses(layout_revision: str) -> dict[str, Any]:
    return {
        "candidateId": CANDIDATE_ID,
        "sourceRevision": SELECTION_REVISION,
        "layoutRevision": layout_revision,
        "accesses": [],
        "clearanceBasis": CLEARANCE_BASIS,
        "clearanceErrorBound": CLEARANCE_BOUND,
        "clearanceRefinement": None,
        "requiredClearance": REQUIRED_CLEARANCE,
    }


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def write_world_record(store: ScenarioStore, scenario_id: str = SID) -> None:
    """Publish the WORLD COMMIT RECORD for the CURRENT ``scenario.json`` and
    ``arrays.npz`` of this hand-written store (AC-01F.2 correction B1).

    A hand-built store must be a COMMITTED store: since the correction, a
    world is trusted only while ``derived/world.json`` names the two live
    revisions, so a fixture that writes the two files without the record
    describes a state production can no longer produce. Every test that
    rewrites ``arrays.npz`` or the document re-publishes the record — except
    where the STALE record is the subject."""
    derived = store.derived_dir(scenario_id)
    derived.mkdir(parents=True, exist_ok=True)
    write_json(
        derived / WORLD_RECORD_FILE,
        build_world_record(
            scenario_id=scenario_id,
            scenario_revision=expected_revision(store.scenario_path(scenario_id)),
            arrays_revision=expected_revision(store.arrays_path(scenario_id)),
            stats={},
        ),
    )


@pytest.fixture
def stack(tmp_path: Path) -> tuple[ScenarioStore, ArtifactReader, Path]:
    """A complete, VALID derived set — every registered artifact present."""
    store = ScenarioStore(tmp_path / "scenarios")
    store.scenario_path(SID).parent.mkdir(parents=True, exist_ok=True)
    store.scenario_path(SID).write_text('{"schemaVersion": 2}', encoding="utf-8")
    store.arrays_path(SID).write_bytes(b"npz")
    derived = store.derived_dir(SID)
    derived.mkdir(parents=True, exist_ok=True)
    write_world_record(store)

    write_json(derived / TARGETS_ARTIFACT, {"levels": []})
    write_json(derived / DECLINE_ARTIFACT, {"levels": []})
    write_json(derived / LEGACY_RAMP_ARTIFACT, {"segments": []})
    write_json(derived / LAYOUT_V2_ARTIFACT, {"candidates": [], "winnerId": None})
    layout_revision = expected_revision(derived / LAYOUT_V2_ARTIFACT)
    write_json(derived / LAYOUT_V2_SELECTED_ARTIFACT, _selection(layout_revision))
    write_json(derived / LEVEL_ACCESSES_ARTIFACT, _accesses(layout_revision))
    write_json(derived / RAMP_SOURCE_FILE, {"activeSource": "LEGACY"})
    (derived / TUNNEL_MESH_GLB).write_bytes(GLB_BYTES)
    (derived / DEVELOPMENT_MESH_GLB).write_bytes(GLB_BYTES)
    # AC-01F.2 correction B3: a SUCCESS report names the GLB publication it
    # belongs to, so a hand-written pair must name it too — the reports the
    # production writer publishes always do
    write_json(
        derived / TUNNEL_MESH_ARTIFACT,
        {
            "status": "SUCCESS",
            "artifactRevision": GLB_DIGEST,
            "glbRevision": expected_revision(derived / TUNNEL_MESH_GLB),
            "meshUrl": "/mesh.glb",
        },
    )
    write_json(
        derived / DEVELOPMENT_MESH_ARTIFACT,
        {
            "status": "SUCCESS",
            "artifactRevision": GLB_DIGEST,
            "glbRevision": expected_revision(derived / DEVELOPMENT_MESH_GLB),
            "meshUrl": "/dev.glb",
            "sources": {"levelAccesses": True, "levels": True, "rampSource": "LEGACY"},
        },
    )
    write_json(
        derived / LEVELS_ARTIFACT,
        _payload(developments=[], levels=[], metrics=None),
    )
    levels_revision = expected_revision(derived / LEVELS_ARTIFACT)
    write_json(
        derived / SHAFTS_ARTIFACT,
        _payload(levelsRevision=levels_revision, shafts=[], centerlines=[], metrics=None),
    )
    write_json(
        derived / STOPES_ARTIFACT,
        _payload(method="LONGHOLE_OPEN_STOPING", stopes=[], metrics=None),
    )
    write_json(
        derived / NETWORK_ARTIFACT,
        _payload(nodes=[], edges=[], metrics=None, validation=None, surfacePathAdvisory=[]),
    )
    network_revision = expected_revision(derived / NETWORK_ARTIFACT)
    write_json(
        derived / CAPABILITY_GRAPH_ARTIFACT,
        _payload(
            networkRevision=network_revision,
            networkSourceRevision="src",
            capabilities=[],
            nodes=[],
            edges=[],
            surfaceNodeIds=[],
            requiredPaths=[],
            egressAdvisory=None,
            validation=None,
            metrics=None,
        ),
    )
    write_json(
        derived / TIMELINE_ARTIFACT,
        _payload(startDay=0.0, endDay=0.0, tasks=[], developments=[], stopes=[], metrics=None),
    )
    write_json(
        derived / COMMUNICATION_ARTIFACT,
        _payload(
            model=None,
            candidates=[],
            demands=[],
            selectedAssets=[],
            demandCoverage=[],
            metrics=None,
        ),
    )
    write_json(
        derived / SENSORS_ARTIFACT,
        _payload(
            model=None,
            candidates=[],
            demands=[],
            selectedSensors=[],
            demandCoverage=[],
            metrics=None,
        ),
    )
    return store, ArtifactReader(store), derived


# --------------------------------------------------------------------------- #
# the spec table vs the registry
# --------------------------------------------------------------------------- #


def test_read_specs_cover_every_registered_derived_artifact() -> None:
    registered = {a.name for a in derived_artifacts()}
    assert RAMP_SOURCE_FILE in registered  # the union of the directive is this set
    assert set(READ_SPECS) == registered | {RAMP_SOURCE_FILE}
    assert len(READ_SPECS) == 17


def test_every_provenance_link_is_a_registry_closure_edge() -> None:
    """Stage B §14 Q8: the resolver may not declare a dependency the AC-01E
    registry does not own."""
    for name, read_spec in READ_SPECS.items():
        for upstream in read_spec.provenance_inputs:
            closures = {
                source: {a.name for a in invalidated_by([upstream], source)}
                for source in ("LEGACY", "LAYOUT_V2")
            }
            assert any(name in c for c in closures.values()), (name, upstream, closures)


def test_agreement_pairs_are_one_registry_capture() -> None:
    """The selection ↔ level-access pair is CO-PUBLISHED, not a dependency:
    the registry declares identical ordered inputs and the same ramp-source
    gate for both (core/artifact_registry.py:217-230).

    C5 makes the declaration SYMMETRIC — each half names the other — because
    the pair is one READ unit in both directions, not only in the direction
    the crash window happens not to produce."""
    pairs = [
        (name, other)
        for name, read_spec in READ_SPECS.items()
        for other in read_spec.agreement_inputs
    ]
    assert sorted(pairs) == sorted(
        [
            (LEVEL_ACCESSES_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT),
            (LAYOUT_V2_SELECTED_ARTIFACT, LEVEL_ACCESSES_ARTIFACT),
        ]
    )
    for name, other in pairs:
        assert spec(name).inputs == spec(other).inputs
        assert spec(name).ramp_source == spec(other).ramp_source == "LAYOUT_V2"


def test_only_the_ramp_source_has_an_absent_default() -> None:
    defaults = {n: s.absent_default for n, s in READ_SPECS.items() if s.absent_default}
    assert defaults == {RAMP_SOURCE_FILE: "LEGACY"}
    assert READ_SPECS[RAMP_SOURCE_FILE].absent_error is None
    assert all(s.absent_error is not None for n, s in READ_SPECS.items() if n != RAMP_SOURCE_FILE)


# --------------------------------------------------------------------------- #
# the four states
# --------------------------------------------------------------------------- #


def test_every_artifact_reads_valid_on_the_hand_written_stack(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    _, reader, derived = stack
    snapshot = reader.snapshot(SID, glb_bytes=True)
    for name in READ_SPECS:
        read = reader.read(snapshot, name)
        assert read.state == "VALID", (name, read.error)
        assert read.raw == json.loads((derived / name).read_text(encoding="utf-8"))
        assert read.revision == expected_revision(derived / name)
        assert (read.model is not None) == (READ_SPECS[name].model is not None)


def test_every_artifact_reads_absent_when_the_file_is_gone(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    _, reader, derived = stack
    for name in READ_SPECS:
        (derived / name).unlink()
    snapshot = reader.snapshot(SID)
    for name in READ_SPECS:
        read = reader.read(snapshot, name)
        assert read.state == "ABSENT" and read.error is None and read.raw is None, name


#: what the READ authority answers for a valid-JSON document of the WRONG
#: shape (``{"hello":"world"}``) — today's behaviour for the same mutation is
#: in Stage A §2.2-2.5 (raw readers 200 serving the junk, validated readers
#: 500). ``targets.json`` is the one artifact with NO first-level precondition:
#: no consumer subscripts it (``_targets_object`` is presence-only,
#: ``design_service.py:409-428``), so the resolver claims nothing about its
#: inner shape and a wrong-shaped document stays VALID.
WRONG_SHAPE_CODES: dict[str, str | None] = {
    TARGETS_ARTIFACT: None,  # VALID: no declared precondition (honest, §8.2)
    DECLINE_ARTIFACT: "ARTIFACT_MALFORMED",
    LEGACY_RAMP_ARTIFACT: "ARTIFACT_MALFORMED",
    LAYOUT_V2_ARTIFACT: "ARTIFACT_MALFORMED",
    # A1 / C-8: the selection's revision check fires BEFORE its certification
    LAYOUT_V2_SELECTED_ARTIFACT: "LAYOUT_V2_SELECTION_STALE",
    # the co-published half runs the SAME A1 order, so a document with no
    # layoutRevision is STALE here too — not the certification failure
    LEVEL_ACCESSES_ARTIFACT: "LAYOUT_V2_SELECTION_STALE",
    RAMP_SOURCE_FILE: "ARTIFACT_MALFORMED",
    TUNNEL_MESH_ARTIFACT: "ARTIFACT_MALFORMED",
    DEVELOPMENT_MESH_ARTIFACT: "ARTIFACT_MALFORMED",
    LEVELS_ARTIFACT: "ARTIFACT_MALFORMED",
    SHAFTS_ARTIFACT: "ARTIFACT_MALFORMED",
    STOPES_ARTIFACT: "ARTIFACT_MALFORMED",
    TIMELINE_ARTIFACT: "ARTIFACT_MALFORMED",
    NETWORK_ARTIFACT: "ARTIFACT_MALFORMED",
    CAPABILITY_GRAPH_ARTIFACT: "ARTIFACT_MALFORMED",
    COMMUNICATION_ARTIFACT: "ARTIFACT_MALFORMED",
    SENSORS_ARTIFACT: "ARTIFACT_MALFORMED",
}


@pytest.mark.parametrize("junk", ["{", "[1,2,3]", '"text"', "17"])
def test_unparseable_or_non_object_json_is_malformed_for_every_artifact(
    stack: tuple[ScenarioStore, ArtifactReader, Path], junk: str
) -> None:
    """M-J (``{`` — the probe's exact torn symptom) and every non-object JSON
    document: ARTIFACT_MALFORMED on all 17, before any other check (A1)."""
    _, reader, derived = stack
    for name in READ_SPECS:
        with mutated(derived / name):
            (derived / name).write_text(junk, encoding="utf-8")
            snapshot = reader.snapshot(SID, [name, *READ_SPECS[name].provenance_inputs])
            read = reader.read(snapshot, name)
            assert read.state == "MALFORMED", (name, junk, read.state)
            assert isinstance(read.error, ArtifactMalformedError), (name, junk)
            assert read.error.artifact == name
        assert_reads_valid(reader, name)


def test_wrong_shaped_documents_answer_the_declared_code(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    """M-S: valid JSON, wrong shape. A13 — the generic ARTIFACT_MALFORMED
    never overwrites a certification / selection failure."""
    _, reader, derived = stack
    assert set(WRONG_SHAPE_CODES) == set(READ_SPECS)
    for name, expected in WRONG_SHAPE_CODES.items():
        with mutated(derived / name):
            write_json(derived / name, {"hello": "world"})
            snapshot = reader.snapshot(
                SID,
                [name, *READ_SPECS[name].provenance_inputs, *READ_SPECS[name].agreement_inputs],
            )
            read = reader.read(snapshot, name)
            if expected is None:
                assert read.state == "VALID" and read.error is None, (name, read.state)
            else:
                assert read.state in ("MALFORMED", "STALE"), (name, read.state)
                assert read.error is not None
                assert type(read.error).code == expected, (name, read.error)
        assert_reads_valid(reader, name)


def test_first_level_shape_preconditions_are_the_subscripts_consumers_perform(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    _, reader, derived = stack
    layout_revision = expected_revision(derived / LAYOUT_V2_ARTIFACT)
    # (artifact, document) ROWS, not a dict: Stage D B2 ADDS three rows for
    # the same artifacts rather than replacing the ones that were here, so the
    # WRONG-TYPE case and the LIST-OF-NON-OBJECTS case are both still pinned.
    cases: tuple[tuple[str, dict[str, Any]], ...] = (
        (DECLINE_ARTIFACT, {"levels": "not-a-list"}),
        (LEGACY_RAMP_ARTIFACT, {"segments": ["not-an-object"]}),
        (LAYOUT_V2_ARTIFACT, {"candidates": {}}),
        (RAMP_SOURCE_FILE, {"activeSource": "MAGIC"}),
        (TUNNEL_MESH_ARTIFACT, {"status": "SUCCESS", "artifactRevision": "short"}),
        (DEVELOPMENT_MESH_ARTIFACT, {"status": "FAILED", "sources": {}}),
        # Stage D B2: the three preconditions that tested the LIST and not its
        # ELEMENTS. The consumers subscript DICTS
        # (``lv.get("selectedCandidateId")``, ``for k, v in c.items()``,
        # ``acc.get("status")``), so a list of NON-objects used to be VALID and
        # leaked a bare 500 one step later. The certification-bearing document
        # keeps a valid ``layoutRevision`` and certification so A1's fixed
        # order reaches the SHAPE check.
        (DECLINE_ARTIFACT, {"levels": [1, 2]}),
        (LAYOUT_V2_ARTIFACT, {"candidates": [1, 2]}),
        (
            LEVEL_ACCESSES_ARTIFACT,
            {**_accesses(layout_revision), "accesses": ["not-an-object"]},
        ),
        # the SELECTION's ``segments`` precondition already used the right
        # helper and was exercised by no row at all: deleting
        # ``_selection_segments_check`` outright (Stage D mutation M22) left
        # the whole suite green. A1's fixed order reaches it only over a
        # valid ``layoutRevision`` and a valid ``clearance`` block.
        (
            LAYOUT_V2_SELECTED_ARTIFACT,
            {**_selection(layout_revision), "segments": ["not-an-object"]},
        ),
    )
    for name, document in cases:
        with mutated(derived / name):
            write_json(derived / name, document)
            snapshot = reader.snapshot(SID, [name, *READ_SPECS[name].provenance_inputs])
            read = reader.read(snapshot, name)
            assert read.state == "MALFORMED", (name, read.state)
            assert isinstance(read.error, ArtifactMalformedError)
            assert read.error.artifact == name
        assert_reads_valid(reader, name)


def test_typed_payload_models_are_the_precondition_of_the_eight(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    _, reader, derived = stack
    for name, read_spec in READ_SPECS.items():
        if read_spec.model is None:
            continue
        with mutated(derived / name):
            document = json.loads((derived / name).read_text(encoding="utf-8"))
            document["unexpectedKey"] = 1  # ApiModel is extra="forbid"
            write_json(derived / name, document)
            snapshot = reader.snapshot(SID, [name, *read_spec.provenance_inputs])
            read = reader.read(snapshot, name)
            assert read.state == "MALFORMED", name
            assert isinstance(read.error, ArtifactMalformedError)
            assert read_spec.model.__name__ in str(read.error)
        assert_reads_valid(reader, name)


def test_stale_states_are_the_persisted_upstream_revision_relations(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    """The three revision relations that exist on disk + the two AC-01F ones.
    Every expected revision is recomputed here from ``os.stat``.

    Cases 4 / 4b carry the Stage-B checkpoint decision C1: in the rule-157
    co-published pair, a ``candidateId`` or certification (provenance key /
    error bound) disagreement is A1's third row — a "candidate identity /
    clearance recipe defect", i.e. ``ClearancePolicyReconstructionError``
    (``LAYOUT_V2_CLEARANCE_MISMATCH``) with the state still STALE — while
    ``sourceRevision`` / ``layoutRevision`` and an orphaned half stay
    ``LAYOUT_V2_SELECTION_STALE``. Case 4 is the same-PR correction of the
    commit-1 row that pinned STALE's code for the candidate identity."""
    _, reader, derived = stack

    # 1. shafts.levelsRevision ↔ levels.json (design_service.py:1065)
    bump_mtime(derived / LEVELS_ARTIFACT)
    read = reader.read(reader.snapshot(SID, [SHAFTS_ARTIFACT, LEVELS_ARTIFACT]), SHAFTS_ARTIFACT)
    assert read.state == "STALE" and isinstance(read.error, ShaftsStaleError)
    document = json.loads((derived / SHAFTS_ARTIFACT).read_text(encoding="utf-8"))
    assert document["levelsRevision"] != expected_revision(derived / LEVELS_ARTIFACT)

    # 2. capabilityGraph.networkRevision ↔ network.json (:1112)
    bump_mtime(derived / NETWORK_ARTIFACT)
    read = reader.read(
        reader.snapshot(SID, [CAPABILITY_GRAPH_ARTIFACT, NETWORK_ARTIFACT]),
        CAPABILITY_GRAPH_ARTIFACT,
    )
    assert read.state == "STALE" and isinstance(read.error, CapabilityGraphStaleError)

    # 2b. the recorded networkSourceRevision against the network's own field
    document = json.loads((derived / CAPABILITY_GRAPH_ARTIFACT).read_text(encoding="utf-8"))
    document["networkRevision"] = expected_revision(derived / NETWORK_ARTIFACT)
    document["networkSourceRevision"] = "a-different-build"
    write_json(derived / CAPABILITY_GRAPH_ARTIFACT, document)
    read = reader.read(
        reader.snapshot(SID, [CAPABILITY_GRAPH_ARTIFACT, NETWORK_ARTIFACT]),
        CAPABILITY_GRAPH_ARTIFACT,
    )
    assert read.state == "STALE" and isinstance(read.error, CapabilityGraphStaleError)

    # 3. selection.layoutRevision ↔ layout_v2.json (:751)
    bump_mtime(derived / LAYOUT_V2_ARTIFACT)
    read = reader.read(
        reader.snapshot(SID, [LAYOUT_V2_SELECTED_ARTIFACT, LAYOUT_V2_ARTIFACT]),
        LAYOUT_V2_SELECTED_ARTIFACT,
    )
    assert read.state == "STALE" and isinstance(read.error, LayoutSelectionStaleError)

    # 4. the co-published pair: level accesses of ANOTHER candidate (§7.4).
    #    C1 (Stage-B checkpoint, a same-PR correction of the commit-1 row that
    #    pinned LAYOUT_V2_SELECTION_STALE here): a candidate-IDENTITY
    #    disagreement is A1's third row — "candidate identity / clearance
    #    recipe defect" → LAYOUT_V2_CLEARANCE_MISMATCH — while the STATE stays
    #    STALE (the document is well-shaped; its pair is not). Only
    #    sourceRevision / layoutRevision and an orphaned half stay
    #    LAYOUT_V2_SELECTION_STALE (cases below and in
    #    ``test_the_co_published_pair_compares_its_own_identity_not_a_recomputation``).
    layout_revision = expected_revision(derived / LAYOUT_V2_ARTIFACT)
    write_json(derived / LAYOUT_V2_SELECTED_ARTIFACT, _selection(layout_revision))
    accesses = _accesses(layout_revision)
    accesses["candidateId"] = "SPIRAL-n1-CCW-e+0-g0.120"
    write_json(derived / LEVEL_ACCESSES_ARTIFACT, accesses)
    read = reader.read(
        reader.snapshot(
            SID, [LEVEL_ACCESSES_ARTIFACT, LAYOUT_V2_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT]
        ),
        LEVEL_ACCESSES_ARTIFACT,
    )
    assert read.state == "STALE" and isinstance(read.error, ClearancePolicyReconstructionError)
    assert type(read.error).code == "LAYOUT_V2_CLEARANCE_MISMATCH"
    assert "candidateId" in str(read.error)

    # 4b. C1's other half: the certification (provenance key / error bound)
    #     disagreement of the same co-published pair is the SAME defect class
    accesses = _accesses(layout_revision)
    accesses["clearanceErrorBound"] = CLEARANCE_BOUND + 1e-3
    write_json(derived / LEVEL_ACCESSES_ARTIFACT, accesses)
    read = reader.read(
        reader.snapshot(
            SID, [LEVEL_ACCESSES_ARTIFACT, LAYOUT_V2_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT]
        ),
        LEVEL_ACCESSES_ARTIFACT,
    )
    assert read.state == "STALE" and isinstance(read.error, ClearancePolicyReconstructionError)
    assert type(read.error).code == "LAYOUT_V2_CLEARANCE_MISMATCH"
    assert "clearance certification" in str(read.error)
    write_json(derived / LEVEL_ACCESSES_ARTIFACT, _accesses(layout_revision))

    # 5. development_mesh.sources.rampSource ↔ the resolved active source
    write_json(derived / RAMP_SOURCE_FILE, {"activeSource": "LAYOUT_V2"})
    read = reader.read(
        reader.snapshot(SID, [DEVELOPMENT_MESH_ARTIFACT, RAMP_SOURCE_FILE]),
        DEVELOPMENT_MESH_ARTIFACT,
    )
    assert read.state == "STALE" and isinstance(read.error, ArtifactStaleError)


def test_two_file_units_fail_closed(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    """A SUCCESS report without its GLB, and GLB bytes that do not hash to the
    report's own ``artifactRevision`` (Stage A §7.2 / §7.4)."""
    _, reader, derived = stack
    (derived / TUNNEL_MESH_GLB).unlink()
    read = reader.read(reader.snapshot(SID, [TUNNEL_MESH_ARTIFACT]), TUNNEL_MESH_ARTIFACT)
    assert read.state == "MALFORMED" and isinstance(read.error, ArtifactMalformedError)
    assert TUNNEL_MESH_GLB in str(read.error)

    (derived / DEVELOPMENT_MESH_GLB).write_bytes(GLB_BYTES[: len(GLB_BYTES) // 2])
    snapshot = reader.snapshot(SID, [DEVELOPMENT_MESH_ARTIFACT, RAMP_SOURCE_FILE], glb_bytes=True)
    read = reader.read(snapshot, DEVELOPMENT_MESH_ARTIFACT)
    assert read.state == "MALFORMED" and isinstance(read.error, ArtifactMalformedError)
    assert "artifactRevision" in str(read.error)
    # stat-only snapshot: the truncated GLB is PRESENT and its BYTES are not
    # in hand, so the hash check cannot see it — until the AC-01F.2 correction
    # that made this read VALID, which is finding B3 (a republication that died
    # between the GLB and its report was 200 on the report route and in the
    # scene). The publication IDENTITY is visible to a stat, so the read is now
    # STALE. Two codes for one physical state, by design: the binary route
    # holds the bytes and keeps the more specific MALFORMED (asserted above).
    stat_only = reader.read(
        reader.snapshot(SID, [DEVELOPMENT_MESH_ARTIFACT, RAMP_SOURCE_FILE]),
        DEVELOPMENT_MESH_ARTIFACT,
    )
    assert stat_only.state == "STALE" and isinstance(stat_only.error, ArtifactStaleError)
    assert DEVELOPMENT_MESH_GLB in str(stat_only.error)


# --------------------------------------------------------------------------- #
# A1: the fixed selection validation order (AC-01D tamper matrix)
# --------------------------------------------------------------------------- #

#: transcribed from tests/test_layout_policy_restore.py:557-618 — the mutation,
#: the code the pinned matrix expects from the four POLICY endpoints, and what
#: the READ authority decides. Two rows are NOT read decisions: they need the
#: catalogue centerline and a REBUILT policy, which stay in
#: ``_selected_candidate_policy`` (Stage B §14 Q1) — the read defers (VALID)
#: and never RECLASSIFIES them (A13).
SELECTION_TAMPERS: tuple[tuple[str, str, str, str | None], ...] = (
    ("bump_bound", "LAYOUT_V2_CLEARANCE_MISMATCH", "VALID", None),
    ("stale_revision", "LAYOUT_V2_SELECTION_STALE", "STALE", "LAYOUT_V2_SELECTION_STALE"),
    ("null_clearance", "LAYOUT_V2_CLEARANCE_MISMATCH", "MALFORMED", "LAYOUT_V2_CLEARANCE_MISMATCH"),
    ("list_clearance", "LAYOUT_V2_CLEARANCE_MISMATCH", "MALFORMED", "LAYOUT_V2_CLEARANCE_MISMATCH"),
    ("str_bound", "LAYOUT_V2_CLEARANCE_MISMATCH", "MALFORMED", "LAYOUT_V2_CLEARANCE_MISMATCH"),
    ("str_required", "LAYOUT_V2_CLEARANCE_MISMATCH", "MALFORMED", "LAYOUT_V2_CLEARANCE_MISMATCH"),
    (
        "list_refinement",
        "LAYOUT_V2_CLEARANCE_MISMATCH",
        "MALFORMED",
        "LAYOUT_V2_CLEARANCE_MISMATCH",
    ),
    (
        "no_candidate_id",
        "LAYOUT_V2_CLEARANCE_MISMATCH",
        "MALFORMED",
        "LAYOUT_V2_CLEARANCE_MISMATCH",
    ),
    ("unknown_candidate", "LAYOUT_V2_CLEARANCE_MISMATCH", "VALID", None),
)


def _tamper(document: dict[str, Any], mutation: str) -> dict[str, Any]:
    doc = json.loads(json.dumps(document))
    if mutation == "bump_bound":
        doc["clearance"]["clearanceErrorBound"] = (
            doc["clearance"]["clearanceErrorBound"] or 0.0
        ) + 1e-3
    elif mutation == "stale_revision":
        doc["layoutRevision"] = "0000000000000000"
    elif mutation == "null_clearance":
        doc["clearance"] = None
    elif mutation == "list_clearance":
        doc["clearance"] = []
    elif mutation == "str_bound":
        doc["clearance"]["clearanceErrorBound"] = "abc"
    elif mutation == "str_required":
        doc["clearance"]["requiredClearance"] = "abc"
    elif mutation == "list_refinement":
        doc["clearance"]["refinement"] = ["x"]
    elif mutation == "no_candidate_id":
        doc.pop("candidateId")
    elif mutation == "unknown_candidate":
        doc["candidateId"] = "NO-SUCH-CANDIDATE"
    else:  # pragma: no cover - the table is closed
        raise AssertionError(mutation)
    return doc


@pytest.mark.parametrize(
    ("mutation", "pinned_code", "state", "code"),
    SELECTION_TAMPERS,
    ids=[row[0] for row in SELECTION_TAMPERS],
)
def test_selection_order_is_revision_then_certification(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
    mutation: str,
    pinned_code: str,
    state: str,
    code: str | None,
) -> None:
    _, reader, derived = stack
    pristine = json.loads((derived / LAYOUT_V2_SELECTED_ARTIFACT).read_text(encoding="utf-8"))
    write_json(derived / LAYOUT_V2_SELECTED_ARTIFACT, _tamper(pristine, mutation))
    read = reader.read(
        reader.snapshot(SID, [LAYOUT_V2_SELECTED_ARTIFACT, LAYOUT_V2_ARTIFACT]),
        LAYOUT_V2_SELECTED_ARTIFACT,
    )
    assert read.state == state, (mutation, read.state, read.error)
    if code is None:
        assert read.error is None
    else:
        assert type(read.error).code == code, (mutation, read.error)
        # A13: the generic ARTIFACT_MALFORMED never overwrites a pinned
        # certification / selection failure
        assert code == pinned_code


def test_level_accesses_order_mirrors_the_selection(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    """A1's fixed order, mirrored for the co-published half: a document that is
    BOTH bound to a foreign catalogue revision AND certification-defective
    reads STALE ``LAYOUT_V2_SELECTION_STALE`` — exactly what the SELECTION
    answers for the same pair of defects — never the certification code."""
    _, reader, derived = stack
    pristine = json.loads((derived / LEVEL_ACCESSES_ARTIFACT).read_text(encoding="utf-8"))

    def read_accesses() -> Any:
        return reader.read(
            reader.snapshot(
                SID,
                [LEVEL_ACCESSES_ARTIFACT, LAYOUT_V2_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT],
            ),
            LEVEL_ACCESSES_ARTIFACT,
        )

    # certification defect ALONE stays the pinned AC-01D code (A13)
    with mutated(derived / LEVEL_ACCESSES_ARTIFACT):
        document = json.loads(json.dumps(pristine))
        document["clearanceErrorBound"] = "abc"
        write_json(derived / LEVEL_ACCESSES_ARTIFACT, document)
        read = read_accesses()
        assert read.state == "MALFORMED", read.error
        assert type(read.error).code == "LAYOUT_V2_CLEARANCE_MISMATCH", read.error
    assert_reads_valid(reader, LEVEL_ACCESSES_ARTIFACT)

    # BOTH defects: the revision check wins, exactly as it does for the selection
    for selection_too in (False, True):
        paths = [derived / LEVEL_ACCESSES_ARTIFACT]
        if selection_too:
            paths.append(derived / LAYOUT_V2_SELECTED_ARTIFACT)
        with mutated(paths[0]), mutated(paths[-1]):
            document = json.loads(json.dumps(pristine))
            document["layoutRevision"] = "0000000000000000"
            document["clearanceErrorBound"] = "abc"
            write_json(derived / LEVEL_ACCESSES_ARTIFACT, document)
            if selection_too:
                selection = json.loads(
                    (derived / LAYOUT_V2_SELECTED_ARTIFACT).read_text(encoding="utf-8")
                )
                selection["layoutRevision"] = "0000000000000000"
                selection["clearance"]["clearanceErrorBound"] = "abc"
                write_json(derived / LAYOUT_V2_SELECTED_ARTIFACT, selection)
                mirror = reader.read(
                    reader.snapshot(SID, [LAYOUT_V2_SELECTED_ARTIFACT, LAYOUT_V2_ARTIFACT]),
                    LAYOUT_V2_SELECTED_ARTIFACT,
                )
                assert mirror.state == "STALE"
                assert type(mirror.error).code == "LAYOUT_V2_SELECTION_STALE", mirror.error
            read = read_accesses()
            assert read.state == "STALE", (selection_too, read.state, read.error)
            assert type(read.error).code == "LAYOUT_V2_SELECTION_STALE", read.error
        assert_reads_valid(reader, LEVEL_ACCESSES_ARTIFACT)
        assert_reads_valid(reader, LAYOUT_V2_SELECTED_ARTIFACT)

    # and the declared ORDER is the selection's, one for one
    assert [c.__name__ for c in READ_SPECS[LEVEL_ACCESSES_ARTIFACT].checks][:2] == [
        "_accesses_revision_check",
        "_accesses_certification_check",
    ]
    assert [c.__name__ for c in READ_SPECS[LAYOUT_V2_SELECTED_ARTIFACT].checks][:2] == [
        "_selection_revision_check",
        "_selection_certification_check",
    ]


def test_a_selection_missing_its_layout_revision_is_stale_not_malformed(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    """A1, verbatim: ``selected.get("layoutRevision") != layout_rev``
    (design_service.py:751) — a MISSING key counts as a mismatch."""
    _, reader, derived = stack
    document = json.loads((derived / LAYOUT_V2_SELECTED_ARTIFACT).read_text(encoding="utf-8"))
    document.pop("layoutRevision")
    write_json(derived / LAYOUT_V2_SELECTED_ARTIFACT, document)
    read = reader.read(
        reader.snapshot(SID, [LAYOUT_V2_SELECTED_ARTIFACT, LAYOUT_V2_ARTIFACT]),
        LAYOUT_V2_SELECTED_ARTIFACT,
    )
    assert read.state == "STALE" and isinstance(read.error, LayoutSelectionStaleError)


#: A12, the artifacts whose persisted ``sourceRevision`` this reader must NOT
#: treat as a freshness token. Stage A §4.5 proved why: that field is
#: ``sha256(fingerprint.entries)`` over the registry's ORDERED input list, and
#: the EFFECTIVE_RAMP group expands to the INACTIVE owner's files — so a
#: legitimate legacy re-run under LAYOUT_V2 changes the recomputed hash while
#: every artifact stays correct (measured: ``network e5fb… → e1c3…``). A hash
#: cannot be source-filtered, so "persisted ≠ recomputed" is a NORMAL state.
SOURCE_REVISION_BEARING: tuple[str, ...] = (
    LEVELS_ARTIFACT,
    SHAFTS_ARTIFACT,
    STOPES_ARTIFACT,
    TIMELINE_ARTIFACT,
    NETWORK_ARTIFACT,
    CAPABILITY_GRAPH_ARTIFACT,
    COMMUNICATION_ARTIFACT,
    SENSORS_ARTIFACT,
)


def test_source_revision_is_never_a_freshness_authority(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    """T12 / A12 — CONTRACT: ``sourceRevision`` is not a generic freshness
    token and is never compared to a recomputed fingerprint. Freshness rests
    ONLY on the provenance relations that exist on disk: a persisted UPSTREAM
    FILE revision (``shafts.levelsRevision`` ↔ ``levels.json``,
    ``capabilityGraph.networkRevision`` ↔ ``network.json``,
    ``layout_v2_selected.layoutRevision`` ↔ ``layout_v2.json``), the
    co-published selection ↔ level-access agreement, the development mesh's
    recorded ramp source, and the GLB content hash. Where persisted evidence
    cannot prove freshness, this reader claims nothing — no evidence is not
    the same as fresh, and it is not permission to invent a rule.

    Proof: replacing the field with garbage changes NO read state."""
    _, reader, derived = stack
    for name in SOURCE_REVISION_BEARING:
        with mutated(derived / name):
            document = json.loads((derived / name).read_text(encoding="utf-8"))
            assert document["sourceRevision"] == "src", name
            document["sourceRevision"] = "GARBAGE-NOT-A-REVISION"
            write_json(derived / name, document)
            read_spec = READ_SPECS[name]
            snapshot = reader.snapshot(SID, [name, *read_spec.provenance_inputs], glb_bytes=True)
            read = reader.read(snapshot, name)
            assert read.state == "VALID", (name, read.state, read.error)
            assert read.raw is not None
            assert read.raw["sourceRevision"] == "GARBAGE-NOT-A-REVISION"
        assert_reads_valid(reader, name)


def test_the_co_published_pair_compares_its_own_identity_not_a_recomputation(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    """The ONE place a ``sourceRevision`` IS read is the rule-157 pair: the
    selection and the level accesses are written under ONE capture, so the
    two halves must carry the SAME value. That is an AGREEMENT between two
    persisted documents, never a comparison against a recomputed hash —
    replacing the value in BOTH halves keeps both VALID."""
    _, reader, derived = stack
    selection = json.loads((derived / LAYOUT_V2_SELECTED_ARTIFACT).read_text(encoding="utf-8"))
    accesses = json.loads((derived / LEVEL_ACCESSES_ARTIFACT).read_text(encoding="utf-8"))
    with mutated(derived / LAYOUT_V2_SELECTED_ARTIFACT), mutated(derived / LEVEL_ACCESSES_ARTIFACT):
        selection["sourceRevision"] = "GARBAGE-NOT-A-REVISION"
        accesses["sourceRevision"] = "GARBAGE-NOT-A-REVISION"
        write_json(derived / LAYOUT_V2_SELECTED_ARTIFACT, selection)
        write_json(derived / LEVEL_ACCESSES_ARTIFACT, accesses)
        names = [LAYOUT_V2_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT, LEVEL_ACCESSES_ARTIFACT]
        snapshot = reader.snapshot(SID, names)
        for name in (LAYOUT_V2_SELECTED_ARTIFACT, LEVEL_ACCESSES_ARTIFACT):
            read = reader.read(snapshot, name)
            assert read.state == "VALID", (name, read.state, read.error)
        # and ONE half alone is the crash residue the pair check exists for
        accesses["sourceRevision"] = "ONLY-ONE-HALF"
        write_json(derived / LEVEL_ACCESSES_ARTIFACT, accesses)
        snapshot = reader.snapshot(SID, names)
        read = reader.read(snapshot, LEVEL_ACCESSES_ARTIFACT)
        assert read.state == "STALE" and isinstance(read.error, LayoutSelectionStaleError)
    assert_reads_valid(reader, LAYOUT_V2_SELECTED_ARTIFACT)
    assert_reads_valid(reader, LEVEL_ACCESSES_ARTIFACT)


# --------------------------------------------------------------------------- #
# require / optional / ramp source
# --------------------------------------------------------------------------- #


def test_require_guard_order_is_scenario_world_uncommitted_absent_malformed(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    store, reader, derived = stack
    with pytest.raises(ScenarioNotFoundError):
        reader.require("no-such-scenario", LEVELS_ARTIFACT)

    (derived / LEVELS_ARTIFACT).write_text("{", encoding="utf-8")
    store.arrays_path(SID).unlink()
    with pytest.raises(WorldNotGeneratedError):
        reader.require(SID, LEVELS_ARTIFACT)  # world guard BEFORE the artifact
    store.arrays_path(SID).write_bytes(b"npz")
    # AC-01F.2 correction: the re-created arrays.npz is a NEW rule-60 revision,
    # so the record no longer commits it — the third rung, between the absent
    # world and the artifact's own states, and still BEFORE the malformed
    # artifact is even looked at
    with pytest.raises(WorldPublicationStaleError):
        reader.require(SID, LEVELS_ARTIFACT)
    write_world_record(store)
    with pytest.raises(ArtifactMalformedError):
        reader.require(SID, LEVELS_ARTIFACT)
    (derived / LEVELS_ARTIFACT).unlink()
    from minegen.services.artifact_errors import LevelsNotGeneratedError

    with pytest.raises(LevelsNotGeneratedError):
        reader.require(SID, LEVELS_ARTIFACT)
    assert reader.optional(SID, LEVELS_ARTIFACT) is None


def test_require_returns_the_typed_model_and_the_raw_document(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    _, reader, derived = stack
    read = reader.require(SID, LEVELS_ARTIFACT)
    assert read.state == "VALID" and read.model is not None
    assert read.raw == json.loads((derived / LEVELS_ARTIFACT).read_text(encoding="utf-8"))


def test_ramp_source_absent_is_legacy_and_malformed_raises(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    _, reader, derived = stack
    assert reader.resolve_ramp_source(reader.snapshot(SID, [RAMP_SOURCE_FILE])) == "LEGACY"
    write_json(derived / RAMP_SOURCE_FILE, {"activeSource": "LAYOUT_V2"})
    assert reader.resolve_ramp_source(reader.snapshot(SID, [RAMP_SOURCE_FILE])) == "LAYOUT_V2"
    (derived / RAMP_SOURCE_FILE).unlink()
    assert reader.resolve_ramp_source(reader.snapshot(SID, [RAMP_SOURCE_FILE])) == "LEGACY"
    (derived / RAMP_SOURCE_FILE).write_text("{", encoding="utf-8")
    with pytest.raises(ArtifactMalformedError):
        reader.resolve_ramp_source(reader.snapshot(SID, [RAMP_SOURCE_FILE]))
    write_json(derived / RAMP_SOURCE_FILE, {"activeSource": "SOMETHING_ELSE"})
    with pytest.raises(ArtifactMalformedError):
        reader.resolve_ramp_source(reader.snapshot(SID, [RAMP_SOURCE_FILE]))


# --------------------------------------------------------------------------- #
# the snapshot boundary
# --------------------------------------------------------------------------- #


def test_snapshot_is_taken_under_the_store_lock(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    """The pattern of tests/test_layout_policy_restore.py:629-682, retargeted:
    a writer holding the per-scenario lock blocks the snapshot."""
    store, reader, _ = stack
    lock = store.lock(SID)
    lock.acquire()
    done = threading.Event()
    captured: dict[str, Any] = {}

    def read_snapshot() -> None:
        captured["snapshot"] = reader.snapshot(SID)
        done.set()

    try:
        thread = threading.Thread(target=read_snapshot, daemon=True)
        thread.start()
        assert not done.wait(0.75), "the snapshot was taken while a writer held the lock"
    finally:
        lock.release()
    assert done.wait(30), "the snapshot never completed after the writer released the lock"
    assert set(captured["snapshot"].files) >= set(READ_SPECS)


def test_snapshot_expectations_fail_closed(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    from minegen.services.artifact_errors import ReadSnapshotChangedError

    store, reader, _ = stack
    snapshot = reader.snapshot(SID, [])
    reader.snapshot(
        SID,
        [],
        expect_scenario_revision=snapshot.scenario_revision,
        expect_arrays_revision=snapshot.arrays_revision,
    )
    bump_mtime(store.scenario_path(SID))
    with pytest.raises(ReadSnapshotChangedError):
        reader.snapshot(SID, [], expect_scenario_revision=snapshot.scenario_revision)
    bump_mtime(store.arrays_path(SID))
    with pytest.raises(ReadSnapshotChangedError):
        reader.snapshot(SID, [], expect_arrays_revision=snapshot.arrays_revision)


def test_read_never_touches_the_file_system(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, reader, _ = stack
    snapshot = reader.snapshot(SID, glb_bytes=True)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("read() touched the file system")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "stat", forbidden)
    monkeypatch.setattr(Path, "is_file", forbidden)
    monkeypatch.setattr(Path, "exists", forbidden)
    for name in READ_SPECS:
        assert reader.read(snapshot, name).state == "VALID", name


def test_snapshot_observes_both_files_of_a_two_file_unit(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    _, reader, _ = stack
    snapshot = reader.snapshot(SID)
    for glb in (TUNNEL_MESH_GLB, DEVELOPMENT_MESH_GLB):
        obs = snapshot.observation(glb)
        assert obs is not None and obs.present
        assert obs.data is None, "a GLB is stat-only unless the bytes are requested"
    assert reader.snapshot(SID, glb_bytes=True).files[TUNNEL_MESH_GLB].data == GLB_BYTES


# --------------------------------------------------------------------------- #
# public-detail hygiene and layering
# --------------------------------------------------------------------------- #


def test_no_read_error_message_carries_a_filesystem_path(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    store, reader, derived = stack
    messages: list[str] = []
    for name in READ_SPECS:
        with mutated(derived / name):
            (derived / name).write_text("{", encoding="utf-8")
            read = reader.read(
                reader.snapshot(SID, [name, *READ_SPECS[name].provenance_inputs]), name
            )
            assert read.error is not None
            messages.append(str(read.error))
        assert_reads_valid(reader, name)
    root = str(store.root)
    assert len(messages) == len(READ_SPECS)
    for message in messages:
        # no absolute path (the store root, the derived dir, the tmp prefix),
        # no traceback, no exception repr — the public detail names FILES only
        assert root not in message, message
        assert str(derived) not in message, message
        assert "/scenarios/" not in message, message
        assert not re.search(r"(?<![\w…])/(?:tmp|home|var|usr|private)\b", message), message
        assert "Traceback" not in message and "object at 0x" not in message, message


def test_the_reader_imports_no_service_it_will_be_consumed_by() -> None:
    """Stage B §8.1: ``artifact_reader`` imports NOTHING from
    ``design_service`` / ``world_service`` / ``effective_ramp`` — those import
    IT in commit 2, and a cycle would be the F05 pattern reborn."""
    source = Path("src/minegen/services/artifact_reader.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    forbidden = {
        "minegen.services.design_service",
        "minegen.services.world_service",
        "minegen.services.effective_ramp",
        "minegen.services.infrastructure_service",
    }
    assert not (modules & forbidden), sorted(modules & forbidden)
    assert "minegen.core.artifact_registry" in modules


# --------------------------------------------------------------------------- #
# Stage D S1 — "present but unreadable" is never a SKIPPED provenance check
# --------------------------------------------------------------------------- #


def test_an_unreadable_ramp_source_makes_the_development_mesh_malformed(
    stack: tuple[ScenarioStore, ArtifactReader, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """S1. ``_development_mesh_source_check`` used to ``return None`` when
    ``ramp_source.json`` was PRESENT but its bytes could not be read — the one
    observation the reader classifies MALFORMED for the artifact's own read
    and the ``_accesses_pair_check`` treats as an unusable half. A skipped
    provenance check is not a deferral to another artifact's report: nobody
    reports it, and the mesh is SERVED.

    Unreadable and unparseable are one outcome now, and it names
    ``ramp_source.json`` — the file the defect belongs to."""
    _, reader, _derived = stack
    original = Path.read_bytes

    def patched(self: Path) -> bytes:
        if self.name == RAMP_SOURCE_FILE:
            raise PermissionError(self.name)
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", patched)
    snapshot = reader.snapshot(SID, [DEVELOPMENT_MESH_ARTIFACT, RAMP_SOURCE_FILE])
    source_obs = snapshot.observation(RAMP_SOURCE_FILE)
    assert source_obs is not None
    # the observation really is "present, bytes unreadable" — never ABSENT
    assert source_obs.present and source_obs.data is None

    read = reader.read(snapshot, DEVELOPMENT_MESH_ARTIFACT)
    assert read.state == "MALFORMED", read.state
    assert isinstance(read.error, ArtifactMalformedError)
    assert read.error.artifact == RAMP_SOURCE_FILE, read.error.artifact
    # and the source's own read agrees, from the SAME observation
    assert reader.read(snapshot, RAMP_SOURCE_FILE).state == "MALFORMED"
    monkeypatch.undo()
    assert_reads_valid(reader, DEVELOPMENT_MESH_ARTIFACT)


# --------------------------------------------------------------------------- #
# Stage D C5 / C6 — the pair, in the SELECTION's direction, on the unit level
# --------------------------------------------------------------------------- #


def test_the_selection_reports_its_co_published_half(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    """C5/C6 on the read spec itself. Every row is a state the two-write
    publish window of ``select_layout_candidate`` can leave behind, and each
    one names the OUTCOME of the SELECTION's read — the direction that had no
    check at all.

    C6's labels: a defect of an artifact's OWN certification block is
    MALFORMED; a disagreement between two parseable halves, or a co-published
    half that is missing / not usable / certification-defective, is STALE."""
    _, reader, derived = stack
    accesses_path = derived / LEVEL_ACCESSES_ARTIFACT
    layout_revision = expected_revision(derived / LAYOUT_V2_ARTIFACT)
    names = [LAYOUT_V2_SELECTED_ARTIFACT, LAYOUT_V2_ARTIFACT, LEVEL_ACCESSES_ARTIFACT]

    def read_selection() -> Any:
        return reader.read(reader.snapshot(SID, names), LAYOUT_V2_SELECTED_ARTIFACT)

    def accesses_with(**changes: Any) -> dict[str, Any]:
        return {**_accesses(layout_revision), **changes}

    with mutated(accesses_path):
        # 1. the half is GONE
        accesses_path.unlink()
        read = read_selection()
        assert read.state == "STALE" and type(read.error).code == "LAYOUT_V2_SELECTION_STALE"
        assert LEVEL_ACCESSES_ARTIFACT in str(read.error)

        # 2. the half is not a usable document
        for junk in ("{", json.dumps([1, 2]), json.dumps("text")):
            accesses_path.write_text(junk, encoding="utf-8")
            read = read_selection()
            assert read.state == "STALE", junk
            assert type(read.error).code == "LAYOUT_V2_SELECTION_STALE", junk

        # 3. capture-revision disagreement → a freshness fact
        for field_name in ("sourceRevision", "layoutRevision"):
            write_json(accesses_path, accesses_with(**{field_name: "0000000000000000"}))
            read = read_selection()
            assert read.state == "STALE", field_name
            assert type(read.error).code == "LAYOUT_V2_SELECTION_STALE", field_name

        # 4. candidate identity / clearance RECIPE → A1's third row, the
        #    pinned AC-01D code. ``requiredClearance`` is C6's addition: it is
        #    the fourth key ``CandidateCertification`` parses and the pair
        #    check compared only the first three.
        for changes in (
            {"candidateId": "OTHER-CANDIDATE"},
            {"clearanceBasis": "COARSE_CONSERVATIVE"},
            {"clearanceErrorBound": (CLEARANCE_BOUND or 0.0) + 1e-3},
            {"clearanceRefinement": {"factor": 2}},
            {"requiredClearance": REQUIRED_CLEARANCE + 1e-3},
        ):
            write_json(accesses_path, accesses_with(**changes))
            read = read_selection()
            assert read.state == "STALE", changes
            assert type(read.error).code == "LAYOUT_V2_CLEARANCE_MISMATCH", changes

        # 5. the co-published half's OWN certification block is defective:
        #    STALE here, and this row never carries the other artifact's text
        broken = accesses_with()
        broken.pop("clearanceBasis")
        write_json(accesses_path, broken)
        read = read_selection()
        assert read.state == "STALE"
        assert type(read.error).code == "LAYOUT_V2_CLEARANCE_MISMATCH"
        assert "co-published" in str(read.error) and LEVEL_ACCESSES_ARTIFACT in str(read.error)
        # while the accesses' OWN read calls the same defect MALFORMED
        own = reader.read(reader.snapshot(SID, names), LEVEL_ACCESSES_ARTIFACT)
        assert own.state == "MALFORMED"
        assert type(own.error).code == "LAYOUT_V2_CLEARANCE_MISMATCH"
    assert_reads_valid(reader, LAYOUT_V2_SELECTED_ARTIFACT)


def test_a_defective_selection_certification_is_not_reported_by_the_accesses_row(
    stack: tuple[ScenarioStore, ArtifactReader, Path],
) -> None:
    """S14 / C6. With the SELECTION's ``clearance`` block null, the
    ``level_accesses.json`` row used to come back ``state=MALFORMED`` carrying
    the SELECTION's own message — a failed shape precondition of a document
    whose shape is fine, and one artifact reporting another's defect. It is
    STALE, with its own text, and the wire code is unchanged."""
    _, reader, derived = stack
    selection = derived / LAYOUT_V2_SELECTED_ARTIFACT
    names = [LEVEL_ACCESSES_ARTIFACT, LAYOUT_V2_ARTIFACT, LAYOUT_V2_SELECTED_ARTIFACT]
    with mutated(selection):
        document = json.loads(selection.read_text(encoding="utf-8"))
        document["clearance"] = None
        write_json(selection, document)
        accesses_read = reader.read(reader.snapshot(SID, names), LEVEL_ACCESSES_ARTIFACT)
        assert accesses_read.state == "STALE"
        assert type(accesses_read.error).code == "LAYOUT_V2_CLEARANCE_MISMATCH"
        assert "co-published" in str(accesses_read.error)
        assert LAYOUT_V2_SELECTED_ARTIFACT in str(accesses_read.error)
        # the selection's OWN block defect stays MALFORMED, on its own row
        own = reader.read(reader.snapshot(SID, names), LAYOUT_V2_SELECTED_ARTIFACT)
        assert own.state == "MALFORMED"
        assert type(own.error).code == "LAYOUT_V2_CLEARANCE_MISMATCH"
    assert_reads_valid(reader, LEVEL_ACCESSES_ARTIFACT)
