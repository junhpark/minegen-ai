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

Output policy: on success only exit code / counts / elapsed are printed; on
failure only the failed test ids, the first actionable traceback and the log
path. Raw logs and the machine-readable summary live under
backend/.verification/ (git-ignored):

    backend/.verification/verification-summary.json
    backend/.verification/<mode>-<step>.log
    backend/.verification/<mode>-pytest.xml

FAST excludes the heavy marker groups; FULL runs pytest UNFILTERED, so its
correctness scope is never smaller than the old ``pytest -q``. A FULL result
is release evidence only for the HEAD it ran on (``gitHead`` / ``gitDirty``
in the summary).
"""

from __future__ import annotations

import argparse
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


class Runner:
    def __init__(self, mode: str, verbose: bool = False) -> None:
        self.mode = mode
        self.verbose = verbose
        self.t0 = time.perf_counter()
        self.steps: list[dict[str, Any]] = []
        self.failed = False
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

    def finish(self, extra: dict[str, Any] | None = None) -> int:
        elapsed = round(time.perf_counter() - self.t0, 1)
        backend_tests = [s for s in self.steps if s["name"].startswith("pytest")]
        summary: dict[str, Any] = {
            "mode": self.mode.upper(),
            **_head(),
            "elapsedSeconds": elapsed,
            "fullAuthority": self.mode == "full" and not self.failed,
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
        print(
            f"{summary['mode']}: {summary['status']} in {elapsed} s "
            f"(backend {summary['backend']['testsPassed']} passed / "
            f"{summary['backend']['testsFailed']} failed; "
            f"head {summary['gitHead'][:10]}{' DIRTY' if summary['gitDirty'] else ''}; "
            f"fullAuthority={summary['fullAuthority']}) → {out.relative_to(ROOT)}"
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
    extra["collectionCoverage"] = {k: v for k, v in cov.items() if k != "excludedFromFastIds"}
    if cov["missingFromFull"] or cov["excludedNotInFull"]:
        r.failed = True
        print(
            "  FAIL  collection coverage: "
            f"missingFromFull={cov['missingFromFull']} "
            f"excludedNotInFull={cov['excludedNotInFull']}"
        )
    else:
        print(
            f"  PASS  collection coverage (all={cov['collectedAll']} "
            f"full={cov['collectedFull']} fast={cov['collectedFast']})"
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
    args = ap.parse_args(argv)
    if args.mode == "collect-full":
        return cmd_collect_full()
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
