"""AC-01F.2 D5.2 — a CROSS-PROCESS reader never sees a torn artifact.

A subprocess loops ``json.loads(path.read_bytes())`` over
``derived/stopes.json`` (and ``np.load`` over ``arrays.npz``) while this
process loops the REAL publish of that artifact
(``DesignService.generate_stopes`` / ``WorldService._save``). Nothing is
monkeypatched and no primitive is substituted: these are the production
writers. The store lock does not participate — it is per process and the
reader is not in it — so this measures publication, and nothing else.

PRE-CHANGE LITERALS, measured at 450f9df (the base of this branch) with the
SAME script (``scratchpad/ac01f2/xproc_race.py``, 12 s per artifact, one
reader process):

    derived/stopes.json   7,673 bytes   1,843 publishes
                          164,384 reads, 7,679 json.JSONDecodeError
                          = 4.671 % torn reads
                          ("Expecting value: line 1 column 1 (char 0)")

    arrays.npz          497,730 bytes     487 publishes
                          357,563 reads, 357,563 zipfile.BadZipFile
                          = 100.0 % torn reads, 0 successful reads
                          ("File is not a zip file" — numpy's ``_savez``
                          opens the DESTINATION zip in mode "w", so the
                          file is invalid for the whole write)

Stage A measured the in-process equivalents at 12d7725 (§7.2,
``p4_f06b_e2e_race``): 0.68 % of ``DesignService.stopes`` calls and 0.95 %
of ``WorldService.scene`` calls raised ``json.JSONDecodeError``. All of
these RATES are artifacts of an artificial write rate on one filesystem and
are not production probabilities; what they establish is the window and the
symptom. This test asserts the window is CLOSED: 0 decode errors, with the
publish and read counts asserted too so it cannot pass vacuously.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from minegen.core.revision import file_revision
from tests.test_artifact_read_api import API, Stack, _make_stack

#: this module is marked ``slow`` + ``e2e`` CENTRALLY (rule 181,
#: ``tests/conftest.py::MODULE_MARKERS``), so the tiering stays one
#: auditable table and no decorator here can drift from it.

#: seconds of concurrent publishing per artifact (D5.2 asks for >= 10 s)
RACE_SECONDS = 10.0

READER = textwrap.dedent(
    """
    import json, sys, time
    kind, path, deadline = sys.argv[1], sys.argv[2], float(sys.argv[3])
    counts = {"reads": 0, "ok": 0, "decode_errors": 0, "os_errors": 0, "samples": []}
    if kind == "npz":
        import numpy as np
    while time.time() < deadline:
        counts["reads"] += 1
        try:
            if kind == "json":
                with open(path, "rb") as fh:
                    json.loads(fh.read())
            else:
                with np.load(path) as loaded:
                    for key in loaded.files:
                        loaded[key]
            counts["ok"] += 1
        except OSError as exc:
            counts["os_errors"] += 1
            if len(counts["samples"]) < 6:
                counts["samples"].append(f"OSError {type(exc).__name__}: {str(exc)[:120]}")
        except Exception as exc:
            counts["decode_errors"] += 1
            if len(counts["samples"]) < 6:
                counts["samples"].append(f"{type(exc).__name__}: {str(exc)[:120]}")
    print(json.dumps(counts))
    """
)


@pytest.fixture(scope="module")
def raced(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    """The smallest LEGACY stack that owns a ``stopes.json`` and a world."""
    stack, context = _make_stack(tmp_path_factory.mktemp("xproc"))

    def step(route: str, **kwargs: object) -> None:
        response = stack.client.post(f"{API}/{stack.sid}{route}", **kwargs)  # type: ignore[arg-type]
        assert response.status_code == 200, (route, response.status_code, response.text[:300])

    step("/world/generate")
    step("/design/targets")
    step("/design/decline", params={"maxLevels": 2, "sync": "true"})
    step("/design/decline/smooth", params={"sync": "true"})
    step("/design/levels")
    step("/design/stopes")
    yield stack
    context.__exit__(None, None, None)
    stack.jobs.shutdown()


def _race(kind: str, path: Path, publish: Callable[[], object]) -> dict[str, object]:
    deadline = time.time() + RACE_SECONDS
    child = subprocess.Popen(
        [sys.executable, "-c", READER, kind, str(path), str(deadline)],
        stdout=subprocess.PIPE,
        text=True,
    )
    writes = 0
    try:
        while time.time() < deadline:
            publish()
            writes += 1
    finally:
        stdout, _ = child.communicate(timeout=180)
    counts = json.loads(stdout.strip().splitlines()[-1])
    counts["writes"] = writes
    counts["bytes"] = path.stat().st_size
    return dict(counts)


def test_a_cross_process_reader_never_sees_a_torn_stopes_json(raced: Stack) -> None:
    path = raced.design.stopes_path(raced.sid)
    counts = _race("json", path, lambda: raced.design.generate_stopes(raced.sid))
    assert counts["decode_errors"] == 0, counts
    assert counts["os_errors"] == 0, counts
    # not vacuous: real concurrency really happened (pre-change: 1,843
    # publishes and 164,384 reads in 12 s on this fixture)
    assert counts["writes"] >= 50, counts
    assert counts["reads"] >= 1000, counts
    assert counts["ok"] == counts["reads"], counts
    assert [p.name for p in path.parent.rglob("*") if ".tmp" in p.name] == []


def test_a_cross_process_reader_never_sees_a_torn_arrays_npz(raced: Stack) -> None:
    """``WorldService._save`` is the production publisher of ``arrays.npz``;
    ``generate`` is not used because it would first run the rule-46
    invalidation and delete the derived set this module shares."""
    scenario, world = raced.worlds.load(raced.sid)
    stats = world.stats(scenario)
    path = raced.store.arrays_path(raced.sid)
    revision = file_revision(raced.store.scenario_path(raced.sid))
    assert revision is not None
    counts = _race("npz", path, lambda: raced.worlds._save(scenario, world, stats, revision))
    assert counts["decode_errors"] == 0, counts
    assert counts["os_errors"] == 0, counts
    # pre-change this artifact was UNREADABLE for the whole run (487
    # publishes, 357,563 reads, 0 of them successful)
    assert counts["writes"] >= 20, counts
    assert counts["reads"] >= 100, counts
    assert counts["ok"] == counts["reads"], counts
    root = raced.store.scenario_dir(raced.sid)
    assert [p.name for p in root.rglob("*") if ".tmp" in p.name] == []
