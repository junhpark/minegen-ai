"""CLI for the golden-scenario harness.

    python -m minegen.regression run --suite full --label phase17_baseline --out golden
    python -m minegen.regression compare golden/phase17_baseline.json golden/phase18.json \
        --expect gradeProxy --out golden/phase18_vs_phase17
    python -m minegen.regression warped-vein --suite full --label phase19_warped_vein --out golden
    python -m minegen.regression warped-vein-compare golden/a.json golden/b.json
    python -m minegen.regression layout-v2 --suite full --label phase20a_layout_v2 --out golden
    python -m minegen.regression layout-v2-compare golden/a.json golden/b.json

``run`` writes ``<out>/<label>.json`` and ``.csv``; ``compare`` writes
``<out>.json`` and ``<out>.md`` and exits non-zero on any HARD CONTRACT
regression (metric drift never fails the command — it is reported)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from minegen.regression import layout_v2, warped_vein
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

    wv_p = sub.add_parser("warped-vein", help="Phase 19 world-only WARPED_VEIN geometry suite")
    wv_p.add_argument("--suite", choices=["full", "smoke"], default="full")
    wv_p.add_argument("--label", required=True)
    wv_p.add_argument("--out", type=Path, default=Path("golden"))

    wvc_p = sub.add_parser("warped-vein-compare", help="compare two warped-vein reports")
    wvc_p.add_argument("baseline", type=Path)
    wvc_p.add_argument("current", type=Path)

    lv_p = sub.add_parser("layout-v2", help="Phase 20A layout-v2 parametric search suite")
    lv_p.add_argument("--suite", choices=["full", "smoke"], default="full")
    lv_p.add_argument("--label", required=True)
    lv_p.add_argument("--out", type=Path, default=Path("golden"))

    lvc_p = sub.add_parser("layout-v2-compare", help="compare two layout-v2 reports")
    lvc_p.add_argument("baseline", type=Path)
    lvc_p.add_argument("current", type=Path)

    lva_p = sub.add_parser(
        "layout-v2-audit",
        help="closeout v3 §3.E diagnostic: exhaustive vs bounded-shortlist validation",
    )
    lva_p.add_argument("--suite", choices=["full", "smoke"], default="full")
    lva_p.add_argument("--label", required=True)
    lva_p.add_argument("--out", type=Path, default=Path("golden"))

    args = parser.parse_args(argv)
    if args.command == "layout-v2":
        lv_cases = layout_v2.suite(args.suite)
        print(f"layout-v2 suite={args.suite} cases={len(lv_cases)}")
        lv_report = layout_v2.run_suite(lv_cases, args.label)
        lv_report["gitHead"] = _git_head()
        for rec in lv_report["cases"]:
            c, m, r = rec["contract"], rec["metrics"], rec["runtime"]
            print(
                f"  {rec['key']}: {c.get('orebodyType')} clearance={c.get('clearanceBasis')} "
                f"levels={c.get('serviceableLevelCount')}/{c.get('requiredLevelCount')} "
                f"feasible={c.get('feasibleCount')}/{c.get('candidateCount')} "
                f"winner={c.get('winnerId')} L={m.get('winnerLength3d')} "
                f"({r.get('total', 0):.2f} s)"
            )
        json_path, csv_path = layout_v2.write_report(lv_report, args.out, args.label)
        print(f"wrote {json_path} and {csv_path} ({lv_report['totalRuntimeSeconds']:.1f} s)")
        return 0
    if args.command == "layout-v2-audit":
        audit = layout_v2.audit_shortlist(layout_v2.suite(args.suite), args.label)
        audit["gitHead"] = _git_head()
        for rec in audit["cases"]:
            print(
                f"  {rec['key']}: cheap-feasible={rec.get('cheapFeasibleCount')} "
                f"shortlist={rec.get('shortlistSize')} feasible normal/exhaustive="
                f"{len(rec.get('feasibleNormal', []))}/{len(rec.get('feasibleExhaustive', []))} "
                f"winner={rec.get('winnerNormal')} exhaustive={rec.get('winnerExhaustive')} "
                f"missedWinner={rec.get('winnerMissedByShortlist')} "
                f"missedFamilies={rec.get('missedFamilies')}"
            )
        args.out.mkdir(parents=True, exist_ok=True)
        audit_path = args.out / f"{args.label}.json"
        audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
        print(f"wrote {audit_path} ({audit['totalRuntimeSeconds']:.1f} s)")
        return 0
    if args.command == "layout-v2-compare":
        cmp_lv = layout_v2.compare_reports(
            layout_v2.load_report(args.baseline), layout_v2.load_report(args.current)
        )
        print(json.dumps(cmp_lv, indent=2))
        return 1 if cmp_lv["contractRegressions"] else 0
    if args.command == "warped-vein":
        wv_cases = warped_vein.suite(args.suite)
        print(f"warped-vein suite={args.suite} cases={len(wv_cases)}")
        report = warped_vein.run_suite(wv_cases, args.label)
        report["gitHead"] = _git_head()
        for rec in report["cases"]:
            c, m, r = rec["contract"], rec["metrics"], rec["runtime"]
            print(
                f"  {rec['key']}: realized={c.get('realized')} mesh={c.get('meshVertices')}v/"
                f"{c.get('meshTriangles')}t watertight={c.get('meshWatertight')} "
                f"volume={m.get('volumeM3', 0) / 1e6:.3f} Mm3 payload="
                f"{m.get('scenePayloadBytes', 0) / 1e6:.2f} MB ({r.get('total', 0):.2f} s)"
            )
        json_path, csv_path = warped_vein.write_report(report, args.out, args.label)
        print(f"wrote {json_path} and {csv_path} ({report['totalRuntimeSeconds']:.1f} s)")
        return 0
    if args.command == "warped-vein-compare":
        cmp_wv = warped_vein.compare_reports(
            warped_vein.load_report(args.baseline), warped_vein.load_report(args.current)
        )
        print(json.dumps(cmp_wv, indent=2))
        return 1 if cmp_wv["contractRegressions"] else 0
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
        args.out.parent.mkdir(parents=True, exist_ok=True)
        Path(f"{args.out}.json").write_text(json.dumps(cmp, indent=2), encoding="utf-8")
        Path(f"{args.out}.md").write_text(text, encoding="utf-8")
    return 1 if cmp["summary"]["contractRegressions"] else 0


if __name__ == "__main__":
    sys.exit(main())
