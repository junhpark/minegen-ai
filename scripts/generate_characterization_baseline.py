#!/usr/bin/env python
"""Generate the AC-01G layout-v2 CHARACTERIZATION baselines under
backend/tests/fixtures/characterization/.

A characterization baseline records what ``LayoutV2Search`` DID at the freeze
SHA, observation by observation (C1 enumeration … C6 payload sha + key
paths), so a later refactor cannot change layout-v2 behaviour silently. It is
not an engineering specification and proves no constraint correct.

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
    observations,
)

from minegen.layout.search import LayoutV2Search  # noqa: E402
from minegen.regression.layout_v2 import case_by_key  # noqa: E402
from minegen.world.synthetic_world import generate_world  # noqa: E402

FIXTURE_VERSION = 1

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
        "observations": observations(result.to_dict()),
    }
    meta = {
        "fixtureVersion": FIXTURE_VERSION,
        "schemaVersion": CHARACTERIZATION_SCHEMA_VERSION,
        "caseKey": case_key,
        "generatedFromGitSha": git_sha,
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "contentFingerprint": content_fingerprint(git_sha, body),
        "authority": (
            "CHARACTERIZATION FREEZE — records observed layout-v2 behaviour at the freeze SHA. "
            "Not an engineering specification; a difference is a signal to explain, never on "
            "its own a defect. Never auto-rewritten."
        ),
    }
    return {"metadata": meta, **body}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="overwrite an existing baseline")
    ap.add_argument("--case", action="append", choices=list(CASE_KEYS), help="restrict to a case")
    args = ap.parse_args()

    keys = tuple(args.case) if args.case else CASE_KEYS
    git_sha = _git_sha()
    if _dirty():
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
            json.dumps(data, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8"
        )
        obs = data["observations"]
        print(
            f"wrote {path.relative_to(ROOT)} "
            f"candidates={len(obs['c1Enumeration'])} "
            f"shortlist={len(obs['c3Shortlist']['shortlist'])} "
            f"winner={obs['c5Ranking']['winnerId']} "
            f"payloadSha={obs['c6Payload']['sha256'][:12]} "
            f"keyPaths={obs['c6Payload']['keyPathCount']} "
            f"fingerprint={data['metadata']['contentFingerprint'][:12]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
