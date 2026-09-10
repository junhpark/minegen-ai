#!/usr/bin/env python
"""MineGen-AI verification runner (VA-01 §25–30).

One orchestration entry point over the EXISTING toolchain (pytest, ruff,
mypy, npm scripts) — no new test framework:

    python scripts/verify.py fast        # inner loop: static + unmarked tests + cached canaries
    python scripts/verify.py feature     # fast + clean canaries (TABULAR / WARPED-301 / 307)
    python scripts/verify.py full        # authoritative: every gate the old CI ran, unfiltered
    python scripts/verify.py full --closeout   # + golden / legacy / survey / screen-audit summaries
    python scripts/verify.py benchmark   # runtime observation only (never a correctness gate)
    python scripts/verify.py collect-full      # invariant: collected(FULL) == collected(all)
    python scripts/verify.py authority A.json B.json   # aggregate component summaries → ONE verdict

Output policy: on success only exit code / counts / elapsed are printed; on
failure only the failed test ids, the first actionable traceback and the log
path. Raw logs and the machine-readable summary live under
backend/.verification/ (git-ignored):

    backend/.verification/verification-summary.json
    backend/.verification/<mode>-<step>.log
    backend/.verification/<mode>-pytest.xml

FAST excludes the heavy marker groups; FULL runs pytest UNFILTERED, so its
correctness scope is never smaller than the old ``pytest -q``.

Release authority (AC-01A) is an AGGREGATE judgement, never "the mode was
full and nothing failed": ``authority.release`` requires EVERY required gate
(backend static + UNFILTERED pytest + the collection proof + all five
frontend gates) to have PASSED, in the FULL tier, over ONE source revision
that was clean at the start AND at the end of the run and did not change in
between. A partial run (``--backend-only``, a non-FULL tier) yields a
COMPONENT authority only; ``authority`` records the typed reasons a run is
not release evidence, and ``verify.py authority`` combines component
summaries of the same revision into one verdict, re-judging each from its own
recorded evidence. On a pull-request CI run the checked-out commit is
GitHub's synthetic merge commit, so the summary records both it and the PR
head SHA (``ci.prHeadSha``) and labels which one the run certifies
(``certifiedShaKind``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VERIFICATION = BACKEND / ".verification"

#: tier expressions — the SINGLE source of truth (tests/test_verification_tiers.py imports them)
HEAVY_MARKERS = ("slow", "golden", "survey", "e2e", "legacy_regression", "benchmark")
FAST_EXPR = " and ".join(f"not {m}" for m in HEAVY_MARKERS)
EXCLUDED_EXPR = " or ".join(HEAVY_MARKERS)
FEATURE_EXPR = f"({FAST_EXPR}) or canary"


def _python() -> str:
    venv = BACKEND / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _head() -> dict[str, Any]:
    return {"gitHead": _git("rev-parse", "HEAD"), "gitDirty": bool(_git("status", "--porcelain"))}


#: gates a FULL run must have PASSED before its result is release evidence.
#: Split by component so a partial run (CI runs the backend and the frontend
#: in separate jobs) reports what it actually covered instead of claiming the
#: whole set.
RELEASE_BACKEND_GATES = ("ruff-check", "ruff-format", "mypy", "pytest-full")
RELEASE_FRONTEND_GATES = ("fe-typecheck", "fe-lint", "fe-prettier", "fe-vitest", "fe-build")
RELEASE_GATES = RELEASE_BACKEND_GATES + RELEASE_FRONTEND_GATES

#: pytest flags that narrow the executed set — any of them means the run was
#: not the unfiltered suite
PYTEST_SELECTION_FLAGS = ("-m", "-k", "--deselect", "--ignore", "--last-failed", "--lf")


def _source_state() -> dict[str, Any]:
    """Identity of the SOURCE the runner is about to judge (or just judged).

    ``digest`` covers the commit AND the porcelain status, so a tree that is
    edited during a run — the common way a "PASS" stops describing the
    reviewed source — changes it. ``_git`` returns ``"unknown"`` when git is
    unavailable, which reads as dirty: fail-closed, never silently clean.
    """
    head = _git("rev-parse", "HEAD")
    porcelain = _git("status", "--porcelain")
    return {
        "head": head,
        "dirty": bool(porcelain),
        "digest": hashlib.sha256(f"{head}\n{porcelain}".encode()).hexdigest()[:16],
    }


def _ci_context() -> dict[str, Any]:
    """On GitHub Actions a ``pull_request`` run checks out a SYNTHETIC merge
    commit, so ``gitHead`` is neither the PR head nor the base. Record both
    and let the summary say which SHA the result certifies."""
    env = os.environ
    if not env.get("GITHUB_ACTIONS"):
        return {"provider": None}
    ctx: dict[str, Any] = {
        "provider": "github-actions",
        "eventName": env.get("GITHUB_EVENT_NAME"),
        "githubSha": env.get("GITHUB_SHA"),
        "githubRef": env.get("GITHUB_REF"),
        "workflow": env.get("GITHUB_WORKFLOW"),
        "job": env.get("GITHUB_JOB"),
        "runId": env.get("GITHUB_RUN_ID"),
        "runAttempt": env.get("GITHUB_RUN_ATTEMPT"),
    }
    path = env.get("GITHUB_EVENT_PATH")
    if ctx["eventName"] in ("pull_request", "pull_request_target"):
        if not path:
            ctx["eventPayloadError"] = "GITHUB_EVENT_PATH not set"
        else:
            try:
                payload = json.loads(Path(path).read_text(encoding="utf-8"))
                pr = payload.get("pull_request") or {}
                ctx["prNumber"] = payload.get("number") or pr.get("number")
                ctx["prHeadSha"] = (pr.get("head") or {}).get("sha")
                ctx["prBaseSha"] = (pr.get("base") or {}).get("sha")
            except Exception as exc:  # payload shape is GitHub's, never ours to assume
                ctx["eventPayloadError"] = f"{type(exc).__name__}: {exc}"[:200]
    return ctx


def _certified_sha_kind(head: str, ci: dict[str, Any]) -> str:
    """What the certified SHA IS — a real source head, or GitHub's throwaway
    PR merge simulation (which exists in no branch and cannot be re-checked
    out later).

    Fails CLOSED: on a pull-request event whose head SHA could not be read the
    answer is UNVERIFIED, never the reassuring "this is the PR head" — that
    conflation is the thing this function exists to prevent.
    """
    if ci.get("eventName") in ("pull_request", "pull_request_target"):
        pr_head = ci.get("prHeadSha")
        if not pr_head:
            return "PULL_REQUEST_SHA_UNVERIFIED"
        if head and head != pr_head:
            return "PULL_REQUEST_MERGE_SIMULATION"
        return "PULL_REQUEST_HEAD"
    return "SOURCE_HEAD"


def _pytest_marker_expression(step: dict[str, Any]) -> str | None:
    """The selection a recorded pytest step ran under, or ``None`` for a
    genuinely unfiltered run.

    Prefers the value the runner recorded. Otherwise it reads the executed
    command line, skipping the ``python -m pytest`` prefix so the
    interpreter's own ``-m`` is never mistaken for a marker filter — and if
    that command cannot be parsed it answers ``"UNPARSEABLE"`` rather than
    "unfiltered": an unreadable command is not evidence of a full run.
    """
    if "markerExpression" in step:
        expr = step["markerExpression"]
        return str(expr) if expr else None
    tokens = str(step.get("command", "")).split()
    start = next(
        (i for i, t in enumerate(tokens) if os.path.basename(t).startswith("pytest")), None
    )
    if start is None:
        return "UNPARSEABLE"
    rest = tokens[start + 1 :]
    for flag in PYTEST_SELECTION_FLAGS:
        if flag in rest:
            return " ".join(rest[rest.index(flag) + 1 :]) or flag
    return None


def _coverage_ok(coverage: dict[str, Any] | None) -> bool:
    """The mechanical collection proof (rule 181): FULL collected the entire
    universe, every FAST exclusion is inside FULL, and — the only part that is
    not true by construction — the unfiltered run EXECUTED everything it
    collected."""
    if not coverage:
        return False
    executed, collected = coverage.get("executedFull"), coverage.get("collectedFull")
    executed_ok = executed is None or int(executed) == int(collected or 0)
    return (
        not coverage.get("missingFromFull")
        and not coverage.get("unexpectedInFull")
        and not coverage.get("excludedNotInFull")
        and not coverage.get("fastAndExcludedOverlap")
        and coverage.get("fastUnionExcludedEqualsFull") is True
        and int(coverage.get("collectedFull") or 0) > 0
        and executed_ok
    )


def evaluate_authority(
    *,
    mode: str,
    steps: list[dict[str, Any]],
    failed: bool,
    source: dict[str, Any],
    coverage: dict[str, Any] | None = None,
    ci: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide what a run is evidence FOR (AC-01A).

    ``release`` is granted only when the FULL tier ran EVERY required gate to
    PASS — including the UNFILTERED pytest command actually executed and the
    collection proof — over one clean, unchanged source revision. Components
    are reported separately so a backend-only or frontend-only run states its
    true coverage instead of inheriting the whole verdict. Every unmet
    condition is returned as a typed reason; ``reasons`` is empty if and only
    if ``release`` is true. This judges evidence, never engineering: no gate,
    threshold or test is relaxed here.
    """
    by_name = {s["name"]: s for s in steps}

    def passed(gate: str) -> bool:
        return by_name.get(gate, {}).get("status") == "PASS"

    ci = ci or {}
    reasons: list[str] = []
    if mode != "full":
        reasons.append(f"MODE_NOT_FULL:{mode}")
    if failed:
        reasons.append("GATE_FAILURE_RECORDED")
    for gate in RELEASE_GATES:
        if gate not in by_name:
            reasons.append(f"GATE_NOT_RUN:{gate}")
        elif not passed(gate):
            reasons.append(f"GATE_FAILED:{gate}")
    # the pytest step that ACTUALLY ran must carry no selection flag
    full_step = by_name.get("pytest-full")
    unfiltered = full_step is not None and _pytest_marker_expression(full_step) is None
    if full_step is not None and not unfiltered:
        reasons.append("PYTEST_FULL_FILTERED")
    coverage_ok = _coverage_ok(coverage)
    if not coverage_ok:
        reasons.append("COVERAGE_PROOF_MISSING" if not coverage else "COVERAGE_PROOF_FAILED")
    # collected(FULL) == collected(unfiltered) is true by construction (both
    # are the same collect-only call), so it proves nothing on its own. What
    # does prove the suite ran whole is the executed count from the junit
    # report of the pytest step that actually ran.
    cov = coverage or {}
    executed, collected = cov.get("executedFull"), cov.get("collectedFull")
    if executed is not None and collected is not None and int(executed) != int(collected):
        reasons.append(f"EXECUTION_COVERAGE_MISMATCH:{executed}!={collected}")
    if source.get("startDirty"):
        reasons.append("WORKTREE_DIRTY_AT_START")
    if source.get("endDirty"):
        reasons.append("WORKTREE_DIRTY_AT_END")
    if not source.get("unchanged"):
        reasons.append("SOURCE_CHANGED_DURING_RUN")

    clean_source = (
        not source.get("startDirty")
        and not source.get("endDirty")
        and bool(source.get("unchanged"))
    )
    backend_component = (
        mode == "full"
        and all(passed(g) for g in RELEASE_BACKEND_GATES)
        and unfiltered
        and coverage_ok
        and clean_source
    )
    frontend_component = (
        mode == "full" and all(passed(g) for g in RELEASE_FRONTEND_GATES) and clean_source
    )
    return {
        "release": not reasons,
        "components": {
            "backendFullSuite": backend_component,
            "frontendFullSuite": frontend_component,
        },
        "requiredGates": {g: by_name.get(g, {}).get("status", "NOT_RUN") for g in RELEASE_GATES},
        "pytestFullUnfiltered": unfiltered,
        "coverageProof": coverage_ok,
        "sourceClean": clean_source,
        "certifiedSha": source.get("endHead"),
        "certifiedShaKind": _certified_sha_kind(str(source.get("endHead") or ""), ci),
        "reasons": reasons,
    }


