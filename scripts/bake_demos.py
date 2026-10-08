#!/usr/bin/env python
"""Bake the demo mines (hardening PR-2 H4) into ``data/demos/``.

Run from the repository root:

    cd backend && PYTHONPATH=src:. .venv/bin/python ../scripts/bake_demos.py
    cd backend && PYTHONPATH=src:. .venv/bin/python ../scripts/bake_demos.py --only demo-warped-vein
    cd backend && PYTHONPATH=src:. .venv/bin/python ../scripts/bake_demos.py --if-missing

Every demo is generated through the application's own HTTP routes
(``minegen.demos.bake``) from its preset + seed recipe, with the DEMO /
SYNTHETIC planning-economics assumptions, then ``index.json`` is written.
``GET /api/v1/demos`` lists the result; the scenario store serves a demo in
place, read-only.

PR #54 review B1: ``--if-missing`` bakes ONLY the recipes the catalogue does
not list as available (``services/demo_materializer.py`` — the same
materializer the backend runs in the background at startup) and exits at
once when all three are there; ``scripts/bin/dev-setup`` runs it, so a fresh
checkout lists the demos before the servers are ever started. ``data/`` stays
git-ignored: the demos are baked on the host that serves them (rule 60 stat
identity), never copied.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND / "src"))

from minegen.config import get_settings  # noqa: E402
from minegen.demos.bake import DEMO_RECIPES, DemoBaker, git_commit, write_index  # noqa: E402
from minegen.services.demo_materializer import DemoMaterializer  # noqa: E402
from minegen.services.demo_service import read_demo_index  # noqa: E402


def _log(message: str) -> None:
    print(f"  {message}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=get_settings().demos_dir,
        help="demos directory (default: <MINEGEN_DATA_DIR>/demos)",
    )
    parser.add_argument(
        "--only", action="append", default=[], help="bake only this recipe id (repeatable)"
    )
    parser.add_argument(
        "--if-missing",
        action="store_true",
        help="bake only the recipes the catalogue does not list as available; exit 0 at once "
        "when every demo is there (what scripts/bin/dev-setup runs)",
    )
    args = parser.parse_args(argv)
    out: Path = args.out
    if args.if_missing:
        if args.only:
            parser.error("--if-missing and --only are exclusive")
        materializer = DemoMaterializer(out, get_settings().scenarios_dir)
        missing = [r.id for r in materializer.missing()]
        if not missing:
            print(f"demos: all {len(DEMO_RECIPES)} baked under {out} — nothing to do")
            return 0
        print(f"demos: baking {len(missing)} missing recipe(s) into {out}: {', '.join(missing)}")
        t0 = time.monotonic()
        state = materializer.bake_missing(log=_log)
        print(f"demos: {state.status} in {time.monotonic() - t0:.1f} s")
        for recipe_id, reason in state.failed_recipes.items():
            print(f"demos: {recipe_id} FAILED — {reason}", file=sys.stderr)
        return 0 if state.status == "DONE" else 1
    recipes = [r for r in DEMO_RECIPES if not args.only or r.id in args.only]
    unknown = set(args.only) - {r.id for r in DEMO_RECIPES}
    if unknown:
        parser.error(f"unknown recipe id(s): {sorted(unknown)}")
    baker = DemoBaker(out)
    try:
        # keep the entries of recipes not re-baked this run
        existing = read_demo_index(out)
        kept = {e.id: e for e in (existing.demos if existing else [])}
        for recipe in recipes:
            t0 = time.monotonic()
            entry = baker.bake(recipe, log=_log)
            kept[entry.id] = entry
            print(f"baked {recipe.id} in {time.monotonic() - t0:.1f} s", flush=True)
        order = [r.id for r in DEMO_RECIPES]
        entries = [kept[i] for i in order if i in kept] + [
            e for i, e in kept.items() if i not in order
        ]
        path = write_index(out, entries, git_commit(ROOT))
        print(f"wrote {path} ({len(entries)} demos)")
    finally:
        baker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
