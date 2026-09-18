"""AC-01G characterization-freeze support (test-side, never production code).

The layout-v2 search behaviour at the freeze SHA is recorded as a committed
baseline (``tests/fixtures/characterization/<case>.json``) so a later refactor
cannot change it silently. This module owns the four mechanisms the baseline
depends on, and NOTHING else:

1. the wall-clock mask — the SAME rule ``tests/test_layout_policy_restore.py``
   already established (drop ``sourceRevision`` and every key ending in
   ``Seconds``); ``test_layout_characterization.py`` asserts the two rules
   are still literally identical, so the mask cannot widen by drift;
2. the observation projections C1–C6 over ``LayoutSearchResult.to_dict()``,
   shared by the generator and the test so the baseline and the comparison
   can never be computed by two different definitions;
3. the enumerated platform-sensitivity registry — the ONE leaf whose last
   bit was MEASURED to move between this container's numpy/LAPACK build and
   the GitHub runner's, canonicalized by name at a declared precision. Not a
   blanket float rounding and not a tolerance: see
   ``PLATFORM_SENSITIVE_LEAVES``;
4. the self-fingerprint: a baseline records the git SHA it was generated at
   and a content fingerprint over its own body. The fingerprint detects a
   hand-edited body; the SHA is pinned as a CONSTANT in the test module, so
   regenerating at another HEAD requires an explicit, reviewable source edit
   (rule 181's "never auto-rewritten", applied to a characterization
   baseline).

Authority: a characterization baseline records what the code DID at the
freeze SHA. It is not an engineering specification and proves no constraint
correct; a difference is a signal to explain, never on its own a defect.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "characterization"
CHARACTERIZATION_SCHEMA_VERSION = 1

#: the git SHA the committed baselines were generated at (AC-01G freeze)
BASELINE_GIT_SHA = "3951d98d91235facb6b95e9d646f0dc62b7c9835"

#: the two frozen cases (minegen.regression.layout_v2.FULL_SUITE keys)
CASE_KEYS: tuple[str, ...] = (
    "TABULAR-REFERENCE",
    "WARPED_VEIN-301",
    "ACCESS-INFEASIBLE",
    "GEOMETRY-STRESS",
)

#: wall-clock keys — identical to tests/test_layout_policy_restore.py
WALL_CLOCK_KEYS = {"sourceRevision"}


def strip_wall_clock(obj: Any) -> Any:
    """Drop wall-clock keys (``sourceRevision``, ``*Seconds``) recursively.

    Deliberately NOT a general normalisation: everything else is compared as
    it is emitted. If two clean runs differ in some other key, that is a
    finding about the code, not something to mask away.
    """
    if isinstance(obj, dict):
        return {
            k: strip_wall_clock(v)
            for k, v in obj.items()
            if k not in WALL_CLOCK_KEYS and not str(k).endswith("Seconds")
        }
    if isinstance(obj, list):
        return [strip_wall_clock(v) for v in obj]
    return obj


#: leaf keys whose LAST BIT is platform-sensitive, mapped to the number of
#: decimal places the characterization compares. This is an ENUMERATED list of
#: MEASURED findings, never a convenience: every other float in the payload —
#: candidate ids, statuses, geometry coordinates, scores, ranking, winner,
#: clearance, access geometry — is compared bit-exactly, and
#: ``test_layout_characterization.py`` proves a single-ulp change to any of
#: those still FAILS.
#:
#: ``localTangentVsGlobalPcaDeg`` (``layout/access.py`` — the only entry):
#:   ``math.degrees(math.acos(|pca_axis · tangent|))`` where ``pca_axis`` comes
#:   from ``numpy.linalg.eigh`` on a 2x2 covariance, whose last bit depends on
#:   the LAPACK build. MEASURED on WARPED_VEIN-301's fourth level access:
#:   ``cos = 0.9996624881871111``, so ``d(deg)/d(cos) = 2205.5`` and ONE ulp of
#:   the dot product (1.110e-16) becomes 2.449e-13 deg. The difference between
#:   this container (numpy 2.5.2 / CPython 3.12.3) and the GitHub runner
#:   (numpy 2.5.3 / CPython 3.12.14) is 2.447e-13 deg — ratio 1.00 — and it
#:   REPRODUCES at the freeze source with zero ``backend/src`` changes
#:   (probe branch ``ac-01g-probe-base-platform``, run 35303979826), so it is
#:   platform drift and not a refactor moving a bit. The measured eigh-vs-svd
#:   eigenvector deviation on the same inputs (1.166e-15) bounds the angle move
#:   at 2.572e-12 deg; 9 decimals (1e-9 deg) leaves ~390x headroom over that
#:   bound while staying far below the only engineering use of the number
#:   (``tests/test_footwall_trace.py``'s ``> 25.0`` threshold).
#:
#:   It is safe to canonicalize because it is TERMINAL: ``_principal_axis`` has
#:   exactly one production call site and its result reaches exactly this one
#:   diagnostic string — no geometry, score, clearance, ranking or decision can
#:   inherit its last bit (``test_layout_characterization.py::
#:   test_the_canonicalized_leaf_is_a_terminal_diagnostic`` is the source-level
#:   guard for exactly that).
PLATFORM_SENSITIVE_LEAVES: dict[str, int] = {
    "localTangentVsGlobalPcaDeg": 9,
}


def canonicalize_platform_sensitive(obj: Any) -> Any:
    """Round ONLY the leaves enumerated in ``PLATFORM_SENSITIVE_LEAVES``.

    Deliberately NOT a blanket float rounding and NOT a tolerance: a key is
    canonicalized only by NAME, only when it actually holds a float, and only
    at the declared number of places. Applied once at the top of
    ``observations`` so the generator and the comparison use one definition and
    the C6 payload sha stays computable over the same bytes.
    """
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            places = PLATFORM_SENSITIVE_LEAVES.get(str(k))
            if places is not None and isinstance(v, float):
                out[k] = round(v, places)
            else:
                out[k] = canonicalize_platform_sensitive(v)
        return out
    if isinstance(obj, list):
        return [canonicalize_platform_sensitive(v) for v in obj]
    return obj


def key_paths(obj: Any, prefix: str = "") -> list[str]:
    """Ordered key paths of a payload.

    Descends into every dict (recording each key in emission order) and into
    list elements that are themselves containers. A list of scalars is a
    LEAF path: ``candidates[3].centerline.points`` is one entry, not 40 000.
    Computed on the UNMASKED payload, so a masked key still shows up as a
    path — a key added, removed or reordered fails even though its value
    was masked.
    """
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.append(p)
            out.extend(key_paths(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, dict | list):
                out.extend(key_paths(v, f"{prefix}[{i}]"))
    return out


def payload_sha(payload: dict[str, Any]) -> str:
    """C6: sha256 of the wall-clock-stripped payload in EMISSION key order."""
    text = json.dumps(strip_wall_clock(payload), sort_keys=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# C1 – C6 projections (one definition, shared by the generator and the test)
# --------------------------------------------------------------------------- #

#: per-candidate keys frozen after the cheap stage. For a SHORTLISTED
#: candidate ``status`` / ``stageReached`` are its POST-DETAILED values: the
#: search publishes ONE result object and exposes no mid-run snapshot, and
#: reaching into the stage methods would freeze private internals instead of
#: behaviour. Recorded as-is and stated, never silently implied.
_C2_KEYS = (
    "status",
    "stageReached",
    "failureReasons",
    "cheapProxy",
    "screenedLevels",
    "requiredLevels",
    "accessibleLevels",
    "rampLevelReferences",
    "accessScreen",
)

#: per-candidate keys frozen after the detailed stage
_C4_KEYS = (
    "status",
    "stageReached",
    "failureReasons",
    "failureDetail",
    "clearance",
    "validation",
    "scores",
    "exposure",
    "diagnostics",
    "derived",
    "access",
)

#: bulk geometry dropped from the READABLE C4 projection — it stays covered
#: exactly by the C6 payload sha, which hashes the whole payload
_ACCESS_BULK = ("centerline", "pieces")


def c1_enumeration(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "candidateId": c["candidateId"],
            "family": c["family"],
            "parameters": c["parameters"],
        }
        for c in payload["candidates"]
    ]


def c2_post_cheap(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"candidateId": c["candidateId"], **{k: c[k] for k in _C2_KEYS}}
        for c in payload["candidates"]
    ]


def c3_shortlist(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "shortlist": list(payload["shortlist"]),
        "shortlisted": [[c["candidateId"], c["shortlisted"]] for c in payload["candidates"]],
    }


def c4_detailed(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in payload["candidates"]:
        if not c["shortlisted"]:
            continue
        rec: dict[str, Any] = {"candidateId": c["candidateId"], **{k: c[k] for k in _C4_KEYS}}
        accesses = c.get("levelAccesses")
        rec["levelAccesses"] = (
            None
            if accesses is None
            else [{k: v for k, v in a.items() if k not in _ACCESS_BULK} for a in accesses]
        )
        out.append(rec)
    return out


def c5_ranking(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ranking": list(payload["ranking"]),
        "ranks": [[c["candidateId"], c["rank"]] for c in payload["candidates"]],
        "winnerId": payload["winnerId"],
    }


#: list indices collapsed so the 92 sibling candidate rows contribute ONE
#: shape entry instead of 92 identical ones.
_INDEX = re.compile(r"\[\d+\]")


def key_path_shape(paths: list[str]) -> list[str]:
    """The order-preserving DISTINCT key paths with list indices collapsed.

    ``candidates[0].scores.total`` and ``candidates[91].scores.total`` are one
    shape entry ``candidates[].scores.total``. A key ADDED to a single row
    still creates a new shape entry, so the schema net is unchanged while the
    committed baseline drops from 39 577 strings to 483 (TABULAR, measured).
    Multiplicity and per-row order are not lost: ``keyPathCount`` pins the
    total and ``keyPathsSha256`` pins the full ORDERED list.
    """
    out: list[str] = []
    seen: set[str] = set()
    for p in paths:
        shape = _INDEX.sub("[]", p)
        if shape not in seen:
            seen.add(shape)
            out.append(shape)
    return out


def c6_payload(payload: dict[str, Any]) -> dict[str, Any]:
    paths = key_paths(payload)
    joined = "\n".join(paths)
    return {
        "sha256": payload_sha(payload),
        "keyPathCount": len(paths),
        "keyPathsSha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "keyPathShape": key_path_shape(paths),
    }


def observations(payload: dict[str, Any]) -> dict[str, Any]:
    """The whole C1–C6 observation set of one search result.

    The enumerated platform-sensitive leaves are canonicalized FIRST, so every
    projection below — including the C6 payload sha — is computed over the same
    canonical bytes on every platform.
    """
    payload = canonicalize_platform_sensitive(payload)
    return {
        "header": {
            "status": payload["status"],
            "layoutVersion": payload["layoutVersion"],
            "clearanceBasis": payload["clearanceBasis"],
            "candidateCount": payload["candidateCount"],
            "feasibleCount": payload["feasibleCount"],
            "serviceableLevelCount": payload["serviceableLevelCount"],
            "requiredLevels": payload["requiredLevels"],
            "portal": payload["portal"],
            "portalGenerated": payload["portalGenerated"],
            "clearanceErrorBound": payload["clearanceErrorBound"],
            "requiredClearance": payload["requiredClearance"],
            "accessReach": payload["accessReach"],
            "footwallStandoff": payload["footwallStandoff"],
            "searchConfig": payload["searchConfig"],
            "performance": strip_wall_clock(payload["performance"]),
        },
        "c1Enumeration": c1_enumeration(payload),
        "c2PostCheap": c2_post_cheap(payload),
        "c3Shortlist": c3_shortlist(payload),
        "c4Detailed": c4_detailed(payload),
        "c5Ranking": c5_ranking(payload),
        "c6Payload": c6_payload(payload),
    }


#: the observation sections a baseline carries, in COMPARISON order: C1 … C6
#: first, so a failure is reported against the stage it belongs to, and the
#: result header (portal, level set, config, masked performance) last.
SECTIONS: tuple[str, ...] = (
    "c1Enumeration",
    "c2PostCheap",
    "c3Shortlist",
    "c4Detailed",
    "c5Ranking",
    "c6Payload",
    "header",
)


# --------------------------------------------------------------------------- #
# self-fingerprint (rule 181 applied to a characterization baseline)
# --------------------------------------------------------------------------- #


def content_fingerprint(git_sha: str, body: dict[str, Any]) -> str:
    """sha256 over the generating git SHA and the baseline BODY.

    The body is hashed exactly as written (no rounding): a characterization
    freeze compares bits, not tolerances.
    """
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{git_sha}\n{canon}".encode()).hexdigest()


def baseline_path(case_key: str) -> Path:
    return FIXTURE_DIR / f"{case_key.replace('-', '_').lower()}.json"


def load_baseline(case_key: str) -> dict[str, Any]:
    """Load a committed baseline and VERIFY its self-fingerprint.

    Loud, explicit failure on a hand-edited or partially-regenerated file;
    never repaired, never rewritten.
    """
    path = baseline_path(case_key)
    if not path.exists():
        raise AssertionError(
            f"MISSING CHARACTERIZATION BASELINE for {case_key}: {path} does not exist. "
            "The AC-01G freeze baseline is generated ONCE, at the freeze SHA "
            f"{BASELINE_GIT_SHA}, by scripts/generate_characterization_baseline.py. "
            "Do not regenerate it to make this test pass."
        )
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("metadata")
    if not isinstance(meta, dict):
        raise AssertionError(f"CORRUPT CHARACTERIZATION BASELINE {path}: no metadata object")
    if meta.get("schemaVersion") != CHARACTERIZATION_SCHEMA_VERSION:
        raise AssertionError(
            f"CHARACTERIZATION BASELINE {case_key}: schemaVersion "
            f"{meta.get('schemaVersion')!r} != {CHARACTERIZATION_SCHEMA_VERSION}"
        )
    if meta.get("caseKey") != case_key:
        raise AssertionError(
            f"CHARACTERIZATION BASELINE {path}: caseKey {meta.get('caseKey')!r} != {case_key!r}"
        )
    body = {k: v for k, v in data.items() if k != "metadata"}
    recorded = meta.get("contentFingerprint")
    actual = content_fingerprint(str(meta.get("generatedFromGitSha")), body)
    if recorded != actual:
        raise AssertionError(
            f"TAMPERED CHARACTERIZATION BASELINE {path}: recorded contentFingerprint "
            f"{str(recorded)[:12]}… does not match its own content ({actual[:12]}…) under the "
            f"recorded git SHA {meta.get('generatedFromGitSha')!r}. The baseline body or the "
            "recorded SHA was edited by hand, or the file was written by something other than "
            "scripts/generate_characterization_baseline.py. It is NEVER auto-rewritten: restore "
            "the committed file, or regenerate deliberately and update BASELINE_GIT_SHA in "
            "tests/characterization_support.py in the same reviewed change."
        )
    return data
