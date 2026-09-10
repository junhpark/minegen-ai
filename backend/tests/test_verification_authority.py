"""AC-01A: what a verification run is evidence FOR.

Before AC-01A the persisted summary set ``fullAuthority = (mode == "full" and
not failed)``. That expression cannot distinguish a complete clean release run
from (a) a ``--backend-only`` run whose frontend gates never executed, (b) a
run over a dirty working tree, (c) a run whose source changed underneath it,
or (d) a run whose collection-coverage proof was missing — every one of which
was reported as release authority. These tests pin the corrected judgement:
the FULL tier, every required gate PASSED, the pytest command actually
UNFILTERED, the coverage proof satisfied, over one clean revision held from
the first gate to the last.

Pure logic over synthetic step lists — no gate, threshold or test is relaxed
here, and nothing engineering is judged. FAST tier by construction.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "scripts" / "verify.py"


def _load_verify():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("verify_authority_under_test", VERIFY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verify = _load_verify()


def _steps(names: list[str], failing: set[str] | None = None) -> list[dict[str, Any]]:
    failing = failing or set()
    out = []
    for name in names:
        command = "python -m pytest -q" if name.startswith("pytest") else f"tool {name}"
        out.append(
            {
                "name": name,
                "command": command,
                "status": "FAIL" if name in failing else "PASS",
                "exitCode": 1 if name in failing else 0,
            }
        )
    return out


ALL_GATES = list(verify.RELEASE_BACKEND_GATES) + list(verify.RELEASE_FRONTEND_GATES)
CLEAN_SOURCE = {
    "startHead": "a" * 40,
    "endHead": "a" * 40,
    "startDirty": False,
    "endDirty": False,
    "startDigest": "deadbeefdeadbeef",
    "endDigest": "deadbeefdeadbeef",
    "unchanged": True,
}
GOOD_COVERAGE = {
    "collectedAll": 604,
    "collectedFull": 604,
    "executedFull": 604,
    "collectedFast": 519,
    "excludedFromFast": 85,
    "missingFromFull": [],
    "unexpectedInFull": [],
    "excludedNotInFull": [],
    "fastAndExcludedOverlap": [],
    "fastUnionExcludedEqualsFull": True,
}


def _evaluate(**over: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "mode": "full",
        "steps": _steps(ALL_GATES),
        "failed": False,
        "source": dict(CLEAN_SOURCE),
        "coverage": dict(GOOD_COVERAGE),
        "ci": {},
    }
    kwargs.update(over)
    return verify.evaluate_authority(**kwargs)


def test_release_authority_is_granted_only_by_a_complete_clean_full_run() -> None:
    """The one shape that IS release evidence — and `reasons` empty iff granted."""
    verdict = _evaluate()
    assert verdict["release"] is True
    assert verdict["reasons"] == []
    assert verdict["components"] == {"backendFullSuite": True, "frontendFullSuite": True}
    assert verdict["requiredGates"] == {g: "PASS" for g in ALL_GATES}
    assert verdict["pytestFullUnfiltered"] is True
    assert verdict["coverageProof"] is True
    assert verdict["sourceClean"] is True
    assert verdict["certifiedSha"] == "a" * 40
    assert verdict["certifiedShaKind"] == "SOURCE_HEAD"


def test_the_ac_f01_shape_is_no_longer_authority() -> None:
    """The audited defect, verbatim: FULL, nothing failed — but a dirty tree,
    no gate executed and no frontend. The old expression returned True."""
    verdict = _evaluate(
        steps=[],
        source={**CLEAN_SOURCE, "startDirty": True, "endDirty": True},
        coverage=None,
    )
    assert verdict["release"] is False
    assert "WORKTREE_DIRTY_AT_START" in verdict["reasons"]
    assert "WORKTREE_DIRTY_AT_END" in verdict["reasons"]
    assert "COVERAGE_PROOF_MISSING" in verdict["reasons"]
    assert {f"GATE_NOT_RUN:{g}" for g in ALL_GATES} <= set(verdict["reasons"])
    assert verdict["components"] == {"backendFullSuite": False, "frontendFullSuite": False}


def test_backend_only_full_run_is_a_component_never_release_evidence() -> None:
    """What CI's ``verify.py full --backend-only`` job actually produces."""
    verdict = _evaluate(steps=_steps(list(verify.RELEASE_BACKEND_GATES)))
    assert verdict["release"] is False
    assert verdict["components"]["backendFullSuite"] is True
    assert verdict["components"]["frontendFullSuite"] is False
    assert set(verdict["reasons"]) == {f"GATE_NOT_RUN:{g}" for g in verify.RELEASE_FRONTEND_GATES}
    assert verdict["requiredGates"]["fe-build"] == "NOT_RUN"


