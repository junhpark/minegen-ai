from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from minegen.api.deps import (
    get_design_service,
    get_exchange_service,
    get_infrastructure_service,
    get_job_service,
    get_scenario_store,
    get_world_service,
)
from minegen.core.enums import ScenarioPreset
from minegen.core.models import (
    FaultConfig,
    FieldSamplingConfig,
    GeologyConfig,
    OrebodyConfig,
    Point3D,
    Scenario,
    ScenarioCreate,
    TerrainConfig,
    WorldConfig,
)
from minegen.layout.search import LayoutSearchResult, LayoutV2Search
from minegen.main import create_app
from minegen.services.design_service import DesignService
from minegen.services.exchange_service import ExchangeService
from minegen.services.infrastructure_service import InfrastructureService
from minegen.services.job_service import JobService
from minegen.services.scenario_realizer import realize_scenario
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from minegen.world.synthetic_world import SyntheticWorld, generate_world

# --------------------------------------------------------------------------- #
# VA-01 verification tiers — central marker assignment (runtime + role).
#
# Unmarked tests are the FAST inner loop. Every marked test is still collected
# by FULL; scripts/verify.py proves collected(FULL) == collected(unfiltered)
# and excludedFromFast ⊆ FULL mechanically, and tests/test_verification_tiers.py
# pins the same invariants. Assignment lives HERE (not scattered decorators)
# so the tiering is one auditable table; --strict-markers rejects typos.
# --------------------------------------------------------------------------- #

