"""AC-01H: the CI workflow STRUCTURE, pinned semantically (W1–W7).

The release verdict of this repository is ONE job — ``Release Authority`` in
``.github/workflows/verify-full.yml`` — that re-judges the two component
summaries with ``scripts/verify.py authority``. These tests read the workflow
YAML and pin what makes that judgement trustworthy: the triggers are the ones
the retired ``ci.yml`` had (pull_request + push main — never narrowed), the
backend component keeps the full-history checkout AC-01G LAYER B needs, every
evidence upload can actually see the dotted ``.verification`` directory and
fails when it is empty, and the authority job depends on BOTH components, runs
even when one failed (``if: always()``), and publishes its verdict.

They pin structure, not formatting: keys are located through the parsed YAML,
so an indentation or comment change never fails them, while a removed
trigger, a dropped ``fetch-depth``, an artifact that could be silently empty
or an authority job that could be skipped does. FAST tier by construction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
FULL = WORKFLOWS / "verify-full.yml"
FAST = WORKFLOWS / "verify-fast.yml"

#: the artifact names an independent reviewer downloads (AC-01H §23)
FULL_ARTIFACTS = {
    "full-backend": "verification-full-backend",
    "full-frontend": "verification-full-frontend",
    "release-authority": "verification-release-authority",
}
FAST_ARTIFACT = "verification-fast"


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), path
    return data


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML parses the bare key `on` as boolean True
    raw = workflow.get("on", workflow.get(True))
    assert raw is not None, "workflow has no trigger block"
    if isinstance(raw, list):
        return {k: None for k in raw}
    if isinstance(raw, str):
        return {raw: None}
    return dict(raw)


def _steps_using(job: dict[str, Any], action: str) -> list[dict[str, Any]]:
    return [s for s in job.get("steps", []) if str(s.get("uses", "")).startswith(action)]


def _run_steps(job: dict[str, Any]) -> list[str]:
    return [str(s["run"]) for s in job.get("steps", []) if "run" in s]


@pytest.fixture(scope="module")
def full() -> dict[str, Any]:
    return _load(FULL)


@pytest.fixture(scope="module")
def fast() -> dict[str, Any]:
    return _load(FAST)


# --------------------------------------------------------------------------- #
# W1 — trigger authority is not narrowed
# --------------------------------------------------------------------------- #


def test_w1_full_runs_on_every_pull_request_and_on_push_to_main(full: dict[str, Any]) -> None:
    """The retired ci.yml ran on ``pull_request`` and ``push: main``. The
    authoritative FULL keeps exactly that reach: never manual-only, label-only,
    main-only or path-filtered."""
    on = _triggers(full)
    assert "pull_request" in on, on
    assert "push" in on, on
    push = on["push"] or {}
    assert "main" in (push.get("branches") or []), push
    # no narrowing filter on either trigger
    for key in ("pull_request", "push"):
        cfg = on.get(key) or {}
        assert not cfg.get("paths") and not cfg.get("paths-ignore"), f"{key} is path-filtered"
        assert not cfg.get("types") or "labeled" not in cfg.get("types", []), (
            f"{key} is label-gated"
        )
    pr = on.get("pull_request") or {}
    assert not pr.get("branches"), "pull_request is restricted to some base branches"


def test_the_three_full_jobs_exist_with_their_public_names(full: dict[str, Any]) -> None:
    jobs = full["jobs"]
    assert set(FULL_ARTIFACTS) <= set(jobs), sorted(jobs)
    assert jobs["release-authority"]["name"] == "Release Authority"


# --------------------------------------------------------------------------- #
# W2 — the backend component keeps AC-01G's full-history checkout
# --------------------------------------------------------------------------- #


def test_w2_backend_component_checks_out_full_history(full: dict[str, Any]) -> None:
    """tests/test_layout_characterization.py extracts ``git archive
    <freeze-sha> backend/src`` on the runner and FAILS (never skips) when the
    commit is absent — a shallow clone would turn LAYER B red."""
    checkouts = _steps_using(full["jobs"]["full-backend"], "actions/checkout")
    assert checkouts, "backend component has no checkout step"
    assert (checkouts[0].get("with") or {}).get("fetch-depth") == 0


# --------------------------------------------------------------------------- #
# W3 / W4 / W6 / W7 — evidence uploads can see .verification and fail when empty
# --------------------------------------------------------------------------- #


def _upload(job: dict[str, Any], name: str) -> dict[str, Any]:
    uploads = [
        s
        for s in _steps_using(job, "actions/upload-artifact")
        if (s.get("with") or {}).get("name") == name
    ]
    assert len(uploads) == 1, f"expected exactly one upload named {name!r}, found {len(uploads)}"
    return uploads[0]


def _assert_evidence_upload(step: dict[str, Any]) -> None:
    with_ = step.get("with") or {}
    assert str(with_.get("path", "")).rstrip("/") == "backend/.verification", with_
    # the pre-AC-01H defect: a dotted directory with include-hidden-files false
    # uploads NOTHING and the step is still green
    assert with_.get("include-hidden-files") is True, with_
    assert with_.get("if-no-files-found") == "error", with_
    # evidence is uploaded on failure too, or a red run leaves no record
    assert step.get("if") == "always()", step


@pytest.mark.parametrize("job_id,artifact", sorted(FULL_ARTIFACTS.items()))
def test_w3_w4_w6_every_full_evidence_upload_is_real(
    full: dict[str, Any], job_id: str, artifact: str
) -> None:
    _assert_evidence_upload(_upload(full["jobs"][job_id], artifact))


def test_w7_fast_evidence_upload_is_real(fast: dict[str, Any]) -> None:
    jobs = fast["jobs"]
    assert len(jobs) == 1
    (job,) = jobs.values()
    _assert_evidence_upload(_upload(job, FAST_ARTIFACT))


# --------------------------------------------------------------------------- #
# W5 — the authority job depends on both components and fails closed
# --------------------------------------------------------------------------- #


def test_w5_release_authority_needs_both_components_and_always_runs(
    full: dict[str, Any],
) -> None:
    job = full["jobs"]["release-authority"]
    assert set(job.get("needs") or []) == {"full-backend", "full-frontend"}, job.get("needs")
    # a failed or missing component must produce a RECORDED withheld verdict,
    # never a skipped job — so the job runs regardless of upstream outcome
    assert job.get("if") == "always()"
    downloads = _steps_using(job, "actions/download-artifact")
    names = {(s.get("with") or {}).get("name") for s in downloads}
    assert names == {FULL_ARTIFACTS["full-backend"], FULL_ARTIFACTS["full-frontend"]}, names
    # a missing artifact must not abort before the verdict is written
    assert all(s.get("continue-on-error") is True for s in downloads), downloads
    runs = "\n".join(_run_steps(job))
    assert "scripts/verify.py authority" in runs
    # both component summaries are passed EVERY time; a missing path is a typed
    # reason inside the verdict (COMPONENT_SUMMARY_MISSING), not a smaller set
    assert "full-backend/verification-summary.json" in runs
    assert "full-frontend/verification-summary.json" in runs


# --------------------------------------------------------------------------- #
# the components run through ONE runner implementation
# --------------------------------------------------------------------------- #


def test_components_run_verify_py_with_exactly_one_component_flag(full: dict[str, Any]) -> None:
    backend = "\n".join(_run_steps(full["jobs"]["full-backend"]))
    frontend = "\n".join(_run_steps(full["jobs"]["full-frontend"]))
    assert "scripts/verify.py full --backend-only" in backend
    assert "--frontend-only" not in backend
    assert "scripts/verify.py full --frontend-only" in frontend
    assert "--backend-only" not in frontend
    # the frontend summary is produced by the runner, never assembled by hand
    assert "verification-summary.json" not in frontend
    for job_id in ("full-backend", "full-frontend"):
        runs = _run_steps(full["jobs"][job_id])
        assert not any("verify.py authority" in r for r in runs), (
            f"{job_id} must not aggregate: the verdict belongs to release-authority only"
        )


def test_fast_is_a_pull_request_feedback_loop_not_a_release_gate(fast: dict[str, Any]) -> None:
    on = _triggers(fast)
    assert "pull_request" in on
    runs = "\n".join(_run_steps(next(iter(fast["jobs"].values()))))
    assert "scripts/verify.py fast" in runs
    assert "verify.py authority" not in runs