@pytest.mark.parametrize(
    ("source_over", "reason"),
    [
        ({"startDirty": True}, "WORKTREE_DIRTY_AT_START"),
        ({"endDirty": True}, "WORKTREE_DIRTY_AT_END"),
        ({"unchanged": False, "endDigest": "0123456789abcdef"}, "SOURCE_CHANGED_DURING_RUN"),
        (
            {"unchanged": False, "endHead": "b" * 40},
            "SOURCE_CHANGED_DURING_RUN",
        ),
    ],
)
def test_source_that_is_dirty_or_moved_never_carries_authority(
    source_over: dict[str, Any], reason: str
) -> None:
    verdict = _evaluate(source={**CLEAN_SOURCE, **source_over})
    assert verdict["release"] is False
    assert reason in verdict["reasons"]
    assert verdict["sourceClean"] is False
    assert verdict["components"] == {"backendFullSuite": False, "frontendFullSuite": False}


def test_a_failed_gate_withholds_authority_and_names_it() -> None:
    verdict = _evaluate(steps=_steps(ALL_GATES, failing={"fe-vitest"}), failed=True)
    assert verdict["release"] is False
    assert "GATE_FAILED:fe-vitest" in verdict["reasons"]
    assert "GATE_FAILURE_RECORDED" in verdict["reasons"]


def test_a_filtered_pytest_command_withholds_authority() -> None:
    """The judgement reads the command that ACTUALLY ran, not a declared tier."""
    steps = _steps(ALL_GATES)
    for step in steps:
        if step["name"] == "pytest-full":
            step["command"] = "python -m pytest -q -m 'not slow'"
    verdict = _evaluate(steps=steps)
    assert verdict["release"] is False
    assert "PYTEST_FULL_FILTERED" in verdict["reasons"]
    assert verdict["pytestFullUnfiltered"] is False
    assert verdict["components"]["backendFullSuite"] is False


@pytest.mark.parametrize(
    ("coverage", "reason"),
    [
        (None, "COVERAGE_PROOF_MISSING"),
        (
            {**GOOD_COVERAGE, "missingFromFull": ["tests/test_x.py::test_y"]},
            "COVERAGE_PROOF_FAILED",
        ),
        (
            {**GOOD_COVERAGE, "excludedNotInFull": ["tests/test_x.py::test_y"]},
            "COVERAGE_PROOF_FAILED",
        ),
        ({**GOOD_COVERAGE, "fastUnionExcludedEqualsFull": False}, "COVERAGE_PROOF_FAILED"),
        ({**GOOD_COVERAGE, "collectedFull": 0}, "COVERAGE_PROOF_FAILED"),
    ],
)
def test_an_unproven_collection_coverage_withholds_authority(
    coverage: dict[str, Any] | None, reason: str
) -> None:
    verdict = _evaluate(coverage=coverage)
    assert verdict["release"] is False
    assert reason in verdict["reasons"]
    assert verdict["coverageProof"] is False


@pytest.mark.parametrize("mode", ["fast", "feature", "benchmark"])
def test_a_non_full_tier_is_never_release_evidence(mode: str) -> None:
    verdict = _evaluate(mode=mode)
    assert verdict["release"] is False
    assert f"MODE_NOT_FULL:{mode}" in verdict["reasons"]
    assert verdict["components"] == {"backendFullSuite": False, "frontendFullSuite": False}