#: module → markers (every test in the module)
MODULE_MARKERS: dict[str, tuple[str, ...]] = {
    "test_layout_v2_golden_smoke": ("golden",),
    # Phase 20B.x: the GEOMETRY-STRESS feasibility oracle (one full layout-v2 search)
    "test_geometry_stress_oracle": ("slow",),
    "test_warped_vein_golden_smoke": ("golden",),
    "test_layout_v2_api": ("e2e",),
    # AC-01F commit 2: the read contract through the real API. Both stacks are
    # built end to end (LEGACY ≈ 9 s + LAYOUT_V2 ≈ 5 s) because ABSENT / STALE
    # / MALFORMED are states of a REAL derived set, not of a hand-written one
    # (the hand-written unit contract is tests/test_artifact_reader.py, FAST).
    "test_artifact_read_api": ("slow", "e2e"),
    # AC-01F commit 2: the scene snapshot boundary — concurrent writers against
    # a paused reader, plus a timed torn-read loop
    "test_scene_snapshot": ("slow", "e2e"),
    # AC-01F.2 D5.1: every one of the 22 write sites driven three times
    # through the REAL LEGACY and LAYOUT_V2 stacks with an injected
    # publication failure (two module-scoped builds ≈ 19 s + 66 driver runs)
    "test_publication_fault_injection": ("slow", "e2e"),
    # AC-01F.2 D5.4: the three paired publications, each on a stack built to
    # the point where the pair has never been written
    "test_publication_pair_order": ("slow", "e2e"),
    # AC-01F.2 D5.2: a subprocess reader against the real publish loop,
    # 10 s per artifact plus the stack build
    "test_publication_cross_process": ("slow", "e2e"),
    # AC-01F.2 correction B2: cross-PROCESS generation coherence (SW1–SW3,
    # MP1–MP5). Every case kills or stalls a REAL spawn child at an injected
    # publication point and reads the survivor state from a fresh process /
    # fresh services; ≈ 1–2 s of interpreter start-up per child, ~25 children
    # plus a committed world + targets per test.
    "test_world_publication_processes": ("slow", "e2e"),
    # AC-01G: the layout-v2 characterization freeze. TABULAR-REFERENCE is a
    # clean module-scoped search (≈ 18 s) and WARPED_VEIN-301 rides the shared
    # session search (≈ 55 s, already paid by the other slow consumers), so
    # the module is `slow` → FULL only, never FAST. NOT added to
    # CANARY_NODEID_SUFFIXES: a canary is a representative-scenario detector
    # the FEATURE tier runs clean, and the freeze is a refactor net whose
    # authority tier is FULL; adding it would put ≈ 75 s into every FEATURE
    # run. Marked at module level so the baseline-integrity tests travel with
    # the comparison tests.
    "test_layout_characterization": ("slow",),
}
#: test function name (any module) → markers
TEST_MARKERS: dict[str, tuple[str, ...]] = {
    # locked golden baselines (legacy Hybrid-A* smoke subset, rule 132)
    "test_baseline_report_is_committed_and_complete": ("golden", "legacy_regression"),
    "test_golden_smoke_contract_matches_baseline": ("golden", "legacy_regression"),
    # clean-pipeline E2E through services / API (8–226 s each)
    "test_downstream_reuses_the_selected_candidate_certification_across_restart": ("e2e", "slow"),
    # AC-01D: cold service chain / sync-API fail-closed proofs drive the services / API
    "test_restore_equals_stage4_policy_on_the_tabular_service_chain_cold": ("e2e",),
    "test_sync_tunnel_and_development_mesh_fail_closed_with_typed_409": ("e2e",),
    "test_selection_snapshot_is_read_under_the_store_lock": ("e2e",),
    "test_cache_never_serves_a_policy_under_a_foreign_selection_revision": ("e2e",),
    "test_clearance_failure_detail_names_the_candidate_basis": ("e2e", "slow"),
    "test_invalidation_chain_smoothed_decline_targets": ("e2e",),
    "test_stale_mesh_job_never_persists": ("e2e",),
    "test_tunnel_async_job_kind_mesh": ("e2e",),
    "test_tunnel_sync_lifecycle_scene_and_glb": ("e2e",),
    "test_tunnel_requires_smoothed": ("e2e",),
    "test_new_decline_invalidates_old_smoothed": ("e2e",),
    "test_world_regeneration_clears_smoothed": ("e2e",),
    "test_smooth_async_job_flow": ("e2e",),
    "test_smooth_sync_lifecycle_and_scene": ("e2e",),
    "test_targets_regeneration_invalidates_decline_and_smoothed": ("e2e",),
    "test_upstream_regeneration_invalidates_network": ("e2e",),
    "test_network_and_tunnel_are_siblings": ("e2e",),
    "test_network_lifecycle_and_payload_contract": ("e2e",),
    "test_network_requires_smoothed_and_levels": ("e2e",),
    "test_progress_events_are_ordered_and_results_unchanged": ("e2e",),
    "test_sync_decline_with_concurrent_invalidation_returns_409": ("e2e",),
    "test_decline_async_job_flow": ("e2e",),
    "test_stopes_api_lifecycle_and_invalidation": ("e2e",),
    "test_timeline_api_lifecycle_and_invalidation": ("e2e",),
    "test_sensor_api_lifecycle_and_sibling_invalidation": ("e2e",),
    "test_missing_owning_geometry_409s": ("e2e",),
    "test_communication_api_lifecycle_and_invalidation": ("e2e",),
    "test_decline_lifecycle": ("e2e",),
    # Phase 20D.3 design assessment over the REAL layout-v2 → capability chain
    "test_e2e_assessment_projects_the_real_layout_and_capability_artifacts": ("e2e",),
    # Phase 23A MineExchange over the REAL LAYOUT_V2 chain (module-scoped
    # stack: search + tunnel + levels + development mesh + network +
    # capability graph) and the REAL LEGACY chain (decline + smoothing)
    "test_e2e_full_bundle_is_deterministic_and_read_only": ("e2e",),
    "test_e2e_orebody_and_terrain_on_the_full_bundle": ("e2e",),
    "test_e1_e4_every_excavation_kind_is_an_individually_closed_solid": ("e2e",),
    "test_e5_export_solids_are_the_production_base_logical_sweep": ("e2e",),
    "test_e6_junction_connected_solids_stay_closed_and_overlap": ("e2e",),
    "test_e7_e8_multibody_is_a_concatenation_never_a_union": ("e2e",),
    "test_render_glbs_are_verbatim_source_bytes": ("e2e",),
    "test_l1_l4_centerlines_csv_matches_the_authoritative_polylines": ("e2e",),
    "test_l2_l3_centerlines_dxf_round_trips_with_stable_identity": ("e2e",),
    "test_n1_n5_network_projection": ("e2e",),
    "test_p1_p4_capability_projection": ("e2e",),
    "test_snapshot_change_during_export_is_refused": ("e2e",),
    "test_p5_p6_capability_absent_stale_and_malformed": ("e2e",),
    "test_legacy_ramp_export": ("e2e",),
    # Phase 20C.2B shaft + capability graph API lifecycle (legacy pipeline E2E)
    "test_shaft_and_capability_api_lifecycle": ("e2e",),
    # AC-01E artifact registry: every artifact built + regenerated through the
    # API under both ramp sources (minutes per source)
    "test_every_regeneration_deletes_exactly_the_registry_closure": ("e2e", "slow"),
    # high-cost algorithm tests (Hybrid-A* chains, exhaustive diagnostics, 307)
    "test_sealed_level_yields_structured_infeasible_and_skips_rest": ("slow",),
    "test_chain_backtracks_out_of_trapped_best_arrival": ("slow",),
    "test_all_levels_completed_and_targets_hit_exactly": ("slow",),
    "test_exhaustive_diagnostic_mode_validates_every_cheap_feasible_candidate": ("slow",),
    "test_group_weights_reorder_the_ranking_deterministically": ("slow",),
    "test_shortlist_reconstruction_holds_on_a_conservative_case_with_failed_detailed": ("slow",),
    "test_simplification_is_lossless": ("slow",),
    "test_cut_and_fill_generic_backbone_is_independent_of_longhole_parameters": ("slow",),
    "test_conservative_screen_is_a_heuristic_and_carries_no_subset_contract": ("slow",),
    # Phase 20B.x: the ramp-floor vertical profile on the WARPED-301 winner plan
    "test_v5_warped_plan_follows_the_ramp_floor": ("slow",),
    "test_candidate_policy_reconstruction_is_deterministic": ("slow",),
    "test_warped_vein_is_accepted_by_layout_v2_but_not_by_the_legacy_pipeline": ("slow",),
    # AC-01G: the stage-boundary proofs that pay for a clean WARPED-301 run.
    # The offset-trace build COUNT (risk R1) needs its own spied search, and
    # the sectionGeometry variant of the performance key order rides the
    # shared session search. The rest of test_layout_stages.py is static AST
    # + a small TABULAR search and stays in FAST.
    "test_offset_trace_build_count_matches_head": ("slow",),
    "test_performance_key_order_with_section_geometry": ("slow",),
    # Phase 20C.4 service reference on a fresh WARPED-307 world + search
    "test_reference_delta_is_positive_on_the_failing_307_spiral": ("slow",),
    "test_307_failing_candidates_now_hold_the_separation_at_every_rl_crossing": ("slow",),
}
#: fixtures whose mere request makes a test expensive (a clean WARPED-301
#: world + search ≈ 60 s): every consumer is `slow`, mechanically — so FAST
#: can never pay for the shared fixture through an unmarked consumer.
EXPENSIVE_FIXTURES: frozenset[str] = frozenset(
    {"warped_301", "warped_301_search", "warped", "warped_search", "warped_levels"}
)
#: representative-scenario regression detectors run CLEAN in FEATURE / FULL
CANARY_NODEID_SUFFIXES: tuple[str, ...] = (
    "test_layout_v2_golden_smoke.py::test_layout_v2_smoke_matches_baseline[TABULAR-REFERENCE]",
    "test_layout_v2_golden_smoke.py::test_layout_v2_smoke_matches_baseline[WARPED_VEIN-301]",
    "test_curved_levels.py::TestCurvedLevelDevelopment::test_warped_levels_succeed_on_the_curved_backbone",
    "test_layout_v2_api.py::test_warped_vein_development_mesh_sweeps_accesses_drifts_and_crosscuts",
    "test_layout_v2_api.py::test_parametric_ramp_drives_the_tabular_downstream_chain",
    "test_verification_fixtures_fresh.py::test_tabular_selection_fixture_matches_clean_regeneration",
    "test_verification_fixtures_fresh.py::test_warped_sections_fixture_matches_clean_regeneration",
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        module = item.module.__name__.rsplit(".", 1)[-1] if item.module else ""
        marks: set[str] = set(MODULE_MARKERS.get(module, ()))
        marks.update(
            TEST_MARKERS.get(item.originalname if hasattr(item, "originalname") else item.name, ())
        )
        fixturenames = set(getattr(item, "fixturenames", ()))
        if fixturenames & EXPENSIVE_FIXTURES:
            marks.add("slow")
        if any(item.nodeid.endswith(suffix) for suffix in CANARY_NODEID_SUFFIXES):
            marks.add("canary")
        for name in sorted(marks):
            item.add_marker(getattr(pytest.mark, name))


@pytest.fixture
def store(tmp_path: Path) -> ScenarioStore:
    return ScenarioStore(tmp_path / "scenarios")


@pytest.fixture
def world_service(store: ScenarioStore) -> WorldService:
    return WorldService(store)


@pytest.fixture
def design_service(store: ScenarioStore, world_service: WorldService) -> DesignService:
    return DesignService(store, world_service)


@pytest.fixture
def job_service() -> Iterator[JobService]:
    svc = JobService(max_workers=2)
    yield svc
    svc.shutdown()


@pytest.fixture
def client(
    store: ScenarioStore,
    world_service: WorldService,
    design_service: DesignService,
    job_service: JobService,
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_scenario_store] = lambda: store
    app.dependency_overrides[get_world_service] = lambda: world_service
    app.dependency_overrides[get_design_service] = lambda: design_service
    app.dependency_overrides[get_infrastructure_service] = lambda: InfrastructureService(
        store, design_service
    )
    app.dependency_overrides[get_job_service] = lambda: job_service
    app.dependency_overrides[get_exchange_service] = lambda: ExchangeService(store, world_service)
    # the WebSocket handler resolves the registry without DI; point it at the same instance
    import minegen.api.jobs as jobs_module

    jobs_module.get_job_service = lambda: job_service  # type: ignore[assignment]
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# VA-01 shared deterministic upstream fixtures (session scope).
#
# WARPED-301 (RANDOM_WARPED_VEIN seed 301, fault_count 1, DEFAULT config) is
# the most repeated clean upstream computation in the suite (VA0: 12 clean
# searches ≈ 745 s ≈ 43 % of test time). Consumers that need the DEFAULT
# configuration share ONE immutable world + search result per process;
# tests that change the configuration (buffer, access reach) or that prove
# cross-instance determinism keep their own clean runs. Isolation contract:
# the fixture objects are READ-ONLY — a content fingerprint taken at
# creation is re-checked at session teardown and any drift fails the run
# naming the leak (VA-01 §10–11).
# --------------------------------------------------------------------------- #


def _search_fingerprint(res: LayoutSearchResult) -> tuple[object, ...]:
    return (
        res.winner_id,
        tuple(res.shortlist),
        tuple(
            (c.candidate_id, c.status, c.stage_reached, tuple(c.failure_reasons))
            for c in res.candidates
        ),
        tuple(
            (c.candidate_id, None if c.scores is None else round(float(c.scores.total), 9))
            for c in res.candidates
        ),
    )


def _world_fingerprint(world: SyntheticWorld) -> tuple[object, ...]:
    import hashlib

    h = hashlib.sha256()
    h.update(np.ascontiguousarray(world.terrain.z).tobytes())
    h.update(np.ascontiguousarray(world.fields.rock_quality.values).tobytes())
    return (h.hexdigest(), len(world.faults), repr(world.orebody.bounding_box()))


@pytest.fixture(scope="session")
def warped_301() -> Iterator[tuple[Scenario, SyntheticWorld]]:
    sc = Scenario(
        **realize_scenario(ScenarioPreset.RANDOM_WARPED_VEIN, 301, fault_count=1).model_dump()
    )
    world = generate_world(sc)
    before = _world_fingerprint(world)
    yield sc, world
    assert _world_fingerprint(world) == before, (
        "shared warped_301 world was MUTATED by a test — shared fixtures are read-only"
    )


@pytest.fixture(scope="session")
def warped_301_search(
    warped_301: tuple[Scenario, SyntheticWorld],
) -> Iterator[tuple[LayoutV2Search, LayoutSearchResult]]:
    sc, world = warped_301
    search = LayoutV2Search(sc, world)
    res = search.run()
    before = _search_fingerprint(res)
    yield search, res
    assert _search_fingerprint(res) == before, (
        "shared warped_301_search result was MUTATED by a test — shared fixtures are read-only"
    )


def small_scenario(seed: int = 42, with_fault: bool = True) -> Scenario:
    """Fast world (≈ 40×40×30 field cells) for algorithm tests."""
    faults = (
        [
            FaultConfig(
                origin=Point3D(x=-60.0, y=-80.0, z=0.0),
                strike_deg=120.0,
                dip_deg=65.0,
                core_half_width=2.5,
                influence_half_width=20.0,
            )
        ]
        if with_fault
        else []
    )
    return Scenario(
        **ScenarioCreate(
            name="small",
            seed=seed,
            world=WorldConfig(size_x=400, size_y=400, depth=250),
            terrain=TerrainConfig(grid_spacing=10, base_elevation=100, relief=40, octaves=3),
            orebody=OrebodyConfig(
                center=Point3D(x=40.0, y=20.0, z=-50.0),
                strike_deg=35.0,
                dip_deg=70.0,
                length=200.0,
                height=120.0,
                thickness=12.0,
                mean_grade=4.2,
                grade_variability=0.3,
            ),
            geology=GeologyConfig(faults=faults),
            field_sampling=FieldSamplingConfig(spacing_x=10, spacing_y=10, spacing_z=10),
        ).model_dump()
    )
