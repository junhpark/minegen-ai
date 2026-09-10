# Verification (VA-01 — Verification Acceleration)

`FAST LOOP, FULL CONFIDENCE.` Verification is tiered so that the developer
inner loop and the Claude-visible output shrink while the authoritative
release evidence keeps its full scope. VA-01 changed **verification
infrastructure only**: no production geometry, ranking, threshold, golden
expectation or hard gate moved (`git diff main -- backend/src` is empty).

## Baseline profile (VA0, main 96bc576, 558 tests)

Measured with `pytest --durations=50 --junitxml` plus a counting plugin that
attributed every `realize_scenario` / `generate_world` / `LayoutV2Search.run`
call to the test that triggered it (raw data: `.verification/baseline-*`,
`upstream-counts.json`; not committed).

| quantity | value |
|---|---|
| backend full pytest wall | 1 779 s (29.7 min); sum of test times 1 749.7 s |
| frontend full gate wall | 55 s |
| top 20 slowest tests | 1 205 s = **68.9 %** |
| tests ≥ 8 s | 50 tests = 1 582 s = 90.4 %; the other 508 tests = 167.6 s |
| layout searches | 42 calls = 955 s = **54.6 %** (34 tests) |
| WARPED-301 clean search | **12 runs = 745 s = 42.6 %** across 10 tests in 5 modules |
| small-TABULAR search / TABULAR-REFERENCE / WARPED-307 | 24 runs 104 s / 4 runs 59 s / 2 runs 48 s |
| `generate_world` calls | 206 (small TABULAR 112, "Untitled" TABULAR 57, WARPED-301 11) |

Category share: golden smoke 22.0 %, API E2E 31.0 %, layout-search
units/integration 35.3 %, everything else 11.8 %.

**Bottleneck type: A+B.** A (a few heavy tests) dominates; B (the same
WARPED-301 default-configuration search repeated) is material. Of the 12
WARPED-301 searches, 7 used the identical default configuration; the rest
differ in configuration (IRREGULAR access reach, clearance-consistency buffer
12 m ×3) or intentionally re-run to prove cross-instance determinism.

## Measured tier runtimes (same machine, uncontended, at VA-01 delivery)

| tier | wall | tests |
|---|---|---|
| FAST | 190 s | 491 passed (7 Claude-visible lines on success) |
| FEATURE | 424 s | 496 passed — three clean WARPED-301 canaries (~212 s) dominate; above the 5-min advisory, kept for coverage |
| old FULL (baseline) | 1 779 s pytest + 55 s frontend | 558 passed |
| new FULL | see the VA-01 delivery report (same-HEAD old/new equivalence run) | unfiltered |

## Tiers

| tier | command | what runs | authority |
|---|---|---|---|
| FAST | `python scripts/verify.py fast` | ruff check, ruff format --check, mypy, `pytest -m "not slow and not golden and not survey and not e2e and not legacy_regression and not benchmark"` (491 / 564 tests) incl. the cached canaries | development acceleration |
| FEATURE | `python scripts/verify.py feature` | FAST ∪ `canary` (clean TABULAR-REFERENCE / WARPED-301 pipelines, cached-fixture freshness) | milestone / atomic-commit gate |
| FULL | `python scripts/verify.py full [--backend-only] [--closeout] [--legacy]` | every gate of the old CI: ruff, format, mypy, **pytest UNFILTERED**, frontend typecheck / lint / prettier / vitest / build, plus the mechanical coverage proof; `--closeout` adds the layout-v2 golden regeneration + compare, the 32-seed survey and the screen audit as compact summaries (`golden-summary.json`); `--legacy` the 22-case legacy suite | merge evidence for its exact HEAD |
| BENCHMARK | `python scripts/verify.py benchmark` | `scripts/benchmark_reference_cases.py` stage split for TABULAR-REFERENCE and WARPED-301 → `runtime-summary.json` | observation only — never a correctness gate |

