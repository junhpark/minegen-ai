#!/usr/bin/env python
"""Bake the demo mines (hardening PR-2 H4) into ``data/demos/``.

Run from the repository root:

    cd backend && PYTHONPATH=src:. .venv/bin/python ../scripts/bake_demos.py
    cd backend && PYTHONPATH=src:. .venv/bin/python ../scripts/bake_demos.py --only demo-warped-vein

Every demo is generated through the application's own HTTP routes
(``minegen.demos.bake``) from its preset + seed recipe, with the DEMO /
SYNTHETIC planning-economics assumptions, then ``index.json`` is written.
``GET /api/v1/demos`` lists the result; the scenario store serves a demo in
place, read-only. ``data/`` is git-ignored: baking is a deployment step.
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
from minegen.services.demo_service import read_demo_index  # noqa: E402


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
    args = parser.parse_args(argv)
    recipes = [r for r in DEMO_RECIPES if not args.only or r.id in args.only]
    unknown = set(args.only) - {r.id for r in DEMO_RECIPES}
    if unknown:
        parser.error(f"unknown recipe id(s): {sorted(unknown)}")
    out: Path = args.out
    baker = DemoBaker(out)
    try:
        # keep the entries of recipes not re-baked this run
        existing = read_demo_index(out)
        kept = {e.id: e for e in (existing.demos if existing else [])}
        for recipe in recipes:
            t0 = time.monotonic()
            entry = baker.bake(recipe, log=lambda m: print(f"  {m}", flush=True))
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
