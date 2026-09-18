#!/usr/bin/env python
"""Generate the AC-01G layout-v2 CHARACTERIZATION baselines under
backend/tests/fixtures/characterization/ — LAYER A, the DISCRETE record.

A characterization baseline records what ``LayoutV2Search`` DID at the freeze
SHA, observation by observation (C1 enumeration … C6 key paths), so a later
refactor cannot change layout-v2 behaviour silently. It is not an engineering
specification and proves no constraint correct.

Since the AC-01G review correction the committed baseline is the DISCRETE
projection (``tests.characterization_support.discrete_observations``): every
float leaf and numeric list is REMOVED, the declared-literal subtrees are kept
verbatim, and the float-hashing C6 sha is dropped. Float / geometry
equivalence is NOT committed: it is proved at test time, same runner, base
vs HEAD (``scripts/characterization_observe.py``), because an IEEE bit
pattern turned out not to be a property of the source tree across GitHub
runners (PR #35 review: identical tree, FULL green, ordinary CI red).

It is generated ONCE, at the freeze SHA, and is NEVER auto-rewritten (rule
181's cached-fixture discipline, applied to a freeze):

  * the baseline carries the generating git SHA and a content fingerprint
    over its own body; ``tests/characterization_support.load_baseline``
    fails loudly on a hand-edited file;
  * the freeze SHA is ALSO pinned as ``BASELINE_GIT_SHA`` in
    ``backend/tests/characterization_support.py``, so a regeneration at
    another HEAD only takes effect through a reviewed source edit;
  * this script refuses to overwrite an existing baseline without
    ``--force``.

Run from the repository root:
    cd backend && PYTHONPATH=src:. .venv/bin/python \
        ../scripts/generate_characterization_baseline.py

REPRODUCING the committed baselines (AC-01G Stage D, D4). A freeze must be
falsifiable from inside the repository, so the committed baselines are
generated from a CLEAN archive of the freeze SHA, never from a working tree:

    SHA=3951d98d91235facb6b95e9d646f0dc62b7c9835
    P=$(mktemp -d)
    mkdir -p "$P/scripts"
    git archive $SHA backend/src | tar -x -C "$P"
    cp -r backend/tests backend/golden "$P/backend/"
    rm -f "$P"/backend/tests/fixtures/characterization/*.json
    cp scripts/generate_characterization_baseline.py "$P/scripts/"
    ln -s "$PWD/backend/.venv" "$P/backend/.venv"
    cd "$P/backend" && PYTHONPATH=src:. .venv/bin/python \
        ../scripts/generate_characterization_baseline.py --force --source-sha $SHA

The production code under test is then the archive's; only the generator and
its projections come from the working tree. The content fingerprints it
prints must equal the committed ``metadata.contentFingerprint`` of every case
(the body is discrete, so this holds on any platform).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(BACKEND))

from tests.characterization_support import (  # noqa: E402
    CASE_KEYS,
    CHARACTERIZATION_SCHEMA_VERSION,
    FIXTURE_DIR,
    baseline_path,
    content_fingerprint,
    discrete_observations,
)

from minegen.layout.search import LayoutV2Search  # noqa: E402
from minegen.regression.layout_v2 import case_by_key  # noqa: E402
from minegen.world.synthetic_world import generate_world  # noqa: E402

#: 2 = LAYER A discrete record (see module docstring)
FIXTURE_VERSION = 2

#: how each case's inputs are obtained AT TEST TIME. WARPED_VEIN-301 is the
#: session-shared ``warped_301`` / ``warped_301_search`` pair (identical
#: inputs, so FULL pays for that 55 s search once); TABULAR-REFERENCE has no
#: shared fixture and is built module-scoped from the golden case.
ROUTES = {
    "TABULAR-REFERENCE": (
        "minegen.regression.layout_v2.case_by_key('TABULAR-REFERENCE').realize() "
        "→ generate_world → LayoutV2Search.run() (module-scoped; no shared fixture exists)"
    ),
    "WARPED_VEIN-301": (
        "tests/conftest.py session fixtures warped_301 / warped_301_search "
        "(identical inputs to case_by_key('WARPED_VEIN-301').realize(), asserted in the test)"
    ),
    # AC-01G Stage D (D4): the two behaviours the first pair could not reach —
    # the NO_FEASIBLE_CANDIDATE terminal branch with winnerId None, and a
    # SWITCHBACK-with-hairpin-station winner over a FamilyInfeasible-dominated
    # population. Both are clean module-scoped searches, ≈ 6 s and ≈ 30 s.
    "ACCESS-INFEASIBLE": (
        "minegen.regression.layout_v2.case_by_key('ACCESS-INFEASIBLE').realize() "
        "→ generate_world → LayoutV2Search.run() (module-scoped; no shared fixture exists)"
    ),
    "GEOMETRY-STRESS": (
        "minegen.regression.layout_v2.case_by_key('GEOMETRY-STRESS').realize() "
        "→ generate_world → LayoutV2Search.run() (module-scoped; no shared fixture exists)"
    ),
}


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # pragma: no cover - git absent
        return "unknown"


def _dirty() -> bool:
    try:
        return bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
        )
    except Exception:  # pragma: no cover - git absent
        return True


def build_case(case_key: str, git_sha: str) -> dict[str, Any]:
    case = case_by_key(case_key)
    sc = case.realize()
    world = generate_world(sc)
    result = LayoutV2Search(sc, world).run()
    body: dict[str, Any] = {
        "case": {
            "key": case.key,
            "preset": case.preset.value,
            "seed": case.seed,
            "faultCount": case.fault_count,
            "overrides": [list(o) for o in case.overrides],
            "note": case.note,
            "orebodyType": sc.orebody.orebody_type.value,
        },
        "route": ROUTES[case_key],
        "observations": discrete_observations(result.to_dict()),
    }
    meta = {
        "fixtureVersion": FIXTURE_VERSION,
        "schemaVersion": CHARACTERIZATION_SCHEMA_VERSION,
        "caseKey": case_key,
        "generatedFromGitSha": git_sha,
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "contentFingerprint": content_fingerprint(git_sha, body),
        "authority": (
            "CHARACTERIZATION FREEZE, LAYER A (discrete) — records the observed layout-v2 "
            "DECISION outputs at the freeze SHA: ids, order, status, reasons, shortlist, "
            "ranking, winner, authority, basis, counts, key paths, declared literals. Floats "
            "are removed, never rounded; their equivalence is proved same-runner at test "
            "time. Not an engineering specification; a difference is a signal to explain, "
            "never on its own a defect. Never auto-rewritten."
        ),
    }
    return {"metadata": meta, **body}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="overwrite an existing baseline")
    ap.add_argument("--case", action="append", choices=list(CASE_KEYS), help="restrict to a case")
    ap.add_argument(
        "--source-sha",
        help=(
            "record this SHA as the generating revision instead of the working tree's HEAD. "
            "For the PINNED-ARCHIVE workflow only: the production source is a clean "
            "`git archive <sha> backend/src` extracted outside the repository, so `git "
            "rev-parse` cannot see it. This is how a freeze baseline gets provenance a "
            "reviewer can reproduce; it is NOT a way to relabel a baseline."
        ),
    )
    args = ap.parse_args()

    keys = tuple(args.case) if args.case else CASE_KEYS
    git_sha = args.source_sha or _git_sha()
    if args.source_sha:
        print(
            f"recording the PINNED source revision {git_sha[:12]} (--source-sha): the production "
            "code under test is an archive of it, not this working tree",
            file=sys.stderr,
        )
    elif _dirty():
        print(
            f"WARNING: working tree is dirty — the recorded git SHA {git_sha[:12]} does not "
            "identify the generated content",
            file=sys.stderr,
        )
    existing = [k for k in keys if baseline_path(k).exists()]
    if existing and not args.force:
        print(
            "REFUSING to overwrite committed characterization baselines "
            f"({', '.join(existing)}). A freeze baseline is generated ONCE, at the freeze SHA; "
            "regenerating it hides exactly the change it exists to catch. Pass --force only in a "
            "reviewed change that also updates BASELINE_GIT_SHA in "
            "backend/tests/characterization_support.py.",
            file=sys.stderr,
        )
        return 2

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for key in keys:
        data = build_case(key, git_sha)
        path = baseline_path(key)
        path.write_text(
            json.dumps(data, indent=1, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )
        obs = data["observations"]
        print(
            f"wrote {path.relative_to(ROOT)} "
            f"candidates={len(obs['c1Enumeration'])} "
            f"shortlist={len(obs['c3Shortlist']['shortlist'])} "
            f"winner={obs['c5Ranking']['winnerId']} "
            f"keyPaths={obs['c6Payload']['keyPathCount']} "
            f"fingerprint={data['metadata']['contentFingerprint'][:12]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
