#!/usr/bin/env python
"""Emit the LAYER B (float-bearing) characterization observations of the
``minegen`` package that THIS interpreter resolves, for the frozen cases.

One script, run twice from one interpreter on one machine — once with
``PYTHONPATH`` pointing at ``git archive <freeze-sha> backend/src``, once at
HEAD's ``backend/src`` — is how ``tests/test_layout_characterization.py``
proves "HEAD is the same function as the base ON THIS PLATFORM" without
asking every CPU / BLAS build to agree on a last bit (Park review of PR #35).

Which source it observed is never assumed: ``--expect-source-root`` makes the
caller state it and the script refuses to run if ``minegen.__file__`` is not
under it. Provenance (interpreter, NumPy version, CPU model, NumPy's enabled
SIMD dispatch features, the numeric-threading environment) is recorded with
the observations so a difference can be attributed.

    python scripts/characterization_observe.py \
        --expect-source-root /path/to/backend/src \
        --out observations.json [--case KEY ...] [--source-sha SHA]

Exit status 0 on success; 2 on a provenance refusal.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
# ``tests.characterization_support`` (stdlib-only) comes from THIS checkout;
# ``minegen`` comes from wherever the caller's PYTHONPATH says — deliberately
# NOT inserted here, so the archive can shadow the editable install.
sys.path.insert(0, str(BACKEND))

from tests.characterization_support import CASE_KEYS, observations  # noqa: E402

#: environment variables that change NumPy / BLAS numerics or threading
_NUMERIC_ENV = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NPY_DISABLE_CPU_FEATURES",
    "NPY_ENABLE_CPU_FEATURES",
)


def _cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _numpy_dispatch() -> dict[str, Any]:
    """NumPy's compiled baseline and the dispatch features ENABLED on this
    CPU — the mechanism by which one wheel produces different last bits on
    different runners."""
    import numpy as np

    info: dict[str, Any] = {"version": np.__version__}
    try:
        from numpy._core._multiarray_umath import (  # type: ignore[attr-defined]
            __cpu_baseline__,
            __cpu_dispatch__,
            __cpu_features__,
        )

        info["baseline"] = list(__cpu_baseline__)
        info["dispatchEnabled"] = [f for f in __cpu_dispatch__ if __cpu_features__.get(f)]
        info["dispatchDisabled"] = [f for f in __cpu_dispatch__ if not __cpu_features__.get(f)]
    except Exception as exc:  # pragma: no cover - older / other NumPy builds
        info["dispatchError"] = repr(exc)
    return info


def provenance(source_root: Path, source_sha: str | None) -> dict[str, Any]:
    import minegen

    return {
        "minegenFile": str(Path(minegen.__file__).resolve()),
        "sourceRoot": str(source_root),
        "sourceSha": source_sha,
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpuModel": _cpu_model(),
        "numpy": _numpy_dispatch(),
        "numericEnv": {k: os.environ.get(k) for k in _NUMERIC_ENV},
    }


def observe(case_key: str) -> dict[str, Any]:
    from minegen.layout.search import LayoutV2Search
    from minegen.regression.layout_v2 import case_by_key
    from minegen.world.synthetic_world import generate_world

    sc = case_by_key(case_key).realize()
    result = LayoutV2Search(sc, generate_world(sc)).run()
    return observations(result.to_dict())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--expect-source-root", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--case", action="append", choices=list(CASE_KEYS))
    ap.add_argument("--source-sha", default=None)
    args = ap.parse_args()

    import minegen

    expected = args.expect_source_root.resolve()
    actual = Path(minegen.__file__).resolve()
    if expected not in actual.parents:
        print(
            f"REFUSING: minegen resolved to {actual}, not under the expected source root "
            f"{expected}. Set PYTHONPATH so the intended source shadows the editable install.",
            file=sys.stderr,
        )
        return 2

    keys = tuple(args.case) if args.case else CASE_KEYS
    out = {
        "provenance": provenance(expected, args.source_sha),
        "cases": {k: observe(k) for k in keys},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, sort_keys=True, allow_nan=False), encoding="utf-8")
    print(
        f"observed {len(keys)} case(s) from {actual.parent} "
        f"(numpy {out['provenance']['numpy']['version']}, cpu {out['provenance']['cpuModel']}) "
        f"→ {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