def test_pull_request_ci_records_the_merge_simulation_separately_from_the_pr_head() -> None:
    """A PR CI run checks out GitHub's synthetic merge commit; the summary must
    not present it as the reviewed head."""
    merge = _evaluate(
        ci={
            "provider": "github-actions",
            "eventName": "pull_request",
            "githubSha": "a" * 40,
            "prHeadSha": "c" * 40,
        }
    )
    assert merge["certifiedShaKind"] == "PULL_REQUEST_MERGE_SIMULATION"
    assert merge["certifiedSha"] == "a" * 40
    same = _evaluate(
        ci={"provider": "github-actions", "eventName": "pull_request", "prHeadSha": "a" * 40}
    )
    assert same["certifiedShaKind"] == "PULL_REQUEST_HEAD"
    push = _evaluate(ci={"provider": "github-actions", "eventName": "push"})
    assert push["certifiedShaKind"] == "SOURCE_HEAD"


# --------------------------------------------------------------------------- #
# aggregate: several component runs of ONE revision
# --------------------------------------------------------------------------- #


def _summary(label: str, gates: list[str], **over: Any) -> dict[str, Any]:
    """A component summary in the shape the runner actually writes: the
    aggregate re-derives its verdict from steps / mode / sourceIdentity /
    collectionCoverage, so the evidence must be there."""
    steps = over.pop("steps", None) or _steps(gates)
    source = over.pop("source", None) or dict(CLEAN_SOURCE)
    coverage = over.pop("coverage", "default")
    coverage = dict(GOOD_COVERAGE) if coverage == "default" else coverage
    mode = over.pop("mode", "full")
    verdict = verify.evaluate_authority(
        mode=mode,
        steps=steps,
        failed=over.pop("failed", False),
        source=source,
        coverage=coverage,
        ci=over.pop("ci", {}),
    )
    return {
        "label": label,
        "mode": mode.upper(),
        "status": "PASS",
        "gitHead": source["endHead"],
        "steps": steps,
        "sourceIdentity": source,
        "collectionCoverage": coverage,
        "failedSteps": [s["name"] for s in steps if s["status"] == "FAIL"],
        "authority": verdict,
    }


def test_aggregate_grants_authority_when_components_cover_every_gate_at_one_revision() -> None:
    backend = _summary("full-backend", list(verify.RELEASE_BACKEND_GATES))
    frontend = _summary("full-frontend", list(verify.RELEASE_FRONTEND_GATES), coverage=None)
    verdict = verify.aggregate_authority([backend, frontend])
    assert verdict["release"] is True, verdict["reasons"]
    assert verdict["reasons"] == []
    assert verdict["certifiedSha"] == "a" * 40
    assert verdict["gateSource"]["pytest-full"] == "full-backend"
    assert verdict["gateSource"]["fe-build"] == "full-frontend"


def test_aggregate_refuses_components_that_certify_different_revisions() -> None:
    backend = _summary("full-backend", list(verify.RELEASE_BACKEND_GATES))
    frontend = _summary("full-frontend", list(verify.RELEASE_FRONTEND_GATES), coverage=None)
    frontend["sourceIdentity"] = {**CLEAN_SOURCE, "startHead": "b" * 40, "endHead": "b" * 40}
    verdict = verify.aggregate_authority([backend, frontend])
    assert verdict["release"] is False
    assert any(r.startswith("COMPONENTS_CERTIFY_DIFFERENT_REVISIONS") for r in verdict["reasons"])
    assert verdict["certifiedSha"] is None


def test_aggregate_refuses_a_gate_no_component_passed_and_a_blocked_component() -> None:
    backend = _summary("full-backend", list(verify.RELEASE_BACKEND_GATES))
    partial = _summary("full-frontend", ["fe-typecheck", "fe-lint"], coverage=None)
    verdict = verify.aggregate_authority([backend, partial])
    assert verdict["release"] is False
    assert "GATE_NOT_PASSED_BY_ANY_COMPONENT:fe-build" in verdict["reasons"]

    dirty = _summary(
        "full-frontend",
        list(verify.RELEASE_FRONTEND_GATES),
        coverage=None,
        source={**CLEAN_SOURCE, "endDirty": True},
    )
    blocked = verify.aggregate_authority([backend, dirty])
    assert blocked["release"] is False
    assert "COMPONENT_BLOCKED:full-frontend:WORKTREE_DIRTY_AT_END" in blocked["reasons"]


