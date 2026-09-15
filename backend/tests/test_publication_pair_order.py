"""AC-01F.2 D5.4 — the three paired publications, and what a crash between
their two atomic replacements leaves.

Two ``os.replace`` are not one atomic pair. The read-side checks (AC-01F
C5: GLB presence + content hash, the rule-157 selection/accesses pair
check) stay the durable answer; the ORDER is what decides which of the two
half-states a reader has to classify, and D3 fixes it so the surviving
state is always the one the reader classifies MOST conservatively:

    report + GLB (tunnel, development mesh), SUCCESS
        GLB FIRST → a crash leaves a GLB with no report → the artifact is
        ABSENT (a stray GLB no reader looks up; the next publish overwrites
        it), never a SUCCESS report whose GLB is missing (ARTIFACT_MALFORMED)

    report + GLB, FAILED (``result.glb is None``)
        the OTHER order, and deliberately so: the FAILED report is published
        FIRST and only then is the stale GLB unlinked. Unlinking first would
        open a window in which a failing report publish leaves the PREVIOUS
        SUCCESS report beside no GLB — exactly the ARTIFACT_MALFORMED half the
        SUCCESS order exists to avoid, and a 200 scene turned into a 409.
        Report-then-unlink leaves at worst a FAILED report beside a stale GLB,
        which the reader refuses on the binary route and serves as FAILED on
        the report route.

    selection + level accesses
        level_accesses.json FIRST → a crash leaves accesses with no
        selection → LAYOUT_V2_NOT_SELECTED on the selection and the typed
        forward orphan LAYOUT_V2_SELECTION_STALE on the accesses, repaired
        by the explicit re-selection, never a selection whose accesses are
        missing (Stage A §7.4 R1: that one was served 200 by four routes and
        surfaced only two builders later as a 79.76 m weld error)

    arrays.npz + derived/world.json
        arrays.npz FIRST and the world COMMIT RECORD LAST (AC-01F.2
        correction): the record's publication IS the commit point, so a crash
        between them leaves an UNCOMMITTED generation — typed 409
        WORLD_PUBLICATION_STALE — where it used to leave a world that was
        served 200 with nothing on disk attesting to it

Each case is a FIRST generation of the pair (nothing of it on disk), with a
hook that raises between the two publishes, and each asserts the state AND
the reader's classification of it. The counterfactual — the state the
OPPOSITE order would have left — is asserted beside it, so "the order
matters" is measured, not claimed.

SCOPE, stated exactly. The ORDER above is about the FIRST publication of a
pair. The RE-publication case was AC-01F.2's declared route-local trade-off
— ``_glb_check`` hashes the GLB against the report's ``artifactRevision``
only where the snapshot captured its BYTES, so the binary route answered
409 ``ARTIFACT_MALFORMED`` while the report route and the scene answered
**200** for the stale-but-present half — and the AC-01F.2 CORRECTION (B3)
closes it: each mesh pair now commits itself with an INTERNAL sidecar
(``core/mesh_record``) published LAST, naming the report and GLB revisions
its own publication installed, so every surface refuses a mixed generation
typed. That matters more than it sounds: the mesh build is deterministic,
so a crash between the two installs IDENTICAL GLB bytes and the content
hash AGREES — without the publication identity the mixture is invisible on
every route, including the binary one. For the selection pair the
re-publication case was never symmetric: the accesses land first either way
under D3, so the selection is the half that can be one generation behind,
and the rule-157 pair check in its READ SPEC classifies that disagreement
(``LAYOUT_V2_SELECTION_STALE``) rather than serving it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from minegen.core import publication
from minegen.core.artifacts import (
    DEVELOPMENT_MESH_ARTIFACT,
    DEVELOPMENT_MESH_GLB,
    LAYOUT_V2_SELECTED_ARTIFACT,
    LEVEL_ACCESSES_ARTIFACT,
    TUNNEL_MESH_ARTIFACT,
    TUNNEL_MESH_GLB,
)
from minegen.core.mesh_record import mesh_commit_name
from minegen.core.revision import file_revision
from minegen.services import design_service, world_service
from tests.test_artifact_read_api import API, Stack, _make_stack


def expected_revision(path: Path) -> str:
    """``file_revision`` of a file that must exist — the comparand the
    report's ``glbRevision`` is checked against (AC-01F.2 correction B3)."""
    revision = file_revision(path)
    assert revision is not None, path.name
    return revision


class PublishHookError(Exception):
    """Raised BETWEEN the two publishes of a pair — the crash, injected at
    the only moment where the order can be observed."""


