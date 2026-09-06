"""Phase 20C.1 closeout A-2: recompute the POOLED rank AUC of an existing
yield-audit artifact from its own per-case rows.

``phase20c1_q_yield_before.json`` (the commit-S search) and
``phase20c1_q_yield_after.json`` (the commit-Q search) are HISTORICAL
artifacts: re-running the production search now would fold every later
commit into them and change what they document. The A-1 pooling bug lives
entirely in the summary, and each family's ``rows`` already carry
``familyRank`` and ``detailedPass`` per case — everything the Mann–Whitney
counts need — so the corrected pooled value is recomputed deterministically
from the file and only the ``pooled`` block is rewritten. Per-case values
(``rankAuc``, ``rankPairs``, ``rows``, every diagnostic) are untouched, and
the file records that it was repooled rather than re-run.

    python -m minegen.regression.repool golden/phase20c1_q_yield_before.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from minegen.regression.layout_v2 import pooled_rank_auc

REPOOL_NOTE = (
    "Phase 20C.1 closeout A-2: the `pooled` block was recomputed from this "
    "file's own per-case rows with pair-weighted within-case pooling "
    "(Σ wins / Σ pairs). The production search was NOT re-run; every "
    "per-case value, row and diagnostic is the original measurement."
)


def repool(report: dict[str, Any]) -> dict[str, Any]:
    """Rewrite ``report['pooled']`` from ``report['cases'][*]['families']``."""
    per_family: dict[str, list[tuple[list[int], list[int]]]] = {}
    for case in report.get("cases", []):
        for fam, block in (case.get("families") or {}).items():
            passes = [int(r["familyRank"]) for r in block["rows"] if r["detailedPass"]]
            fails = [int(r["familyRank"]) for r in block["rows"] if not r["detailedPass"]]
            per_family.setdefault(fam, []).append((passes, fails))
    pooled: dict[str, Any] = {}
    for fam, per_case in per_family.items():
        out = pooled_rank_auc(per_case)
        out["passCount"] = sum(len(p) for p, _ in per_case)
        out["failCount"] = sum(len(f) for _, f in per_case)
        pooled[fam] = out
    report["pooled"] = pooled
    report["pooledCorrection"] = REPOOL_NOTE
    return report


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        return 2
    for name in args:
        path = Path(name)
        report = json.loads(path.read_text(encoding="utf-8"))
        before = json.dumps(report.get("pooled"), sort_keys=True)
        repool(report)
        path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"{path}\n  before {before}\n  after  {json.dumps(report['pooled'], sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