def component_verdict(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Re-derive a component's verdict from the evidence recorded IN its
    summary — the steps, tier, source identity and coverage report — never
    from its own ``authority`` block. A self-reported verdict is a claim; only
    its basis is trusted. ``None`` when the summary carries no such basis."""
    steps = summary.get("steps")
    source = summary.get("sourceIdentity")
    if not isinstance(steps, list) or not isinstance(source, dict):
        return None
    return evaluate_authority(
        mode=str(summary.get("mode", "")).lower(),
        steps=steps,
        failed=bool(summary.get("failedSteps")) or summary.get("status") == "FAIL",
        source=source,
        coverage=summary.get("collectionCoverage"),
        ci=summary.get("ci") or {},
    )


def aggregate_authority(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine COMPONENT summaries (e.g. CI's backend-only FULL job and a
    frontend FULL job) into one release verdict.

    Every required gate must have PASSED in some component, every component
    must itself be a clean unchanged FULL run, and all of them must certify
    the SAME resolvable revision — an aggregate over two revisions, or over a
    component that cannot name its revision, is evidence for neither. Reasons
    are typed, and the verdict never invents a gate result no component
    produced.
    """
    reasons: list[str] = []
    if not summaries:
        return {"release": False, "reasons": ["NO_COMPONENT_SUMMARIES"], "components": []}
    verdicts: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
    shas: set[str] = set()
    for summary in summaries:
        label = str(summary.get("label") or summary.get("mode") or "?")
        verdict = component_verdict(summary)
        verdicts.append((label, summary, verdict))
        if verdict is None:
            reasons.append(f"COMPONENT_EVIDENCE_MISSING:{label}")
            continue
        sha = str(verdict.get("certifiedSha") or "")
        if not sha or sha.lower() in ("none", "unknown"):
            reasons.append(f"COMPONENT_REVISION_UNKNOWN:{label}")
            continue
        shas.add(sha)
    if len(shas) > 1:
        reasons.append("COMPONENTS_CERTIFY_DIFFERENT_REVISIONS:" + ",".join(sorted(shas)))
    gate_source: dict[str, str | None] = {}
    for gate in RELEASE_GATES:
        owner = next(
            (
                label
                for label, _summary, verdict in verdicts
                if verdict and verdict["requiredGates"].get(gate) == "PASS"
            ),
            None,
        )
        gate_source[gate] = owner
        if owner is None:
            reasons.append(f"GATE_NOT_PASSED_BY_ANY_COMPONENT:{gate}")
    components = []
    for label, summary, verdict in verdicts:
        blocking = [
            r
            for r in (verdict["reasons"] if verdict else ["AUTHORITY_EVIDENCE_MISSING"])
            # a component legitimately does not run the other component's
            # gates, and only the backend component produces the collection
            # proof; both are re-checked globally below, so they are not
            # component defects. A FAILED proof or a dirty source stays
            # blocking.
            if not r.startswith("GATE_NOT_RUN:") and r != "COVERAGE_PROOF_MISSING"
        ]
        components.append(
            {
                "label": label,
                "mode": summary.get("mode"),
                "certifiedSha": (verdict or {}).get("certifiedSha"),
                "certifiedShaKind": (verdict or {}).get("certifiedShaKind"),
                "blockingReasons": blocking,
            }
        )
        for reason in blocking:
            reasons.append(f"COMPONENT_BLOCKED:{label}:{reason}")
    if not any(v and v["coverageProof"] for _label, _summary, v in verdicts):
        reasons.append("COVERAGE_PROOF_MISSING")
    if not any(v and v["pytestFullUnfiltered"] for _label, _summary, v in verdicts):
        reasons.append("PYTEST_FULL_FILTERED")
    return {
        "release": not reasons,
        "certifiedSha": next(iter(shas)) if len(shas) == 1 else None,
        "certifiedShaKinds": sorted(
            {str(c["certifiedShaKind"]) for c in components if c["certifiedShaKind"]}
        ),
        "gateSource": gate_source,
        "components": components,
        "reasons": reasons,
    }


class Runner:
    def __init__(self, mode: str, verbose: bool = False) -> None:
        self.mode = mode
        self.verbose = verbose
        self.t0 = time.perf_counter()
        self.steps: list[dict[str, Any]] = []
        self.failed = False
        # the source the run STARTS on: a result only describes a revision the
        # run held from the first gate to the last (AC-01A)
        self.source_start = _source_state()
        self.ci = _ci_context()
        VERIFICATION.mkdir(parents=True, exist_ok=True)

    # -- primitives ---------------------------------------------------------- #

    def run(
        self, name: str, cmd: list[str], cwd: Path, env: dict[str, str] | None = None
    ) -> dict[str, Any]:
        log = VERIFICATION / f"{self.mode}-{name}.log"
        t0 = time.perf_counter()
        full_env = {**os.environ, **(env or {})}
        with log.open("w", encoding="utf-8") as fh:
            proc = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, env=full_env)
        step = {
            "name": name,
            "command": " ".join(cmd),
            "cwd": str(cwd.relative_to(ROOT)),
            "exitCode": proc.returncode,
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "elapsedSeconds": round(time.perf_counter() - t0, 1),
            "log": str(log.relative_to(ROOT)),
        }
        self.steps.append(step)
        if proc.returncode != 0:
            self.failed = True
            print(
                f"  FAIL  {name} ({step['elapsedSeconds']} s) "
                f"exit={proc.returncode} → {step['log']}"
            )
            self._show_failure_excerpt(log)
        else:
            print(f"  PASS  {name} ({step['elapsedSeconds']} s)")
        return step

    def _show_failure_excerpt(self, log: Path, lines: int = 40) -> None:
        text = log.read_text(encoding="utf-8", errors="replace").splitlines()
        # first actionable region: an error/traceback marker, else the tail
        idx = next(
            (i for i, ln in enumerate(text) if re.search(r"error|Error|FAILED|Traceback", ln)), None
        )
        excerpt = text[idx : idx + lines] if idx is not None else text[-lines:]
        for ln in excerpt:
            print("    " + ln[:200])

    def pytest(self, name: str, extra: list[str], junit: str | None = None) -> dict[str, Any]:
        xml = VERIFICATION / (junit or f"{self.mode}-pytest.xml")
        cmd = [
            _python(),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={xml}",
            *extra,
        ]
        step = self.run(name, cmd, BACKEND)
        step.update(_junit_counts(xml))
        # the marker filter this step ACTUALLY used — authority reads the
        # executed selection, never the declared tier (AC-01A)
        step["markerExpression"] = extra[extra.index("-m") + 1] if "-m" in extra else None
        step["junit"] = str(xml.relative_to(ROOT))
        if step["exitCode"] != 0 and step.get("failedTests"):
            print(f"    failed tests ({len(step['failedTests'])}):")
            for tid in step["failedTests"][:20]:
                print(f"      {tid}")
            if step.get("firstFailure"):
                print("    first failure:")
                for ln in step["firstFailure"].splitlines()[:30]:
                    print("      " + ln[:200])
        else:
            print(
                f"        tests: {step.get('testsPassed', '?')} passed, "
                f"{step.get('testsFailed', '?')} failed, "
                f"{step.get('testsSkipped', 0)} skipped"
            )
        return step

    # -- gates ----------------------------------------------------------------- #

    def backend_static(self) -> None:
        # tools are invoked through the interpreter (``-m``) so the same
        # runner works in the local .venv AND on a CI runner where the dev
        # extras are installed into the system Python (no .venv/bin/*)
        py = _python()
        self.run("ruff-check", [py, "-m", "ruff", "check", "."], BACKEND)
        self.run("ruff-format", [py, "-m", "ruff", "format", "--check", "."], BACKEND)
        self.run("mypy", [py, "-m", "mypy", "src"], BACKEND)

    def frontend_full(self) -> None:
        npm = shutil.which("npm") or "npm"
        npx = shutil.which("npx") or "npx"
        self.run("fe-typecheck", [npm, "run", "typecheck"], FRONTEND)
        self.run("fe-lint", [npm, "run", "lint"], FRONTEND)
        self.run("fe-prettier", [npx, "prettier", "--check", "src/**/*.{ts,tsx,css}"], FRONTEND)
        step = self.run("fe-vitest", [npm, "test", "--", "--run"], FRONTEND)
        step.update(_vitest_counts(VERIFICATION / f"{self.mode}-fe-vitest.log"))
        print(
            f"        vitest: {step.get('testsPassed', '?')} passed "
            f"in {step.get('testFiles', '?')} files"
        )
        self.run("fe-build", [npm, "run", "build"], FRONTEND)

    # -- summary ----------------------------------------------------------------- #

    def source_identity(self) -> dict[str, Any]:
        """Start / end identity of the judged source (AC-01A)."""
        end = _source_state()
        return {
            "startHead": self.source_start["head"],
            "endHead": end["head"],
            "startDirty": self.source_start["dirty"],
            "endDirty": end["dirty"],
            "startDigest": self.source_start["digest"],
            "endDigest": end["digest"],
            "unchanged": self.source_start["digest"] == end["digest"],
        }

    def finish(self, extra: dict[str, Any] | None = None) -> int:
        elapsed = round(time.perf_counter() - self.t0, 1)
        backend_tests = [s for s in self.steps if s["name"].startswith("pytest")]
        source = self.source_identity()
        authority = evaluate_authority(
            mode=self.mode,
            steps=self.steps,
            failed=self.failed,
            source=source,
            coverage=(extra or {}).get("collectionCoverage"),
            ci=self.ci,
        )
        summary: dict[str, Any] = {
            "mode": self.mode.upper(),
            **_head(),
            "elapsedSeconds": elapsed,
            # release evidence for ONE clean revision, not "full and no failure"
            "fullAuthority": authority["release"],
            "authority": authority,
            "sourceIdentity": source,
            "ci": self.ci,
            "status": "FAIL" if self.failed else "PASS",
            "backend": {
                "testsPassed": sum(s.get("testsPassed", 0) for s in backend_tests),
                "testsFailed": sum(s.get("testsFailed", 0) for s in backend_tests),
                "testsSkipped": sum(s.get("testsSkipped", 0) for s in backend_tests),
                "ruff": _status(self.steps, "ruff-check"),
                "format": _status(self.steps, "ruff-format"),
                "mypy": _status(self.steps, "mypy"),
            },
            "frontend": {
                "typecheck": _status(self.steps, "fe-typecheck"),
                "lint": _status(self.steps, "fe-lint"),
                "prettier": _status(self.steps, "fe-prettier"),
                "vitest": _status(self.steps, "fe-vitest"),
                "build": _status(self.steps, "fe-build"),
                "testsPassed": next(
                    (s.get("testsPassed") for s in self.steps if s["name"] == "fe-vitest"), None
                ),
            },
            "steps": self.steps,
            "failedSteps": [s["name"] for s in self.steps if s["status"] == "FAIL"],
            "failedTests": [t for s in backend_tests for t in s.get("failedTests", [])],
            **(extra or {}),
        }
        out = VERIFICATION / "verification-summary.json"
        out.write_text(json.dumps(summary, indent=1, sort_keys=True), encoding="utf-8")
        components = [k for k, v in authority["components"].items() if v]
        blocked = (
            ""
            if authority["release"]
            else (
                (f" [component OK: {', '.join(components)}]" if components else "")
                + " ← "
                + ", ".join(authority["reasons"][:4])
            )
        )
        print(
            f"{summary['mode']}: {summary['status']} in {elapsed} s "
            f"(backend {summary['backend']['testsPassed']} passed / "
            f"{summary['backend']['testsFailed']} failed; "
            f"head {summary['gitHead'][:10]}{' DIRTY' if summary['gitDirty'] else ''}; "
            f"releaseAuthority={authority['release']}{blocked}) → {_display_path(out)}"
        )
        return 1 if self.failed else 0