def _raise_between(
    monkeypatch: pytest.MonkeyPatch, module: Any, function: str, target: str
) -> None:
    """Make ``module.<function>`` raise when it is asked to publish
    ``target``; every other publication of the same writer goes through."""
    real = getattr(module, function)

    def hooked(path: Path, *args: Any, **kwargs: Any) -> None:
        if Path(path).name == target:
            raise PublishHookError(target)
        real(path, *args, **kwargs)

    monkeypatch.setattr(module, function, hooked)


def _generate(stack: Stack, report: str) -> Any:
    """Run the REAL builder for whichever of the two mesh pairs ``report``
    names, so every case in this module starts from the state it needs."""
    if report == TUNNEL_MESH_ARTIFACT:
        return stack.design.generate_tunnel(stack.sid)
    return stack.design.generate_development_mesh(stack.sid)


def _step(stack: Stack, method: str, route: str, **kwargs: Any) -> Any:
    response = stack.client.request(method, f"{API}/{stack.sid}{route}", **kwargs)
    assert response.status_code in (200, 201), (route, response.status_code, response.text[:300])
    return response


# --------------------------------------------------------------------------- #
# report + GLB
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def before_tunnel(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    """LEGACY chain up to the smoothed ramp: the tunnel pair has never been
    published on this scenario."""
    stack, context = _make_stack(tmp_path_factory.mktemp("pair_tunnel"))
    _step(stack, "POST", "/world/generate")
    _step(stack, "POST", "/design/targets")
    _step(stack, "POST", "/design/decline", params={"maxLevels": 2, "sync": "true"})
    _step(stack, "POST", "/design/decline/smooth", params={"sync": "true"})
    _step(stack, "POST", "/design/levels")
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


@pytest.mark.parametrize(
    ("report", "glb", "route", "absent_code"),
    [
        (TUNNEL_MESH_ARTIFACT, TUNNEL_MESH_GLB, "/design/tunnel", "TUNNEL_NOT_GENERATED"),
        (
            DEVELOPMENT_MESH_ARTIFACT,
            DEVELOPMENT_MESH_GLB,
            "/design/development-mesh",
            "DEVELOPMENT_MESH_NOT_GENERATED",
        ),
    ],
)
def test_a_crash_between_glb_and_report_leaves_an_absent_artifact(
    before_tunnel: Stack,
    monkeypatch: pytest.MonkeyPatch,
    report: str,
    glb: str,
    route: str,
    absent_code: str,
) -> None:
    stack = before_tunnel
    derived = stack.derived
    assert not (derived / report).exists() and not (derived / glb).exists()
    _raise_between(monkeypatch, design_service, "publish_text", report)
    with pytest.raises(PublishHookError):
        _generate(stack, report)
    monkeypatch.undo()
    # exactly the D3 state: the GLB is there, the report is not
    assert (derived / glb).is_file()
    assert not (derived / report).exists()
    assert [p.name for p in derived.rglob("*") if ".tmp" in p.name] == []
    # … and the reader calls it ABSENT, on its own route, on the binary route
    # and in the scene — never MALFORMED
    assert stack.get(route) == (409, absent_code)
    assert stack.get(f"{route}/mesh.glb") == (409, absent_code)
    scene = stack.scene()
    assert scene.status_code == 200
    slot = "tunnelMesh" if report == TUNNEL_MESH_ARTIFACT else "developmentMesh"
    assert scene.json()[slot] is None
    # the next publish overwrites the stray GLB and the artifact is whole
    _generate(stack, report)
    assert stack.get(route)[0] == 200
    assert stack.client.get(f"{API}/{stack.sid}{route}/mesh.glb").status_code == 200


@pytest.mark.parametrize(
    ("report", "glb", "route"),
    [
        (TUNNEL_MESH_ARTIFACT, TUNNEL_MESH_GLB, "/design/tunnel"),
        (DEVELOPMENT_MESH_ARTIFACT, DEVELOPMENT_MESH_GLB, "/design/development-mesh"),
    ],
)
def test_the_opposite_order_would_leave_the_malformed_half(
    before_tunnel: Stack, report: str, glb: str, route: str
) -> None:
    """The counterfactual, produced with the Stage A §7.4 R2 recipe (the GLB
    removed from beside a SUCCESS report): report-first would leave THIS —
    a SUCCESS report advertising a ``meshUrl`` and an ``artifactRevision``
    for bytes that are not there. It is ARTIFACT_MALFORMED, not ABSENT, and
    it is the state D3's order makes unreachable."""
    stack = before_tunnel
    derived = stack.derived
    # self-contained: this case needs a COMPLETE SUCCESS pair on disk,
    # whatever the module's other cases left behind
    _generate(stack, report)
    payload = json.loads((derived / report).read_text(encoding="utf-8"))
    assert payload["status"] == "SUCCESS"
    saved = (derived / glb).read_bytes()
    import os

    stat_before = os.stat(derived / glb)
    (derived / glb).unlink()
    try:
        assert stack.get(route) == (409, "ARTIFACT_MALFORMED")
        assert stack.get(f"{route}/mesh.glb") == (409, "ARTIFACT_MALFORMED")
        # the other half of the FAILED-path rationale: the whole scene turns
        # from 200 into 409 on this half-state (measured, not only claimed)
        assert stack.scene().status_code == 409
    finally:
        (derived / glb).write_bytes(saved)
        os.utime(derived / glb, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
    assert stack.get(route)[0] == 200


# --------------------------------------------------------------------------- #
# report + GLB — the FAILED path (the D3 amendment)
# --------------------------------------------------------------------------- #

#: the two mesh pairs, with the module attribute whose builder has to be
#: replaced to reach the ``result.glb is None`` branch and the FAILED result
#: class that branch was written for
FAILED_PAIRS = [
    (TUNNEL_MESH_ARTIFACT, TUNNEL_MESH_GLB, "/design/tunnel", "TunnelMeshBuilder"),
    (
        DEVELOPMENT_MESH_ARTIFACT,
        DEVELOPMENT_MESH_GLB,
        "/design/development-mesh",
        "DevelopmentMeshBuilder",
    ),
]


class _FailedBuilder:
    """Stands in for ``TunnelMeshBuilder`` / ``DevelopmentMeshBuilder`` and
    returns what their own ``_failed`` returns: a FAILED report and
    ``glb=None``. The rest of the writer — fingerprint, lock, payload
    decoration (``sources``, ``artifactRevision = None``) — is the real one."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def build(self, *args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            status="FAILED",
            report={"status": "FAILED", "failureReason": "injected: a FAILED mesh build"},
            glb=None,
        )


def _fail_the_build(monkeypatch: pytest.MonkeyPatch, builder_attr: str) -> None:
    monkeypatch.setattr(design_service, builder_attr, _FailedBuilder)


@pytest.mark.parametrize(("report", "glb", "route", "builder_attr"), FAILED_PAIRS)
def test_a_crash_between_the_failed_report_and_the_unlink_leaves_a_stale_glb(
    before_tunnel: Stack,
    monkeypatch: pytest.MonkeyPatch,
    report: str,
    glb: str,
    route: str,
    builder_attr: str,
) -> None:
    """The FAILED path's own half-state, measured. The report lands first, so
    a crash before the unlink leaves a FAILED report beside a STALE GLB — and
    that is the conservative half: the report route serves the FAILED status
    (the artifact is VALID; ``_glb_check`` applies to SUCCESS reports only)
    and the binary route refuses, because ``DesignService._glb`` demands
    ``status == "SUCCESS"``. What can never be reached from here is a SUCCESS
    report without its GLB."""
    stack = before_tunnel
    derived = stack.derived
    _generate(stack, report)  # a complete SUCCESS pair, self-contained
    stale_glb = (derived / glb).read_bytes()

    _fail_the_build(monkeypatch, builder_attr)
    real_unlink = Path.unlink

    def hooked_unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        if self.name == glb:
            raise PublishHookError(glb)  # the crash, between report and unlink
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", hooked_unlink)
    with pytest.raises(PublishHookError):
        _generate(stack, report)
    monkeypatch.undo()

    # exactly the amended order's state: the FAILED report, and the stale GLB
    assert json.loads((derived / report).read_text(encoding="utf-8"))["status"] == "FAILED"
    assert (derived / glb).read_bytes() == stale_glb
    assert [p.name for p in derived.rglob("*") if ".tmp" in p.name] == []
    # the report route serves the FAILED report; the binary route refuses it
    response = stack.client.get(f"{API}/{stack.sid}{route}")
    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert stack.get(f"{route}/mesh.glb")[0] == 409
    # restore the module fixture to a whole SUCCESS pair
    _generate(stack, report)
    assert stack.get(route)[0] == 200
    assert stack.client.get(f"{API}/{stack.sid}{route}/mesh.glb").status_code == 200


@pytest.mark.parametrize(("report", "glb", "route", "builder_attr"), FAILED_PAIRS)
def test_a_failing_failed_report_publish_leaves_the_previous_success_pair_whole(
    before_tunnel: Stack,
    monkeypatch: pytest.MonkeyPatch,
    report: str,
    glb: str,
    route: str,
    builder_attr: str,
) -> None:
    """Why the FAILED path does NOT unlink first. With the report published
    first, a failing report publish is a complete no-op: the previous SUCCESS
    pair is byte-identical and all three surfaces still answer 200.

    Under the withdrawn unlink-first order the very same crash would have
    left the previous SUCCESS report beside NO GLB — the state
    ``test_the_opposite_order_would_leave_the_malformed_half`` measures as
    409 ARTIFACT_MALFORMED on both routes, and the scene with it."""
    stack = before_tunnel
    derived = stack.derived
    _generate(stack, report)  # a complete SUCCESS pair, self-contained
    report_before = (derived / report).read_bytes()
    glb_before = (derived / glb).read_bytes()

    _fail_the_build(monkeypatch, builder_attr)
    _raise_between(monkeypatch, design_service, "publish_text", report)
    with pytest.raises(PublishHookError):
        _generate(stack, report)
    monkeypatch.undo()

    assert (derived / report).read_bytes() == report_before
    assert (derived / glb).read_bytes() == glb_before
    assert [p.name for p in derived.rglob("*") if ".tmp" in p.name] == []
    response = stack.client.get(f"{API}/{stack.sid}{route}")
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert stack.client.get(f"{API}/{stack.sid}{route}/mesh.glb").status_code == 200
    assert stack.scene().status_code == 200


# --------------------------------------------------------------------------- #
# selection + level accesses
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def before_selection(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    """Catalogue generated, nothing selected."""
    stack, context = _make_stack(tmp_path_factory.mktemp("pair_selection"))
    _step(stack, "POST", "/world/generate")
    _step(stack, "POST", "/design/layout-v2", params={"sync": "true"})
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


def test_a_crash_between_accesses_and_selection_leaves_a_forward_orphan(
    before_selection: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = before_selection
    derived = stack.derived
    winner = json.loads((derived / "layout_v2.json").read_text(encoding="utf-8"))["winnerId"]
    assert not (derived / LAYOUT_V2_SELECTED_ARTIFACT).exists()
    assert not (derived / LEVEL_ACCESSES_ARTIFACT).exists()
    _raise_between(monkeypatch, design_service, "publish_text", LAYOUT_V2_SELECTED_ARTIFACT)
    with pytest.raises(PublishHookError):
        stack.design.select_layout_candidate(stack.sid, winner)
    monkeypatch.undo()
    # exactly the D3 state: the accesses are there, the selection is not
    assert (derived / LEVEL_ACCESSES_ARTIFACT).is_file()
    assert not (derived / LAYOUT_V2_SELECTED_ARTIFACT).exists()
    assert [p.name for p in derived.rglob("*") if ".tmp" in p.name] == []
    # the selection is ABSENT and the accesses are the TYPED forward orphan
    assert stack.get("/design/layout-v2/selected") == (409, "LAYOUT_V2_NOT_SELECTED")
    assert stack.get("/design/level-accesses") == (409, "LAYOUT_V2_SELECTION_STALE")
    # the resolved summary reports the honest "nothing selected" …
    summary = stack.client.get(f"{API}/{stack.sid}/design/ramp-source").json()
    assert summary["layoutV2Available"] is True
    assert summary["layoutV2Selected"] is False
    # … and the scene refuses, naming the level accesses (AC-01F aggregate)
    scene = stack.scene()
    assert scene.status_code == 409
    detail = scene.json()["detail"]
    assert detail["code"] == "SCENE_ARTIFACT_INVALID"
    assert LEVEL_ACCESSES_ARTIFACT in detail["message"]
    # S5: the explicit re-selection repairs BOTH halves
    assert stack.post("/design/layout-v2/select", json={"candidateId": winner})[0] == 200
    assert stack.get("/design/layout-v2/selected")[0] == 200
    assert stack.get("/design/level-accesses")[0] == 200
    assert stack.scene().status_code == 200


def test_a_crash_while_republishing_the_pair_leaves_two_halves_that_disagree(
    before_selection: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The REPUBLISH crash, required by the AC-01F.2 correction architecture
    (Q5) and not covered by the first-publication case above: a selection of
    candidate A exists, candidate B is selected, and the process dies between
    ``level_accesses.json`` (B) and ``layout_v2_selected.json`` (still A).

    Nothing new guards this — the AC-01F C5/C6 pair check already compares
    ``candidateId``, ``sourceRevision``, ``layoutRevision`` and the recorded
    certification BETWEEN the halves, in both directions. What this case adds
    is the PROOF that the check covers a republication and not only a first
    write: ``sourceRevision`` hashes the candidate id, so the surviving halves
    cannot agree, and both reads plus the scene refuse typed. Re-selecting the
    SAME candidate at the SAME catalogue revision is byte-identical in both
    halves, so that mixture is indistinguishable from the committed state and
    is harmless — the control at the end asserts exactly that."""
    stack = before_selection
    derived = stack.derived
    catalogue = json.loads((derived / "layout_v2.json").read_text(encoding="utf-8"))
    winner = catalogue["winnerId"]
    assert stack.post("/design/layout-v2/select", json={"candidateId": winner})[0] == 200
    other = next(
        c["candidateId"]
        for c in catalogue["candidates"]
        if c["status"] == "FEASIBLE" and c["candidateId"] != winner
    )
    selection_a = json.loads((derived / LAYOUT_V2_SELECTED_ARTIFACT).read_text(encoding="utf-8"))
    # activate while the pair is whole: a switch requires a VALID selection, so
    # it cannot be done after the crash
    assert (
        stack.client.put(
            f"{API}/{stack.sid}/design/ramp-source", json={"activeSource": "LAYOUT_V2"}
        ).status_code
        == 200
    )

    _raise_between(monkeypatch, design_service, "publish_text", LAYOUT_V2_SELECTED_ARTIFACT)
    with pytest.raises(PublishHookError):
        stack.design.select_layout_candidate(stack.sid, other)
    monkeypatch.undo()

    # the halves belong to different selections, and say so
    accesses_b = json.loads((derived / LEVEL_ACCESSES_ARTIFACT).read_text(encoding="utf-8"))
    selection_on_disk = json.loads(
        (derived / LAYOUT_V2_SELECTED_ARTIFACT).read_text(encoding="utf-8")
    )
    assert selection_on_disk == selection_a, "the selection publication never happened"
    assert accesses_b["candidateId"] == other != selection_a["candidateId"]
    assert accesses_b["sourceRevision"] != selection_a["sourceRevision"]
    assert [p.name for p in derived.rglob("*") if ".tmp" in p.name] == []

    # every surface refuses, typed, in both directions of the pair — including
    # the ramp, which resolves the selection only under an ACTIVE LAYOUT_V2
    # source (Stage D D4-4: the architecture declared these surfaces and the
    # first draft of this case asserted only the two reads and the scene)
    assert stack.get("/design/layout-v2/selected") == (409, "LAYOUT_V2_SELECTION_STALE")
    assert stack.get("/design/level-accesses") == (409, "LAYOUT_V2_SELECTION_STALE")
    assert stack.get("/design/ramp") == (409, "LAYOUT_V2_SELECTION_STALE")
    scene = stack.scene()
    assert scene.status_code == 409
    assert scene.json()["detail"]["code"] == "SCENE_ARTIFACT_INVALID"
    # the explicit re-selection is the repair
    assert stack.post("/design/layout-v2/select", json={"candidateId": other})[0] == 200
    assert stack.get("/design/layout-v2/selected")[0] == 200
    assert stack.get("/design/level-accesses")[0] == 200

    # the control: re-selecting the SAME candidate republishes both halves
    # byte-identically, so a crash in the same place is not observable
    before = {
        name: (derived / name).read_bytes()
        for name in (LAYOUT_V2_SELECTED_ARTIFACT, LEVEL_ACCESSES_ARTIFACT)
    }
    assert stack.post("/design/layout-v2/select", json={"candidateId": other})[0] == 200
    for name, data in before.items():
        assert (derived / name).read_bytes() == data, name

    # leave the MODULE fixture exactly as it was found: this is the only case
    # that switches the ramp source, and under an active LAYOUT_V2 the
    # ramp-source summary has a different shape, which a later case reads
    assert (
        stack.client.put(
            f"{API}/{stack.sid}/design/ramp-source", json={"activeSource": "LEGACY"}
        ).status_code
        == 200
    )


def test_the_opposite_order_would_leave_a_selection_without_its_accesses(
    before_selection: Stack,
) -> None:
    """The counterfactual, produced with the Stage A §7.4 R1 recipe: a
    selection whose level accesses are missing. Under AC-01F both halves are
    read together, so it is refused — but it is the half D3's order makes
    unreachable in the first place, and it is the one that used to be served
    200 by four routes."""
    stack = before_selection
    derived = stack.derived
    winner = json.loads((derived / "layout_v2.json").read_text(encoding="utf-8"))["winnerId"]
    # self-contained: this case needs a COMPLETE pair on disk, whatever the
    # module's other cases did (selecting the selected candidate at the same
    # revision with both halves VALID is the AC-01D no-op)
    assert stack.post("/design/layout-v2/select", json={"candidateId": winner})[0] == 200
    accesses = derived / LEVEL_ACCESSES_ARTIFACT
    assert (derived / LAYOUT_V2_SELECTED_ARTIFACT).is_file()
    import os

    saved, stat_before = accesses.read_bytes(), os.stat(accesses)
    accesses.unlink()
    try:
        # MEASURED literals: the selection half now claims a selection that
        # its own accesses cannot back (LAYOUT_V2_SELECTION_STALE), and the
        # resolved summary advertises ``layoutV2Selected: true`` — where the
        # D3 order reports ``false`` and points at the repair
        assert stack.get("/design/level-accesses") == (409, "LEVEL_ACCESSES_NOT_GENERATED")
        assert stack.get("/design/layout-v2/selected") == (409, "LAYOUT_V2_SELECTION_STALE")
        summary = stack.client.get(f"{API}/{stack.sid}/design/ramp-source").json()
        assert summary["layoutV2Selected"] is True
        scene = stack.scene()
        assert scene.status_code == 409
        assert LAYOUT_V2_SELECTED_ARTIFACT in scene.json()["detail"]["message"]
    finally:
        accesses.write_bytes(saved)
        os.utime(accesses, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))
    assert stack.get("/design/level-accesses")[0] == 200


# --------------------------------------------------------------------------- #
# arrays.npz + derived/world.json
# --------------------------------------------------------------------------- #


def test_a_crash_between_arrays_and_the_record_is_an_uncommitted_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``arrays.npz`` is published FIRST and ``derived/world.json`` — the
    world COMMIT RECORD — LAST, so its publication is the commit point of the
    generation and a crash between the two leaves a generation that is not
    visible.

    Until the AC-01F.2 CORRECTION this same test asserted the opposite
    ("leaves a usable world"): ``world.json`` was an unread stats snapshot, so
    ``GET …/world`` and ``GET …/scene`` answered **200** for a world nothing on
    disk attested to. That 200 is the B1 defect — the same shape as a NEW
    ``scenario.json`` beside an OLD ``arrays.npz`` — and the 409 below is the
    correction. Nothing about the ORDER changed; what changed is that the
    second file now means something."""
    stack, context = _make_stack(tmp_path / "pair_world")
    try:
        _raise_between(monkeypatch, world_service, "publish_text", "world.json")
        with pytest.raises(PublishHookError):
            stack.worlds.generate(stack.sid)
        monkeypatch.undo()
        stack.worlds._cache.clear()  # a fresh process has no cache either
        root = stack.store.scenario_dir(stack.sid)
        assert (root / "arrays.npz").is_file()
        assert not (root / "derived" / "world.json").exists()
        assert [p.name for p in root.rglob("*") if ".tmp" in p.name] == []
        # the arrays are whole — and that is NOT enough to be a world
        for route in (f"{API}/{stack.sid}/world", f"{API}/{stack.sid}/scene"):
            response = stack.client.get(route)
            assert response.status_code == 409, route
            assert response.json()["detail"]["code"] == "WORLD_PUBLICATION_STALE", route
        # … and a re-generation commits both
        assert stack.client.post(f"{API}/{stack.sid}/world/generate").status_code == 200
        assert (root / "derived" / "world.json").is_file()
        assert stack.client.get(f"{API}/{stack.sid}/world").status_code == 200
    finally:
        context.__exit__(None, None, None)
        stack.jobs.shutdown()


def test_the_pair_order_is_the_one_the_writers_implement() -> None:
    """The order is a property of the SOURCE, not only of these runs: inside
    each writer's own body the co-published file precedes the one D3 names
    second. Read per FUNCTION (``inspect.getsource``), never by searching
    the whole module — three writers spell their publish the same way.

    For the two mesh writers this is the SUCCESS branch; the FAILED branch's
    opposite order is asserted separately below."""
    import inspect

    from minegen.services.design_service import DesignService
    from minegen.services.world_service import WorldService

    for function, first, second in (
        (DesignService.generate_tunnel, "publish_bytes(glb_path", "publish_text(report_path"),
        (
            DesignService.generate_development_mesh,
            "publish_bytes(glb_path",
            "publish_text(report_path",
        ),
        (
            DesignService.select_layout_candidate,
            "publish_text(self.level_accesses_path(scenario_id)",
            "publish_text(path, serialized)",
        ),
        (
            WorldService._save,
            "publish_npz(path, **fields)",
            "publish_text(derived / WORLD_RECORD_FILE",
        ),
    ):
        body = inspect.getsource(function)
        assert first in body and second in body, (function.__qualname__, first, second)
        assert body.index(first) < body.index(second), function.__qualname__


def test_the_failed_branch_publishes_the_report_before_it_unlinks_the_glb() -> None:
    """The amended FAILED order, read from the SOURCE: the LAST
    ``publish_text(report_path`` of each mesh writer — the one in the
    ``result.glb is None`` branch — precedes the ``glb_path.unlink()`` it
    guards."""
    import inspect

    from minegen.services.design_service import DesignService

    for function in (DesignService.generate_tunnel, DesignService.generate_development_mesh):
        body = inspect.getsource(function)
        assert body.count("publish_text(report_path") == 2, function.__qualname__
        assert body.count("glb_path.unlink()") == 1, function.__qualname__
        assert body.rindex("publish_text(report_path") < body.index("glb_path.unlink()"), (
            function.__qualname__
        )


# --------------------------------------------------------------------------- #
# AC-01F.2 CORRECTION (B3) — the report/GLB GENERATION transition matrix
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("report", "glb", "route", "builder_attr"), FAILED_PAIRS)
def test_success_to_success_a_crash_before_the_second_report_is_refused_everywhere(
    before_tunnel: Stack,
    monkeypatch: pytest.MonkeyPatch,
    report: str,
    glb: str,
    route: str,
    builder_attr: str,
) -> None:
    """The B3 case. A COMPLETE pair is republished; the crash lands between
    GLB G2 and report G2, leaving report G1 beside GLB G2.

    Measured on PR #34 HEAD ``57c64a5``: the report route and the scene
    answered **200** for that pair, because ``artifactRevision`` is a CONTENT
    hash and only the binary route captures the bytes to check it. Worse, the
    mesh build is deterministic — G2's bytes equal G1's — so the content hash
    cannot see the mixture AT ALL, on any route. What distinguishes the two
    generations is the PUBLICATION identity, which a stat already has: the
    report's ``glbRevision``. Every surface now refuses typed."""
    stack = before_tunnel
    derived = stack.derived
    _generate(stack, report)  # a complete SUCCESS pair, self-contained
    first = json.loads((derived / report).read_text(encoding="utf-8"))
    assert first["status"] == "SUCCESS"
    assert "glbRevision" not in first, "the public report carries no publication provenance"
    glb_bytes_before = (derived / glb).read_bytes()
    commit = derived / mesh_commit_name(report)
    commit_before = json.loads(commit.read_text(encoding="utf-8"))

    _raise_between(monkeypatch, design_service, "publish_text", report)
    with pytest.raises(PublishHookError):
        _generate(stack, report)
    monkeypatch.undo()

    on_disk = json.loads((derived / report).read_text(encoding="utf-8"))
    assert on_disk == first, "the report is still G1 — its publication never happened"
    assert (derived / glb).read_bytes() == glb_bytes_before, "a deterministic rebuild"
    live_digest = hashlib.sha256((derived / glb).read_bytes()).hexdigest()
    assert on_disk["artifactRevision"] == live_digest, (
        "the CONTENT hash still agrees — it cannot see this mixture"
    )
    assert json.loads(commit.read_text(encoding="utf-8")) == commit_before, (
        "the sidecar is published LAST, so it is still G1's"
    )
    assert commit_before["glbRevision"] != expected_revision(derived / glb), (
        "the PUBLICATION identity in the sidecar is what differs"
    )

    assert stack.get(route) == (409, "ARTIFACT_STALE")
    assert stack.get(f"{route}/mesh.glb") == (409, "ARTIFACT_STALE")
    scene = stack.scene()
    assert scene.status_code == 409
    assert scene.json()["detail"]["code"] == "SCENE_ARTIFACT_INVALID"
    assert any(
        f["artifact"] == report and f["code"] == "ARTIFACT_STALE"
        for f in scene.json()["detail"]["artifacts"]
    ), scene.json()["detail"]

    # a complete republication is the remedy, and restores the module fixture
    _generate(stack, report)
    assert stack.get(route)[0] == 200
    assert stack.client.get(f"{API}/{stack.sid}{route}/mesh.glb").status_code == 200


@pytest.mark.parametrize(("report", "glb", "route", "builder_attr"), FAILED_PAIRS)
def test_success_to_failed_and_back(
    before_tunnel: Stack,
    monkeypatch: pytest.MonkeyPatch,
    report: str,
    glb: str,
    route: str,
    builder_attr: str,
) -> None:
    """The other two transitions. SUCCESS→FAILED: the FAILED report carries
    ``glbRevision: null``, expects no GLB, and the generation check is inert
    on it — a leftover GLB beside a FAILED report is ignored, because no
    surface presents it. FAILED→SUCCESS: the new pair is whole and the report
    names the GLB that was just installed."""
    stack = before_tunnel
    derived = stack.derived
    _generate(stack, report)

    _fail_the_build(monkeypatch, builder_attr)
    _generate(stack, report)
    monkeypatch.undo()
    failed = json.loads((derived / report).read_text(encoding="utf-8"))
    assert failed["status"] == "FAILED"
    assert "glbRevision" not in failed
    failed_commit = json.loads((derived / mesh_commit_name(report)).read_text(encoding="utf-8"))
    assert failed_commit["glbRevision"] is None, "a FAILED publication commits NO GLB"
    assert failed_commit["reportRevision"] == expected_revision(derived / report)
    assert not (derived / glb).exists(), "the FAILED path unlinks the stale GLB after its report"
    response = stack.client.get(f"{API}/{stack.sid}{route}")
    assert response.status_code == 200 and response.json()["status"] == "FAILED"
    assert stack.get(f"{route}/mesh.glb")[0] == 409

    # FAILED → SUCCESS
    _generate(stack, report)
    success = json.loads((derived / report).read_text(encoding="utf-8"))
    assert success["status"] == "SUCCESS"
    assert "glbRevision" not in success
    commit_after = json.loads((derived / mesh_commit_name(report)).read_text(encoding="utf-8"))
    assert commit_after == {
        "reportRevision": expected_revision(derived / report),
        "glbRevision": expected_revision(derived / glb),
    }
    assert stack.get(route)[0] == 200
    assert stack.client.get(f"{API}/{stack.sid}{route}/mesh.glb").status_code == 200
    assert stack.scene().status_code == 200


@pytest.mark.parametrize(("report", "glb", "route", "builder_attr"), FAILED_PAIRS)
def test_the_report_names_the_glb_its_own_publication_installed(
    before_tunnel: Stack,
    monkeypatch: pytest.MonkeyPatch,
    report: str,
    glb: str,
    route: str,
    builder_attr: str,
) -> None:
    """Stage D D2-1: the B3 identity must come from the RETURN VALUE of
    ``publish_bytes`` — the temp file's own ``os.fstat`` — never from a stat of
    the GLB path after the write.

    MEASURED before this case: replacing the call site with
    ``payload["glbRevision"] = file_revision(glb_path)`` survived all 289 tests
    of the publication and reader suites, because in a quiet process the two
    values agree. The hook below is the same interleaving MP4 stalls a real
    second process into, applied to the GLB: a foreign generation takes the
    path between our ``os.replace`` and anything we could stat afterwards. A
    post-hoc stat then records the INTRUDER's identity, the reader finds
    agreement, and the mixed pair reads 200."""
    stack = before_tunnel
    derived = stack.derived
    intruder = b"glTF" + b"\x00" * 64  # a foreign generation at the GLB path
    fired: list[str] = []
    real_fsync = publication._fsync_directory

    def intrude(directory: Path) -> None:
        real_fsync(directory)
        target = derived / glb
        if not fired and target.is_file():
            fired.append(glb)
            target.write_bytes(intruder)

    monkeypatch.setattr(publication, "_fsync_directory", intrude)
    payload = _generate(stack, report)
    monkeypatch.undo()

    assert fired == [glb], "the hook must fire exactly once, on the GLB publication"
    assert (derived / glb).read_bytes() == intruder
    assert "glbRevision" not in payload, "the public payload carries no provenance"
    commit = json.loads((derived / mesh_commit_name(report)).read_text(encoding="utf-8"))
    assert commit["glbRevision"] != expected_revision(derived / glb), (
        "the sidecar recorded a POST-HOC stat of the GLB path: it names the intruder's "
        "file, not the bytes this publication installed"
    )
    # and because it names OUR bytes, every surface sees the mixture
    assert stack.get(route) == (409, "ARTIFACT_STALE")
    assert stack.scene().status_code == 409

    _generate(stack, report)  # restore the module fixture
    assert stack.get(route)[0] == 200
