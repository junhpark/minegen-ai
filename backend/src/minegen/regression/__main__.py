"""CLI for the golden-scenario harness.

    python -m minegen.regression run --suite full --label phase17_baseline --out golden
    python -m minegen.regression compare golden/phase17_baseline.json golden/phase18.json \
        --expect gradeProxy --out golden/phase18_vs_phase17

``run`` writes ``<out>/<label>.json`` and ``.csv``; ``compare`` writes
``<out>.json`` and ``<out>.md`` and exits non-zero on any HARD CONTRACT
regression (metric drift never fails the command — it is reported)."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from minegen.regression.golden import (
    compare_reports,
    format_comparison,
    load_report,
    run_suite,
    suite,
    write_report,
)


def _git_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10
        )
        return out.stdout.strip()
    except Exception:  # advisory metadata only
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m minegen.regression")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a suite and write a report")
    run_p.add_argument("--suite", choices=["full", "smoke"], default="full")
    run_p.add_argument("--label", required=True)
    run_p.add_argument("--out", type=Path, default=Path("golden"))
    run_p.add_argument("--root", type=Path, default=None, help="scenario store root (temp)")
    run_p.add_argument("--only", nargs="*", default=None, help="restrict to these case keys")

    cmp_p = sub.add_parser("compare", help="compare two reports")
    cmp_p.add_argument("baseline", type=Path)
    cmp_p.add_argument("current", type=Path)
    cmp_p.add_argument("--expect", nargs="*", default=[], help="metrics expected to change")
    cmp_p.add_argument("--out", type=Path, default=None, help="report path without extension")

    args = parser.parse_args(argv)
    if args.command == "run":
        cases = suite(args.suite)
        if args.only:
            cases = [c for c in cases if c.key in set(args.only)]
        root = args.root or Path(tempfile.mkdtemp(prefix="minegen-golden-"))
        print(f"suite={args.suite} cases={len(cases)} store={root}")
        report = run_suite(cases, root, args.label, on_progress=print)
        report["gitHead"] = _git_head()
        json_path, csv_path = write_report(report, args.out, args.label)
        print(f"wrote {json_path} and {csv_path} ({report['totalRuntimeSeconds']:.1f} s)")
        return 0
    baseline = load_report(args.baseline)
    current = load_report(args.current)
    cmp = compare_reports(baseline, current, set(args.expect))
    text = format_comparison(cmp)
    print(text)
    if args.out is not None:
        import json

        args.out.parent.mkdir(parents=True, exist_ok=True)
        Path(f"{args.out}.json").write_text(json.dumps(cmp, indent=2), encoding="utf-8")
        Path(f"{args.out}.md").write_text(text, encoding="utf-8")
    return 1 if cmp["summary"]["contractRegressions"] else 0


if __name__ == "__main__":
    sys.exit(main())