def test_aggregate_of_nothing_is_not_authority() -> None:
    verdict = verify.aggregate_authority([])
    assert verdict["release"] is False
    assert verdict["reasons"] == ["NO_COMPONENT_SUMMARIES"]


def test_aggregate_needs_the_coverage_proof_from_some_component() -> None:
    backend = _summary("full-backend", list(verify.RELEASE_BACKEND_GATES), coverage=None)
    frontend = _summary("full-frontend", list(verify.RELEASE_FRONTEND_GATES), coverage=None)
    verdict = verify.aggregate_authority([backend, frontend])
    assert verdict["release"] is False
    assert "COVERAGE_PROOF_MISSING" in verdict["reasons"]


# --------------------------------------------------------------------------- #
# the runner records the identity it judged
# --------------------------------------------------------------------------- #


def test_runner_records_start_and_end_source_identity() -> None:
    runner = verify.Runner("fast")
    identity = runner.source_identity()
    assert set(identity) == {
        "startHead",
        "endHead",
        "startDirty",
        "endDirty",
        "startDigest",
        "endDigest",
        "unchanged",
    }
    # nothing changed between construction and this call
    assert identity["startHead"] == identity["endHead"]
    assert identity["unchanged"] is True
    # a moved source is detected through the digest, not only the head
    runner.source_start = {"head": "z" * 40, "dirty": False, "digest": "0000000000000000"}
    moved = runner.source_identity()
    assert moved["unchanged"] is False


def test_source_state_is_fail_closed_when_git_is_unavailable(monkeypatch: Any) -> None:
    monkeypatch.setattr(verify, "_git", lambda *a: "unknown")
    state = verify._source_state()
    assert state["dirty"] is True


def test_authority_subcommand_writes_a_verdict_and_exits_nonzero_when_withheld(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(verify, "VERIFICATION", tmp_path)
    backend = tmp_path / "backend.json"
    frontend = tmp_path / "frontend.json"
    # no explicit label in the files: the CLI must name components by file stem
    be = _summary("", list(verify.RELEASE_BACKEND_GATES))
    fe = _summary("", list(verify.RELEASE_FRONTEND_GATES), coverage=None)
    be.pop("label")
    fe.pop("label")
    backend.write_text(json.dumps(be), encoding="utf-8")
    frontend.write_text(json.dumps(fe), encoding="utf-8")
    assert verify.main(["authority", str(backend), str(frontend)]) == 0
    written = json.loads((tmp_path / "release-authority.json").read_text(encoding="utf-8"))
    # the label defaults to the file stem, so the verdict says who proved what
    assert written["release"] is True
    assert written["gateSource"]["mypy"] == "backend"
    assert verify.main(["authority", str(backend)]) == 1


# --------------------------------------------------------------------------- #
# review pass: every ambiguous input must fail CLOSED
# --------------------------------------------------------------------------- #


def test_an_unreadable_pull_request_payload_is_unverified_not_the_pr_head() -> None:
    """The reassuring label is exactly the conflation this record exists to
    prevent: with no readable event payload the SHA is UNVERIFIED."""
    for ci in (
        {"provider": "github-actions", "eventName": "pull_request"},
        {"provider": "github-actions", "eventName": "pull_request", "prHeadSha": None},
        {
            "provider": "github-actions",
            "eventName": "pull_request_target",
            "eventPayloadError": "GITHUB_EVENT_PATH not set",
        },
    ):
        assert _evaluate(ci=ci)["certifiedShaKind"] == "PULL_REQUEST_SHA_UNVERIFIED"


def test_ci_context_records_a_missing_event_path(monkeypatch: Any) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    ctx = verify._ci_context()
    assert ctx["eventPayloadError"] == "GITHUB_EVENT_PATH not set"
    assert "prHeadSha" not in ctx


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("python -m pytest -q --junitxml=/x/full-pytest.xml", None),
        ("python -m pytest -q -m 'not slow'", "'not slow'"),
        ("/usr/bin/pytest-3 -q -k not_slow", "not_slow"),
        ("python -m pytest -q --deselect tests/test_x.py::test_y", "tests/test_x.py::test_y"),
        ("", "UNPARSEABLE"),
        ("bash run-the-suite.sh", "UNPARSEABLE"),
    ],
)
def test_marker_detection_reads_the_executed_command_and_fails_closed(
    command: str, expected: str | None
) -> None:
    assert verify._pytest_marker_expression({"name": "pytest-full", "command": command}) == expected
    # a recorded expression always wins over the command line
    assert (
        verify._pytest_marker_expression(
            {"name": "pytest-full", "command": command, "markerExpression": None}
        )
        is None
    )


