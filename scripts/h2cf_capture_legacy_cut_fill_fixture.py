"""Capture the PR #53 (pre-H2-CF) Cut & Fill scenario directory as the
regression fixture of the PR #54 review B2 migration
(``tests/test_cut_fill_legacy_migration.py``). Run ONCE from a checkout's root
against a WORKTREE of the pinned PR-2 base — the LAST commit whose Cut & Fill
artifacts carry no ``cutFillModelVersion``:

    git worktree add --detach /tmp/pr53 1bd68c807730d12053d723d1189c4b901a18cf3e
    backend/.venv/bin/python scripts/h2cf_capture_legacy_cut_fill_fixture.py \\
        --source /tmp/pr53 --out backend/tests/fixtures/h2cf/legacy_pr53_cut_fill

The script imports ``minegen`` and ``tests.conftest`` from ``--source`` (never
from the checkout it lives in), builds the small CUT_AND_FILL scenario through
THAT code's own HTTP routes — world → layout-v2 → activate → levels → network →
production → timeline, exactly the PR #53 workflow — and copies the whole
scenario directory (``scenario.json``, ``arrays.npz``, ``derived/*``) into the
fixture together with ``stat.json`` (size + ``mtime_ns`` of every file: the
rule-60 world commit record and every layout revision bind by STAT identity,
which git does not preserve, so the test restores the timestamps) and
``meta.json`` (the source commit, the scenario id, the stages run).

Refuses any other source HEAD: the fixture is a historical record of the PR #53
shape and is never regenerated from newer code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

#: the PR #53 merge commit — the PR-2 base and the ONLY source this fixture
#: may be captured from (``tests/test_cut_fill_legacy_migration.py`` pins it)
PR53_HEAD = "1bd68c807730d12053d723d1189c4b901a18cf3e"

STAGES: tuple[tuple[str, str], ...] = (
    ("WORLD", "/world/generate"),
    ("LAYOUT", "/design/layout-v2?sync=true"),
    ("ACTIVATE", "/design/layout-v2/activate"),
    ("LEVELS", "/design/levels"),
    ("NETWORK", "/network/generate"),
    ("PRODUCTION", "/design/production"),
    ("SCHEDULE", "/design/timeline"),
)


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=root
    ).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(source: Path, out: Path) -> None:
    head = _git_head(source)
    if head != PR53_HEAD:
        raise SystemExit(
            f"refusing to capture the legacy Cut & Fill fixture from {head}: pinned to "
            f"{PR53_HEAD} (edit PR53_HEAD here AND in tests/test_cut_fill_legacy_migration.py "
            "only as an explicit, reviewed change)"
        )
    backend = source / "backend"
    # the SOURCE tree's code, ahead of the editable install of this checkout
    sys.path.insert(0, str(backend))
    sys.path.insert(0, str(backend / "src"))
    for name in [m for m in sys.modules if m == "minegen" or m.startswith("minegen.")]:
        del sys.modules[name]
    from fastapi.testclient import TestClient
    from tests.conftest import small_scenario
    from tests.phase21a_parity_support import with_method

    from minegen.api.deps import (
        get_design_service,
        get_infrastructure_service,
        get_job_service,
        get_scenario_store,
        get_world_service,
    )
    from minegen.core.enums import MiningMethodType
    from minegen.main import create_app
    from minegen.services.design_service import DesignService
    from minegen.services.infrastructure_service import InfrastructureService
    from minegen.services.job_service import JobService
    from minegen.services.scenario_service import ScenarioStore
    from minegen.services.world_service import WorldService

    assert Path(create_app.__code__.co_filename).resolve().is_relative_to(backend.resolve()), (
        "minegen was not imported from --source"
    )
    with tempfile.TemporaryDirectory(prefix="legacy-cut-fill-") as tmp:
        store = ScenarioStore(Path(tmp) / "scenarios")
        worlds = WorldService(store)
        design = DesignService(store, worlds)
        jobs = JobService(max_workers=1)
        app = create_app()
        app.dependency_overrides[get_scenario_store] = lambda: store
        app.dependency_overrides[get_world_service] = lambda: worlds
        app.dependency_overrides[get_design_service] = lambda: design
        app.dependency_overrides[get_infrastructure_service] = lambda: InfrastructureService(
            store, design
        )
        app.dependency_overrides[get_job_service] = lambda: jobs
        with TestClient(app) as client:
            sc = with_method(small_scenario(), MiningMethodType.CUT_AND_FILL)
            payload = sc.model_dump(by_alias=True, exclude={"id", "schema_version"})
            payload["name"] = "legacy-pr53-cut-fill"
            created = client.post("/api/v1/scenarios", json=payload)
            assert created.status_code == 201, created.text
            sid = str(created.json()["id"])
            base = f"/api/v1/scenarios/{sid}"
            done: list[str] = []
            winner: str | None = None
            for stage, route in STAGES:
                body: dict[str, Any] | None = None
                if stage == "ACTIVATE":
                    body = {"candidateId": winner}
                r = client.post(f"{base}{route}", json=body)
                assert r.status_code == 200, f"{stage}: {r.status_code} {r.text[:300]}"
                doc = r.json()
                status = doc.get("status")
                assert status in (None, "SUCCESS", "AVAILABLE"), f"{stage}: {doc}"
                if stage == "LAYOUT":
                    winner = doc["winnerId"]
                    assert winner
                done.append(stage)
                print(f"  {stage}: ok", flush=True)
        jobs.shutdown()
        src_dir = store.scenario_dir(sid)
        stopes = json.loads((src_dir / "derived" / "stopes.json").read_text())
        assert stopes["method"] == "CUT_AND_FILL" and "cutFillModelVersion" not in stopes
        if out.exists():
            shutil.rmtree(out)
        (out / "scenario").mkdir(parents=True)
        stat: dict[str, dict[str, Any]] = {}
        for path in sorted(p for p in src_dir.rglob("*") if p.is_file()):
            rel = path.relative_to(src_dir).as_posix()
            target = out / "scenario" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            st = path.stat()
            stat[rel] = {"size": st.st_size, "mtimeNs": st.st_mtime_ns, "sha256": _sha256(path)}
        (out / "stat.json").write_text(json.dumps(stat, indent=2, sort_keys=True) + "\n")
        (out / "meta.json").write_text(
            json.dumps(
                {
                    "generatedFromGitSha": head,
                    "scenarioId": sid,
                    "miningMethod": "CUT_AND_FILL",
                    "stages": done,
                    "cutFillModelVersion": None,
                    "note": (
                        "PR #53 Cut & Fill scenario directory captured through the PR #53 "
                        "routes; stat.json restores the size / mtime_ns identities the world "
                        "commit record and the layout revisions bind to"
                    ),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        total = sum(v["size"] for v in stat.values())
        print(f"wrote {out} ({len(stat)} files, {total / 1e6:.2f} MB, scenario {sid})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="worktree at PR53_HEAD")
    parser.add_argument("--out", type=Path, required=True, help="fixture directory to write")
    args = parser.parse_args(argv)
    capture(args.source.resolve(), args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
