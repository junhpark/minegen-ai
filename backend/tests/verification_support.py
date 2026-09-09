"""VA-01 verification-fixture support (test-side, never production code).

Content-based fingerprints for cached verification fixtures (rule: a cached
fixture is development acceleration, never release authority). The
fingerprint hashes the UPSTREAM CONTRACT the fixture represents — selected
candidate id, ramp centerline coordinates, level-entry coordinates and anchor
chainages — so FULL can detect a stale fixture by regenerating the same
artifacts cleanly and comparing, independent of git SHAs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "verification"
FIXTURE_SCHEMA_VERSION = 1


def _round(obj: Any, nd: int = 6) -> Any:
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, list):
        return [_round(v, nd) for v in obj]
    if isinstance(obj, dict):
        return {k: _round(v, nd) for k, v in obj.items()}
    return obj


def digest(payload: Any) -> str:
    canon = json.dumps(_round(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def selection_fingerprint(ramp_payload: dict[str, Any], accesses_payload: dict[str, Any]) -> str:
    """Upstream contract of a materialized layout selection: candidate id,
    every ramp segment centerline, every access terminal + anchor chainage."""
    core = {
        "candidateId": accesses_payload.get("candidateId"),
        "sourceKind": ramp_payload.get("sourceKind"),
        "segments": [
            {
                "levelId": s.get("levelId"),
                "points": (s.get("effectiveCenterline") or {}).get("points"),
            }
            for s in ramp_payload.get("segments", [])
        ],
        "accesses": [
            {
                "levelId": a.get("levelId"),
                "status": a.get("status"),
                "terminal": ((a.get("centerline") or {}).get("points") or [])[-3:],
                "traceChainage": (a.get("anchor") or {}).get("traceChainage"),
                "standoff": (a.get("anchor") or {}).get("standoff"),
            }
            for a in accesses_payload.get("accesses", [])
        ],
    }
    return digest(core)


def load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / f"{name}.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    meta = data["metadata"]
    if meta.get("schemaVersion") != FIXTURE_SCHEMA_VERSION:
        raise AssertionError(
            f"verification fixture {name}: schemaVersion {meta.get('schemaVersion')} != "
            f"{FIXTURE_SCHEMA_VERSION} — regenerate with scripts/generate_verification_fixtures.py"
        )
    for key in ("fixtureVersion", "sourceStage", "generatedFromGitSha", "upstreamFingerprint"):
        if key not in meta:
            raise AssertionError(f"verification fixture {name}: metadata lacks {key!r}")
    return data


def stale_message(name: str, expected: str, actual: str) -> str:
    return (
        f"STALE VERIFICATION FIXTURE {name}: upstream fingerprint {expected[:12]}… (fixture) "
        f"!= {actual[:12]}… (clean regeneration) — regeneration required: "
        "python scripts/generate_verification_fixtures.py. The clean E2E result stands; "
        "this is a verification-infrastructure failure, not a production result."
    )