def test_an_unparseable_pytest_command_withholds_authority() -> None:
    steps = _steps(ALL_GATES)
    for step in steps:
        if step["name"] == "pytest-full":
            step["command"] = "bash run-the-suite.sh"
    verdict = _evaluate(steps=steps)
    assert verdict["release"] is False
    assert "PYTEST_FULL_FILTERED" in verdict["reasons"]


def test_the_suite_must_have_executed_everything_it_collected() -> None:
    """collected(FULL) == collected(unfiltered) is true by construction; the
    executed count is the part that actually proves the run."""
    verdict = _evaluate(coverage={**GOOD_COVERAGE, "executedFull": 603})
    assert verdict["release"] is False
    assert "EXECUTION_COVERAGE_MISMATCH:603!=604" in verdict["reasons"]
    assert verdict["coverageProof"] is False
    # an older summary with no executed count is not failed by this condition
    older = dict(GOOD_COVERAGE)
    older.pop("executedFull")
    assert _evaluate(coverage=older)["release"] is True


def test_aggregate_refuses_a_component_that_cannot_name_its_revision() -> None:
    backend = _summary("full-backend", list(verify.RELEASE_BACKEND_GATES))
    frontend = _summary("full-frontend", list(verify.RELEASE_FRONTEND_GATES), coverage=None)
    for blank in ({**CLEAN_SOURCE, "endHead": ""}, {**CLEAN_SOURCE, "endHead": "unknown"}):
        frontend["sourceIdentity"] = blank
        verdict = verify.aggregate_authority([backend, frontend])
        assert verdict["release"] is False
        assert "COMPONENT_REVISION_UNKNOWN:full-frontend" in verdict["reasons"]
        assert verdict["certifiedSha"] != "None"


def test_aggregate_refuses_a_summary_with_no_evidence_and_ignores_a_lying_block() -> None:
    """A self-reported authority block is a claim, not its basis."""
    backend = _summary("full-backend", list(verify.RELEASE_BACKEND_GATES))
    liar = {
        "label": "full-frontend",
        "mode": "FAST",
        "status": "FAIL",
        "gitHead": "a" * 40,
        "authority": {
            "release": True,
            "reasons": [],
            "requiredGates": {g: "PASS" for g in ALL_GATES},
            "coverageProof": True,
            "pytestFullUnfiltered": True,
            "certifiedSha": "a" * 40,
            "certifiedShaKind": "SOURCE_HEAD",
        },
    }
    verdict = verify.aggregate_authority([backend, liar])
    assert verdict["release"] is False
    assert "COMPONENT_EVIDENCE_MISSING:full-frontend" in verdict["reasons"]
    assert "GATE_NOT_PASSED_BY_ANY_COMPONENT:fe-build" in verdict["reasons"]

    # the same claim WITH evidence that contradicts it is judged on the evidence
    dishonest = _summary(
        "full-frontend",
        list(verify.RELEASE_FRONTEND_GATES),
        mode="fast",
        coverage=None,
    )
    dishonest["authority"] = liar["authority"]
    contradicted = verify.aggregate_authority([backend, dishonest])
    assert contradicted["release"] is False
    assert "COMPONENT_BLOCKED:full-frontend:MODE_NOT_FULL:fast" in contradicted["reasons"]