`python scripts/verify.py collect-full` prints and stores the coverage
invariants (`collection-coverage.json`, `collect-all.txt`,
`collect-fast.txt`, `collect-excluded.txt`).

## Markers

Registered in `backend/pyproject.toml` under `--strict-markers` (an unknown
marker is a collection error). Assignment is central, in
`backend/tests/conftest.py::pytest_collection_modifyitems`, from three explicit
tables so the tiering is one auditable place:

* `MODULE_MARKERS` — whole modules (`test_layout_v2_golden_smoke`,
  `test_warped_vein_golden_smoke` → `golden`; `test_layout_v2_api` → `e2e`).
* `TEST_MARKERS` — individual tests by function name (legacy golden smoke →
  `golden` + `legacy_regression`; API lifecycle / invalidation chains and the
  restart E2E → `e2e`; Hybrid-A* chains, exhaustive diagnostics, WARPED-307
  and cross-instance determinism → `slow`).
* `EXPENSIVE_FIXTURES` — any test whose fixture closure requests the shared
  WARPED-301 fixtures is `slow` mechanically, so FAST can never pay for the
  60 s fixture through an unmarked consumer.
* `CANARY_NODEID_SUFFIXES` — the clean representative detectors (`canary`,
  additive).

Marker semantics: `slow` high cost / low inner-loop value; `golden` locked
contract or metric comparison; `survey` multi-seed deterministic survey;
`e2e` clean pipeline integration; `legacy_regression` locked historical
Hybrid-A* suite; `benchmark` runtime observation; `canary` representative
scenario regression detector. Every marked test is in FULL.

## Shared deterministic fixtures (session scope)

`warped_301` / `warped_301_search` in `tests/conftest.py` build the DEFAULT
WARPED-301 world and search once per process and are consumed by
`test_layout_v2`, `test_curved_levels` and `test_level_access` (12 → 10 clean
WARPED-301 searches in FULL). They are READ-ONLY: a content fingerprint
(terrain, rock-quality field, orebody bounds; winner, shortlist, candidate
statuses and scores) is taken at creation and re-asserted at session
teardown — a leaking test fails the run by name. Tests that change the
configuration keep their own clean runs; the cross-instance determinism test
keeps its intentional second search. Small-TABULAR module fixtures were left
alone (sharing gains < 10 s).

## Cached verification fixtures

`backend/tests/fixtures/verification/*.json`, written only by
`scripts/generate_verification_fixtures.py`, never edited by hand. Metadata:
`fixtureVersion`, `schemaVersion`, `scenarioPreset`, `seed`, `faultCount`,
`sourceStage`, `generatedFromGitSha`, `upstreamFingerprint` (content hash of
the upstream contract — candidate id, ramp centerlines, access terminals,
anchor chainages — so a new commit does not invalidate a fixture whose
upstream did not change).

* `tabular_small_selected` — the small TABULAR selected layout (Effective
  Ramp + level accesses). FAST canary: cached selection → level development
  (rule 43) → MineNetwork. For an analytic body the candidate policy IS the
  exact world policy, so the cached chain runs under the service's own
  certification.
* `warped_301_sections` — WARPED-301 section(z) geometry + footwall / offset
  traces under the world policy (no search). FAST canary pins the summary.

Freshness (`tests/test_verification_fixtures_fresh.py`, `canary` — and,
being cheap, also collected by FAST): the same artifacts are regenerated
CLEANLY and the fingerprint compared; a mismatch fails with `STALE VERIFICATION FIXTURE … regeneration
required` — the clean result stands, the fixture is never rewritten
automatically. A curved-level FAST canary with the candidate-specific refined
policy is NOT cached: rule 172 reconstructs that policy from the search
context, so it stays a clean FEATURE canary.

## Output policy