def _status(steps: list[dict[str, Any]], name: str) -> str:
    for s in steps:
        if s["name"] == name:
            return str(s["status"])
    return "NOT_RUN"


def _junit_counts(xml: Path) -> dict[str, Any]:
    if not xml.exists():
        return {"testsPassed": 0, "testsFailed": 0, "testsSkipped": 0, "failedTests": []}
    root = ET.parse(xml).getroot()
    failed: list[str] = []
    first_failure: str | None = None
    passed = skipped = 0
    for tc in root.iter("testcase"):
        cls, name = tc.get("classname", ""), tc.get("name", "")
        tid = f"{cls.replace('.', '/', 1) if cls.startswith('tests.') else cls}::{name}"
        fail = tc.find("failure")
        err = tc.find("error")
        if fail is not None or err is not None:
            failed.append(tid)
            if first_failure is None:
                node = fail if fail is not None else err
                first_failure = (node.get("message") or "") + "\n" + (node.text or "")
        elif tc.find("skipped") is not None:
            skipped += 1
        else:
            passed += 1
    return {
        "testsPassed": passed,
        "testsFailed": len(failed),
        "testsSkipped": skipped,
        "failedTests": failed,
        "firstFailure": first_failure,
    }


def _vitest_counts(log: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not log.exists():
        return out
    for ln in log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.search(r"Test Files\s+(\d+) passed", ln)
        if m:
            out["testFiles"] = int(m.group(1))
        m = re.search(r"^\s*Tests\s+(\d+) passed", ln)
        if m:
            out["testsPassed"] = int(m.group(1))
    return out


# -- collection coverage (VA-01 §14–16) ------------------------------------------ #


def _collect(backend: Path, expr: str | None) -> list[str]:
    # NOTE: pyproject addopts already carries -q; a second -q (-qq) would print
    # per-file counts instead of node ids, so collection passes no -q here.
    cmd = [_python(), "-m", "pytest", "--collect-only", "-p", "no:cacheprovider"]
    if expr:
        cmd += ["-m", expr]
    proc = subprocess.run(cmd, cwd=backend, capture_output=True, text=True)
    ids = [ln.strip() for ln in proc.stdout.splitlines() if "::" in ln and not ln.startswith(" ")]
    if proc.returncode not in (0, 5):  # 5 = no tests collected
        raise RuntimeError(
            f"collect-only failed ({proc.returncode}):\n"
            f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
        )
    return ids


def collection_coverage(backend: Path = BACKEND) -> dict[str, Any]:
    everything = _collect(backend, None)
    full = _collect(backend, None)  # FULL is UNFILTERED by construction; proven, not assumed
    fast = _collect(backend, FAST_EXPR)
    excluded = _collect(backend, EXCLUDED_EXPR)
    s_all, s_full, s_fast, s_exc = set(everything), set(full), set(fast), set(excluded)
    report = {
        "fastExpression": FAST_EXPR,
        "excludedExpression": EXCLUDED_EXPR,
        "collectedAll": len(s_all),
        "collectedFull": len(s_full),
        "collectedFast": len(s_fast),
        "excludedFromFast": len(s_exc),
        "missingFromFull": sorted(s_all - s_full),
        "unexpectedInFull": sorted(s_full - s_all),
        "excludedNotInFull": sorted(s_exc - s_full),
        "fastAndExcludedOverlap": sorted(s_fast & s_exc),
        "fastUnionExcludedEqualsFull": (s_fast | s_exc) == s_full,
        "excludedFromFastIds": sorted(s_exc),
    }
    (VERIFICATION).mkdir(parents=True, exist_ok=True)
    (VERIFICATION / "collect-all.txt").write_text("\n".join(sorted(s_all)) + "\n", encoding="utf-8")
    (VERIFICATION / "collect-fast.txt").write_text(
        "\n".join(sorted(s_fast)) + "\n", encoding="utf-8"
    )
    (VERIFICATION / "collect-excluded.txt").write_text(
        "\n".join(sorted(s_exc)) + "\n", encoding="utf-8"
    )
    return report


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def cmd_authority(args: argparse.Namespace) -> int:
    """Combine component summaries into ONE release verdict (AC-01A).

    Reads verification-summary.json files (a backend-only FULL run and a
    frontend FULL run, say), labels each by its filename and prints which
    component supplied every required gate. Exit code 1 when authority is
    withheld, so it can later serve as a single CI release gate.
    """
    summaries: list[dict[str, Any]] = []
    for raw in args.summaries:
        path = Path(raw)
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("label", path.stem)
        summaries.append(data)
    verdict = aggregate_authority(summaries)
    VERIFICATION.mkdir(parents=True, exist_ok=True)
    out = VERIFICATION / "release-authority.json"
    out.write_text(json.dumps(verdict, indent=1, sort_keys=True), encoding="utf-8")
    print(
        f"release authority: {verdict['release']} "
        f"for {verdict['certifiedSha']} ({', '.join(verdict['certifiedShaKinds'])})"
    )
    for gate, owner in verdict["gateSource"].items():
        print(f"  {'PASS   ' if owner else 'MISSING'} {gate}{' ← ' + owner if owner else ''}")
    for reason in verdict["reasons"]:
        print(f"  BLOCKED {reason}")
    print(f"→ {_display_path(out)}")
    return 0 if verdict["release"] else 1


def cmd_collect_full() -> int:
    rep = collection_coverage()
    ok = (
        not rep["missingFromFull"]
        and not rep["unexpectedInFull"]
        and not rep["excludedNotInFull"]
        and not rep["fastAndExcludedOverlap"]
        and rep["fastUnionExcludedEqualsFull"]
    )
    print(
        f"collected all={rep['collectedAll']} full={rep['collectedFull']} "
        f"fast={rep['collectedFast']} "
        f"excludedFromFast={rep['excludedFromFast']} missingFromFull={len(rep['missingFromFull'])} "
        f"excludedNotInFull={len(rep['excludedNotInFull'])} "
        f"overlap={len(rep['fastAndExcludedOverlap'])} "
        f"→ {'PASS' if ok else 'FAIL'}"
    )
    (VERIFICATION / "collection-coverage.json").write_text(
        json.dumps(rep, indent=1), encoding="utf-8"
    )
    return 0 if ok else 1


# -- modes --------------------------------------------------------------------- #


def cmd_fast(args: argparse.Namespace) -> int:
    r = Runner("fast")
    r.backend_static()
    r.pytest("pytest-fast", ["-m", FAST_EXPR])
    return r.finish({"tier": "FAST", "pytestExpression": FAST_EXPR})


def cmd_feature(args: argparse.Namespace) -> int:
    r = Runner("feature")
    r.backend_static()
    r.pytest("pytest-feature", ["-m", FEATURE_EXPR])
    return r.finish({"tier": "FEATURE", "pytestExpression": FEATURE_EXPR})


def cmd_full(args: argparse.Namespace) -> int:
    r = Runner("full")
    # the exact gate list of the old CI (.github/workflows/ci.yml), unfiltered
    r.backend_static()
    r.pytest("pytest-full", [])
    if not args.backend_only:
        r.frontend_full()
    extra: dict[str, Any] = {"tier": "FULL", "pytestExpression": None}
    cov = collection_coverage()
    # what the unfiltered run actually EXECUTED (the collected-vs-collected
    # comparison is true by construction; this one is not)
    full_step = next((s for s in r.steps if s["name"] == "pytest-full"), None)
    if full_step is not None:
        cov["executedFull"] = (
            int(full_step.get("testsPassed", 0))
            + int(full_step.get("testsFailed", 0))
            + int(full_step.get("testsSkipped", 0))
        )
    extra["collectionCoverage"] = {k: v for k, v in cov.items() if k != "excludedFromFastIds"}
    # ONE judgement of the proof: the printed line, the exit code and the
    # authority verdict cannot disagree (they used to check 2, 5 and 6
    # conditions respectively)
    coverage_ok = _coverage_ok(extra["collectionCoverage"])
    r.steps.append(
        {
            "name": "collection-coverage",
            "command": "verify.collection_coverage()",
            "cwd": "backend",
            "exitCode": 0 if coverage_ok else 1,
            "status": "PASS" if coverage_ok else "FAIL",
            "elapsedSeconds": None,
        }
    )
    if not coverage_ok:
        r.failed = True
        print(
            "  FAIL  collection coverage: "
            f"missingFromFull={cov['missingFromFull']} "
            f"excludedNotInFull={cov['excludedNotInFull']} "
            f"overlap={cov['fastAndExcludedOverlap']} "
            f"fastUnionExcludedEqualsFull={cov['fastUnionExcludedEqualsFull']} "
            f"executed={cov.get('executedFull')} collected={cov['collectedFull']}"
        )
    else:
        print(
            f"  PASS  collection coverage (all={cov['collectedAll']} "
            f"full={cov['collectedFull']} fast={cov['collectedFast']} "
            f"executed={cov.get('executedFull')})"
        )
    if args.closeout:
        extra["closeout"] = closeout(r)
    return r.finish(extra)


def closeout(r: Runner) -> dict[str, Any]:
    """Phase closeout gates with COMPACT summaries (raw detail stays on disk)."""
    py = _python()
    env = {"PYTHONPATH": "src"}
    out: dict[str, Any] = {}
    # layout-v2 golden: regenerate into .verification and compare against the committed baseline
    label = "closeout_layout_v2"
    r.run(
        "golden-layout-v2",
        [
            py,
            "-m",
            "minegen.regression",
            "layout-v2",
            "--suite",
            "full",
            "--label",
            label,
            "--out",
            str(VERIFICATION),
        ],
        BACKEND,
        env,
    )
    baseline = _latest_golden("phase*_layout_v2.json")
    if baseline:
        r.run(
            "golden-layout-v2-compare",
            [
                py,
                "-m",
                "minegen.regression",
                "layout-v2-compare",
                str(baseline),
                str(VERIFICATION / f"{label}.json"),
            ],
            BACKEND,
            env,
        )
        out["layoutGolden"] = _layout_compare_summary(
            VERIFICATION / f"{r.mode}-golden-layout-v2-compare.log", baseline
        )
    # 32-seed survey → survey-detail.json + compact summary vs committed survey golden
    r.run(
        "survey-32",
        [
            py,
            "-m",
            "minegen.regression",
            "warped-seeds",
            "--label",
            "survey-detail",
            "--out",
            str(VERIFICATION),
        ],
        BACKEND,
        env,
    )
    out["survey"] = _survey_summary(
        VERIFICATION / "survey-detail.json", _latest_golden("phase*_warped_seed_survey.json")
    )
    # screen audit
    r.run(
        "screen-audit",
        [
            py,
            "-m",
            "minegen.regression",
            "layout-v2-screen-audit",
            "--suite",
            "full",
            "--label",
            "screen-audit-detail",
            "--out",
            str(VERIFICATION),
        ],
        BACKEND,
        env,
    )
    out["screenAudit"] = _screen_audit_summary(
        VERIFICATION / "screen-audit-detail.json", _latest_golden("phase*_screen_audit.json")
    )
    if getattr(r, "legacy", False):
        r.run(
            "legacy-22",
            [
                py,
                "-m",
                "minegen.regression",
                "run",
                "--suite",
                "full",
                "--label",
                "legacy-detail",
                "--out",
                str(VERIFICATION),
            ],
            BACKEND,
            env,
        )
        base = BACKEND / "golden" / "phase20b_closeout_full.json"
        r.run(
            "legacy-22-compare",
            [
                py,
                "-m",
                "minegen.regression",
                "compare",
                str(base),
                str(VERIFICATION / "legacy-detail.json"),
                "--out",
                str(VERIFICATION / "legacy-compare"),
            ],
            BACKEND,
            env,
        )
        out["legacy22"] = _legacy_compare_summary(VERIFICATION / f"{r.mode}-legacy-22-compare.log")
    (VERIFICATION / "golden-summary.json").write_text(
        json.dumps(out, indent=1, sort_keys=True), encoding="utf-8"
    )
    for k, v in out.items():
        print(
            f"  {k}: "
            + json.dumps(
                {kk: vv for kk, vv in v.items() if not isinstance(vv, list) or len(vv) <= 12}
            )
        )
    return out


def _latest_golden(pattern: str) -> Path | None:
    files = sorted((BACKEND / "golden").glob(pattern))
    return files[-1] if files else None


def _layout_compare_summary(log: Path, baseline: Path) -> dict[str, Any]:
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    try:
        data = json.loads(text[text.index("{") :])
    except Exception:
        return {"baseline": baseline.name, "parseError": True, "log": str(log.relative_to(ROOT))}
    regs = data.get("contractRegressions", [])
    drift = data.get("metricDrift", [])
    return {
        "baseline": baseline.name,
        "contractRegressions": len(regs),
        "contractRegressionKeys": sorted({str(x).split(":")[0] for x in regs})[:40],
        "metricChanges": len(drift),
        "log": str(log.relative_to(ROOT)),
    }


def _survey_summary(detail: Path, baseline: Path | None) -> dict[str, Any]:
    if not detail.exists():
        return {"missing": True}
    cur = json.loads(detail.read_text(encoding="utf-8"))
    out: dict[str, Any] = {
        "successCount": cur["successCount"],
        "failureCount": cur["noFeasibleCount"],
        "failureReasonHistogram": cur["dominantFailureHistogram"],
        "runtimeSeconds": round(cur["totalRuntimeSeconds"], 1),
        "detail": str(detail.relative_to(ROOT)),
    }
    if baseline and baseline.exists():
        base = json.loads(baseline.read_text(encoding="utf-8"))
        b = {r["seed"]: r for r in base["rows"]}
        c = {r["seed"]: r for r in cur["rows"]}
        keys = (
            "status",
            "winnerId",
            "detailedFeasibleCount",
            "dominantFailure",
            "bestAccessibleLevels",
        )
        changed = [s for s in sorted(c) if s in b and any(b[s].get(k) != c[s].get(k) for k in keys)]
        out.update(
            {
                "baseline": baseline.name,
                "changedSeeds": changed,
                "recoveredSeeds": [
                    s
                    for s in changed
                    if b[s].get("status") != "SUCCESS" and c[s].get("status") == "SUCCESS"
                ],
                "newFailureSeeds": [
                    s
                    for s in changed
                    if b[s].get("status") == "SUCCESS" and c[s].get("status") != "SUCCESS"
                ],
            }
        )
    return out


def _screen_audit_summary(detail: Path, baseline: Path | None) -> dict[str, Any]:
    if not detail.exists():
        return {"missing": True}
    cur = json.loads(detail.read_text(encoding="utf-8"))
    out: dict[str, Any] = {
        "totalFalseBlocks": cur["totalFalseBlocks"],
        "insideProductionShortlist": cur["falseBlocksInsideProductionShortlist"],
        "exactCasesFalseBlocks": {
            r["key"]: r.get("screenBlockedButStage4Served")
            for r in cur["cases"]
            if r.get("clearanceBasis") == "EXACT"
        },
        "detail": str(detail.relative_to(ROOT)),
    }
    if baseline and baseline.exists():
        base = json.loads(baseline.read_text(encoding="utf-8"))
        out["baseline"] = baseline.name
        out["changedCases"] = [
            r["key"]
            for r in cur["cases"]
            if next((b for b in base["cases"] if b["key"] == r["key"]), {}).get(
                "screenBlockedButStage4Served"
            )
            != r.get("screenBlockedButStage4Served")
        ]
    return out


def _legacy_compare_summary(log: Path) -> dict[str, Any]:
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    m = re.search(r"HARD CONTRACT regressions: (\d+)", text)
    n = re.search(r"metric changes: (\d+)", text)
    return {
        "hardContractRegressions": int(m.group(1)) if m else None,
        "metricChanges": int(n.group(1)) if n else None,
        "log": str(log.relative_to(ROOT)) if log.exists() else None,
    }


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Runtime observation only: same-machine stage split for the reference
    cases (never a correctness gate, never a threshold input)."""
    r = Runner("benchmark")
    script = ROOT / "scripts" / "benchmark_reference_cases.py"
    step = r.run(
        "benchmark-reference-cases", [_python(), str(script)], BACKEND, {"PYTHONPATH": "src:."}
    )
    detail = VERIFICATION / "runtime-summary.json"
    extra: dict[str, Any] = {"tier": "BENCHMARK", "correctnessAuthority": False}
    if detail.exists():
        data = json.loads(detail.read_text(encoding="utf-8"))
        extra["runtime"] = data
        for c in data:
            s = c.get("search", {})
            print(
                f"  {c['key']}: search {s.get('totalSeconds')} s "
                f"(cheap {s.get('constructAndCheapSeconds')} / "
                f"detailed {s.get('detailedSeconds')}) "
                f"levels {c.get('levelDevelopmentSeconds')} s rss {c.get('peakRssMbFinal')} MB"
            )
    r.failed = step["exitCode"] != 0
    return r.finish(extra)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("fast")
    sub.add_parser("feature")
    full = sub.add_parser("full")
    full.add_argument(
        "--closeout",
        action="store_true",
        help="also run golden / survey / screen-audit with compact summaries",
    )
    full.add_argument(
        "--legacy",
        action="store_true",
        help="with --closeout: also the 22-case legacy regression (hours)",
    )
    full.add_argument("--backend-only", action="store_true")
    sub.add_parser("benchmark")
    sub.add_parser("collect-full")
    auth = sub.add_parser("authority")
    auth.add_argument(
        "summaries",
        nargs="+",
        help="verification-summary.json files of the components to aggregate",
    )
    args = ap.parse_args(argv)
    if args.mode == "collect-full":
        return cmd_collect_full()
    if args.mode == "authority":
        return cmd_authority(args)
    if args.mode == "fast":
        return cmd_fast(args)
    if args.mode == "feature":
        return cmd_feature(args)
    if args.mode == "benchmark":
        return cmd_benchmark(args)
    if args.mode == "full":
        r_legacy = args.legacy
        Runner.legacy = r_legacy  # type: ignore[attr-defined]
        return cmd_full(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