Success prints only `PASS name (elapsed)`, counts and the summary line;
failure prints the failed step, the failed test ids, the first actionable
traceback and the log path. Everything else lives in `backend/.verification/`
(git-ignored): `<mode>-<step>.log`, `<mode>-pytest.xml`,
`verification-summary.json` (`mode`, `gitHead`, `gitDirty`, `elapsedSeconds`,
`fullAuthority`, `authority`, `sourceIdentity`, `ci`, backend / frontend gate
statuses and counts, steps, failed tests), `golden-summary.json`,
`survey-detail.json`, `runtime-summary.json`.

## Release authority (AC-01A)

`fullAuthority` is a JUDGEMENT over the whole run, not "the mode was full and
nothing failed". `evaluate_authority()` grants it only when ALL of these hold,
and returns a typed reason for each one that does not (`authority.reasons` is
empty if and only if authority is granted):

| condition | withheld with |
|---|---|
| the FULL tier ran | `MODE_NOT_FULL:<mode>` |
| no step recorded a failure | `GATE_FAILURE_RECORDED`, `GATE_FAILED:<gate>` |
| every required gate executed — `ruff-check`, `ruff-format`, `mypy`, `pytest-full`, `fe-typecheck`, `fe-lint`, `fe-prettier`, `fe-vitest`, `fe-build` | `GATE_NOT_RUN:<gate>` |
| the pytest step that ACTUALLY ran carried no `-m` selection | `PYTEST_FULL_FILTERED` |
| the collection-coverage proof (rule 181) was produced and satisfied | `COVERAGE_PROOF_MISSING`, `COVERAGE_PROOF_FAILED` |
| the unfiltered run EXECUTED everything it collected (`executedFull` from the junit report == `collectedFull`) | `EXECUTION_COVERAGE_MISMATCH:<executed>!=<collected>` |
| the working tree was clean at the FIRST gate and at the LAST | `WORKTREE_DIRTY_AT_START`, `WORKTREE_DIRTY_AT_END` |
| the source did not change during the run (`sourceIdentity.digest` over HEAD + porcelain status) | `SOURCE_CHANGED_DURING_RUN` |

A partial run reports what it actually covered:
`authority.components.backendFullSuite` / `frontendFullSuite`. CI's
`verify.py full --backend-only` job is therefore a COMPONENT — true backend
component authority, `release` false with the five frontend gates named.
`python scripts/verify.py authority A.json B.json` combines component
summaries of ONE revision into a single verdict (`gateSource` names which
component proved each gate) and exits non-zero when authority is withheld.
It re-derives every component from the evidence recorded in its own summary
(steps, tier, source identity, coverage) rather than from that summary's
`authority` block, and refuses a component that cannot name its revision
(`COMPONENT_REVISION_UNKNOWN`) or carries no evidence
(`COMPONENT_EVIDENCE_MISSING`).

`certifiedSha` / `certifiedShaKind` say WHICH commit a result certifies: on a
GitHub `pull_request` run the checkout is a synthetic merge commit that exists
in no branch, so the summary records it as `PULL_REQUEST_MERGE_SIMULATION`
alongside `ci.prHeadSha` — and `PULL_REQUEST_SHA_UNVERIFIED` when the event
payload could not be read, never the reassuring `PULL_REQUEST_HEAD`.
`collected(FULL) == collected(unfiltered)` is true by construction and proves
nothing on its own; the executed-vs-collected condition above is the part
that does. A FULL summary is release evidence only for its own
`certifiedSha`, and `fullAuthority` values recorded in phase documents before
AC-01A were produced under the weaker expression.

## CI

`verify-fast.yml` (pull requests) and `verify-full.yml` (push to main and pull
requests; backend `verify.py full --backend-only` + the unchanged frontend
job) run ALONGSIDE the original `ci.yml`. The original trigger set is reduced
only after old/new FULL equivalence on the same HEAD is proven (VA5) —
path-based filtering is out of VA-01 scope.
