"""Phase 03 design services: cost evaluator construction, access-target
generation and persistence (``derived/targets.json``).

Evaluators are cached per scenario and dropped whenever the world is
invalidated (the world service owns that lifecycle)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from minegen.core.enums import OrebodyType
from minegen.core.models import Scenario
from minegen.design.constraints import DesignContext
from minegen.design.cost_field import DesignCostEvaluator
from minegen.design.mine_designer import ChainedDeclineGenerator
from minegen.design.progress import (
    ProgressCallback,
    ProgressEvent,
    ProgressStage,
    no_progress,
)
from minegen.design.smoothing import DeclineSmoother
from minegen.design.targets import AccessTargetSet, generate_access_targets, resolve_portal
from minegen.design.tunnel_mesh import TunnelMeshBuilder
from minegen.levels.builder import LevelDevelopmentBuilder
from minegen.levels.models import LevelsPayload
from minegen.mining.methods.base import strategy_for, unsupported_method_payload
from minegen.mining.models import StopesPayload
from minegen.network.builder import MineNetworkBuilder
from minegen.network.models import NetworkPayload
from minegen.scheduling.builder import MineTimelineBuilder
from minegen.scheduling.models import TimelinePayload
from minegen.services.scenario_service import ScenarioStore
from minegen.services.world_service import WorldService
from minegen.world.synthetic_world import SyntheticWorld


class UnsupportedOrebodyError(RuntimeError):
    """Phase 17 gate: the legacy Phase 03+ layout supports TABULAR only.
    Non-tabular scenarios are valid for world generation/visualization;
    generalized layout is deferred to Phase 18 (rule 123)."""


class TargetsNotGeneratedError(LookupError):
    pass


class TimelineNotGeneratedError(LookupError):
    """timeline.json does not exist for the scenario."""


class StopesNotGeneratedError(LookupError):
    """stopes.json does not exist for the scenario."""


class LevelsNotGeneratedError(LookupError):
    """levels.json does not exist for the scenario."""


class NetworkNotFoundError(LookupError):
    """network.json does not exist for the scenario."""


class TunnelNotGeneratedError(LookupError):
    """tunnel_mesh.json does not exist for the scenario."""

    def __init__(self, scenario_id: str) -> None:
        super().__init__(f"tunnel mesh not generated for scenario {scenario_id}")
        self.scenario_id = scenario_id


class SmoothedNotGeneratedError(LookupError):
    """decline_smoothed.json does not exist for the scenario."""

    def __init__(self, scenario_id: str) -> None:
        super().__init__(f"smoothed decline not generated for scenario {scenario_id}")
        self.scenario_id = scenario_id


class DeclineNotGeneratedError(LookupError):
    pass


class StaleInputsError(RuntimeError):
    """The scenario/world/targets revision changed while a design job was
    running (rule 60). The stale result is discarded, never persisted."""

    code = "JOB_INPUTS_CHANGED"

    def __init__(self, scenario_id: str) -> None:
        super().__init__(
            f"inputs of scenario '{scenario_id}' changed while the job was running; "
            "the stale result was discarded (regenerate to get a current one)"
        )


@dataclass(frozen=True)
class InputFingerprint:
    """Revision fingerprint of a decline job's inputs: (exists, size, mtime_ns)
    of scenario.json, arrays.npz and targets.json. Every invalidating mutation
    (scenario PUT, world regeneration, target regeneration, deletion) rewrites
    or removes at least one of these files, so equality of fingerprints means
    the inputs are the same revision — even when regenerated content is
    byte-identical, the revision is considered new (rules 40/46)."""

    entries: tuple[tuple[str, bool, int, int], ...]

    @staticmethod
    def _stat(path: Path) -> tuple[str, bool, int, int]:
        try:
            st = path.stat()
        except FileNotFoundError:
            return (path.name, False, 0, 0)
        return (path.name, True, st.st_size, st.st_mtime_ns)

    @classmethod
    def capture(cls, paths: list[Path]) -> InputFingerprint:
        return cls(entries=tuple(cls._stat(p) for p in paths))


class DesignService:
    def __init__(self, store: ScenarioStore, worlds: WorldService) -> None:
        self.store = store
        self.worlds = worlds
        self._evaluators: dict[str, tuple[SyntheticWorld, DesignCostEvaluator]] = {}
        self._targets: dict[str, AccessTargetSet] = {}

    # -- evaluator --------------------------------------------------------- #

    def evaluator(self, scenario_id: str) -> tuple[Scenario, SyntheticWorld, DesignCostEvaluator]:
        scenario, world = self.worlds.load(scenario_id)
        cached = self._evaluators.get(scenario_id)
        if cached is not None and cached[0] is world:
            return scenario, world, cached[1]
        ev = DesignCostEvaluator(world, scenario.design)
        self._evaluators[scenario_id] = (world, ev)
        return scenario, world, ev

    def evaluate(self, scenario_id: str, points: list[list[float]]) -> dict[str, Any]:
        _, _, ev = self.evaluator(scenario_id)
        res = ev.evaluate_points(np.asarray(points, dtype=np.float64))
        return {"count": len(res), "results": res.to_payload()}

    # -- targets ----------------------------------------------------------- #

    def targets_path(self, scenario_id: str) -> Any:
        return self.store.derived_dir(scenario_id) / "targets.json"

    def generate_targets(self, scenario_id: str) -> dict[str, Any]:
        scenario, world, ev = self.evaluator(scenario_id)
        if scenario.orebody.orebody_type is not OrebodyType.TABULAR:
            raise UnsupportedOrebodyError(scenario.orebody.orebody_type.value)
        portal, generated = resolve_portal(scenario, world)
        targets: AccessTargetSet = generate_access_targets(
            world,
            scenario.design,
            scenario.ramp,
            scenario.mining.sublevel_interval,
            ev,
            portal,
            generated,
        )
        payload = targets.to_dict()
        with self.store.lock(scenario_id):
            path = self.targets_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._targets[scenario_id] = targets
            decline = self.decline_path(scenario_id)
            if decline.exists():
                decline.unlink()  # rule 46: a decline built on old targets is stale
            smoothed = self.smoothed_path(scenario_id)
            if smoothed.exists():
                smoothed.unlink()  # rule 64: derived from the deleted decline
            self._delete_tunnel_artifacts(scenario_id)  # rule 67 chain
            self._delete_levels_artifact(scenario_id)  # rule 74 chain
            self._delete_stopes_artifact(scenario_id)  # rule 79 chain
            self._delete_timeline_artifact(scenario_id)  # rule 86 chain
            self._delete_communication_artifact(scenario_id)  # rule 92 chain
            self._delete_sensors_artifact(scenario_id)  # rule 98
            self._delete_network_artifact(scenario_id)  # rule 68 chain
        return payload

    # -- decline (Phase 04) ------------------------------------------------ #

    def decline_path(self, scenario_id: str) -> Any:
        return self.store.derived_dir(scenario_id) / "decline.json"

    def _targets_object(self, scenario_id: str) -> AccessTargetSet:
        cached = self._targets.get(scenario_id)
        if cached is not None and self.targets_path(scenario_id).is_file():
            return cached
        if not self.targets_path(scenario_id).is_file():
            raise TargetsNotGeneratedError(scenario_id)
        # targets.json exists from an earlier process: rebuild deterministically
        scenario, world, ev = self.evaluator(scenario_id)
        portal, generated = resolve_portal(scenario, world)
        targets = generate_access_targets(
            world,
            scenario.design,
            scenario.ramp,
            scenario.mining.sublevel_interval,
            ev,
            portal,
            generated,
        )
        self._targets[scenario_id] = targets
        return targets

    def _input_paths(self, scenario_id: str) -> list[Path]:
        return [
            self.store.scenario_path(scenario_id),
            self.store.arrays_path(scenario_id),
            Path(self.targets_path(scenario_id)),
        ]

    def input_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return InputFingerprint.capture(self._input_paths(scenario_id))

    def generate_decline(
        self,
        scenario_id: str,
        max_levels: int | None = None,
        on_progress: ProgressCallback = no_progress,
    ) -> dict[str, Any]:
        # Capture the input revision BEFORE loading anything: a mutation that
        # lands between capture and load makes the check fail (fail-safe),
        # never the other way around.
        fingerprint = self.input_fingerprint(scenario_id)
        scenario, _, ev = self.evaluator(scenario_id)
        targets = self._targets_object(scenario_id)
        gen = ChainedDeclineGenerator(
            ev, scenario.ramp, scenario.design.search, scenario.tunnel_profile
        )
        result = gen.generate(targets, max_levels=max_levels, on_progress=on_progress)
        payload = result.to_dict()
        # Persist atomically w.r.t. invalidation: the same lock guards
        # WorldService.invalidate's deletions, so a stale job can never write
        # after a mutation cleared derived/ (rules 40/46/60).
        with self.store.lock(scenario_id):
            if self.input_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.decline_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
            smoothed = self.smoothed_path(scenario_id)
            if smoothed.exists():
                smoothed.unlink()  # rule 64: the old smoothed artifact is stale
            self._delete_tunnel_artifacts(scenario_id)  # rule 67 chain
            self._delete_levels_artifact(scenario_id)  # rule 74 chain
            self._delete_stopes_artifact(scenario_id)  # rule 79 chain
            self._delete_timeline_artifact(scenario_id)  # rule 86 chain
            self._delete_communication_artifact(scenario_id)  # rule 92 chain
            self._delete_sensors_artifact(scenario_id)  # rule 98
            self._delete_network_artifact(scenario_id)  # rule 68 chain
        return payload

    # -- smoothing (Phase 05, rules 61–64) ---------------------------------- #

    def smoothed_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / "decline_smoothed.json"

    def _smoothing_input_paths(self, scenario_id: str) -> list[Path]:
        return [*self._input_paths(scenario_id), Path(self.decline_path(scenario_id))]

    def smoothing_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return InputFingerprint.capture(self._smoothing_input_paths(scenario_id))

    def generate_smoothed(
        self, scenario_id: str, on_progress: ProgressCallback = no_progress
    ) -> dict[str, Any]:
        """Phase 05: smooth + fully revalidate the persisted decline. The
        fingerprint additionally covers decline.json; persistence follows the
        same locked stale-input protocol as generate_decline (rule 60)."""
        fingerprint = self.smoothing_fingerprint(scenario_id)
        decline_payload = self.decline(scenario_id)  # 409 if not generated
        scenario, _, ev = self.evaluator(scenario_id)
        smoother = DeclineSmoother(ev, scenario.ramp, scenario.design.smoothing)

        def progress(i: int, n: int, level_id: str, stage: str) -> None:
            on_progress(
                ProgressEvent(
                    stage=ProgressStage(stage),
                    phase="DECLINE_SMOOTHING",
                    level=min(i + 1, n),
                    total_levels=n,
                    candidate=0,
                    total_candidates=0,
                    progress=min(i, n) / n if n else 1.0,
                    expanded_states=0,
                    level_id=level_id,
                )
            )

        result = smoother.smooth(decline_payload, on_progress=progress)
        payload = result.to_dict()
        n_seg = len(result.segments)
        on_progress(
            ProgressEvent(
                stage=ProgressStage.SMOOTHING_COMPLETED,
                phase="DECLINE_SMOOTHING",
                level=n_seg,
                total_levels=n_seg,
                candidate=0,
                total_candidates=0,
                progress=1.0,
                expanded_states=0,
                message=result.status,
            )
        )
        with self.store.lock(scenario_id):
            if self.smoothing_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.smoothed_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
            self._delete_tunnel_artifacts(scenario_id)  # rule 67: mesh is stale
            self._delete_levels_artifact(scenario_id)  # rule 74: levels are stale
            self._delete_stopes_artifact(scenario_id)  # rule 79: stopes are stale
            self._delete_timeline_artifact(scenario_id)  # rule 86: timeline is stale
            self._delete_communication_artifact(scenario_id)  # rule 92: stale
            self._delete_sensors_artifact(scenario_id)  # rule 98
            self._delete_network_artifact(scenario_id)  # rule 68: network is stale
        return payload

    def smoothed(self, scenario_id: str) -> dict[str, Any]:
        self.store.get(scenario_id)
        if not self.worlds.is_generated(scenario_id):
            from minegen.services.world_service import WorldNotGeneratedError

            raise WorldNotGeneratedError(scenario_id)
        path = self.smoothed_path(scenario_id)
        if not path.is_file():
            raise SmoothedNotGeneratedError(scenario_id)
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    # -- level developments (Phase 08, rules 71–74) -------------------------- #

    def levels_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / "levels.json"

    def _delete_levels_artifact(self, scenario_id: str) -> None:
        path = self.levels_path(scenario_id)
        if path.exists():
            path.unlink()

    def _levels_input_paths(self, scenario_id: str) -> list[Path]:
        # cross-section + mining lattice config from scenario.json, orebody
        # geometry via arrays.npz, entries from the smoothed artifact
        return [
            Path(self.store.scenario_path(scenario_id)),
            Path(self.store.arrays_path(scenario_id)),
            Path(self.smoothed_path(scenario_id)),
        ]

    def levels_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return InputFingerprint.capture(self._levels_input_paths(scenario_id))

    def generate_levels(self, scenario_id: str) -> LevelsPayload:
        """Synchronous deterministic analytic geometry (rule 71; rule 60
        reserves async jobs for long-running operations). Regenerating levels
        invalidates the MineNetwork but never the tunnel mesh (rule 74)."""
        fingerprint = self.levels_fingerprint(scenario_id)
        smoothed_payload = self.smoothed(scenario_id)  # 409 if not generated
        scenario, world, drift_ev = self.evaluator(scenario_id)
        crosscut_ev = DesignCostEvaluator(
            world, scenario.design, DesignContext.crosscut(scenario.design)
        )
        source_revision = hashlib.sha256(
            json.dumps(fingerprint.entries, sort_keys=True).encode()
        ).hexdigest()[:16]
        builder = LevelDevelopmentBuilder(scenario, world.orebody, drift_ev, crosscut_ev)
        payload = builder.build(smoothed_payload, source_revision)
        serialized = json.dumps(payload.model_dump(mode="json", by_alias=True))
        with self.store.lock(scenario_id):
            if self.levels_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.levels_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized, encoding="utf-8")
            self._delete_network_artifact(scenario_id)  # rule 74: rebuild, never patch
            self._delete_stopes_artifact(scenario_id)  # rule 79 chain
            self._delete_timeline_artifact(scenario_id)  # rule 86 chain
            self._delete_communication_artifact(scenario_id)  # rule 92 chain
            self._delete_sensors_artifact(scenario_id)  # rule 98
        return payload

    def levels(self, scenario_id: str) -> LevelsPayload:
        self.store.get(scenario_id)
        path = self.levels_path(scenario_id)
        if not path.is_file():
            raise LevelsNotGeneratedError(scenario_id)
        return LevelsPayload.model_validate(json.loads(path.read_text(encoding="utf-8")))

    # -- stopes (Phase 09, rules 75–80) --------------------------------------- #

    def stopes_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / "stopes.json"

    def _delete_stopes_artifact(self, scenario_id: str) -> None:
        path = self.stopes_path(scenario_id)
        if path.exists():
            path.unlink()

    def _stopes_input_paths(self, scenario_id: str) -> list[Path]:
        return [
            Path(self.store.scenario_path(scenario_id)),
            Path(self.store.arrays_path(scenario_id)),
            Path(self.levels_path(scenario_id)),
        ]

    def stopes_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return InputFingerprint.capture(self._stopes_input_paths(scenario_id))

    def generate_stopes(self, scenario_id: str) -> StopesPayload:
        """Synchronous Phase 09 stope generation (rules 75–80): consumes the
        validated levels artifact only, resolves the scenario mining method
        through the explicit strategy factory (rule 78 — unsupported methods
        fail, never silently substitute), and leaves tunnel/network untouched
        (rule 79)."""
        fingerprint = self.stopes_fingerprint(scenario_id)
        levels_payload = self.levels(scenario_id)  # 409 if not generated
        scenario, world, _ = self.evaluator(scenario_id)
        hard_ev = DesignCostEvaluator(
            world, scenario.design, DesignContext.crosscut(scenario.design)
        )
        source_revision = hashlib.sha256(
            json.dumps(fingerprint.entries, sort_keys=True).encode()
        ).hexdigest()[:16]
        strategy = strategy_for(scenario.mining.method)
        if strategy is None:
            payload = unsupported_method_payload(scenario.mining.method, source_revision)
        else:
            payload = strategy.generate(
                scenario,
                world,
                levels_payload.model_dump(mode="json", by_alias=True),
                hard_ev,
                source_revision,
            )
        serialized = json.dumps(payload.model_dump(mode="json", by_alias=True))
        with self.store.lock(scenario_id):
            if self.stopes_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.stopes_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized, encoding="utf-8")
            self._delete_timeline_artifact(scenario_id)  # rule 86: rebuild, never patch
        return payload

    def stopes(self, scenario_id: str) -> StopesPayload:
        self.store.get(scenario_id)
        path = self.stopes_path(scenario_id)
        if not path.is_file():
            raise StopesNotGeneratedError(scenario_id)
        return StopesPayload.model_validate(json.loads(path.read_text(encoding="utf-8")))

    # -- timeline (Phase 10, rules 81–86) ------------------------------------- #

    def timeline_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / "timeline.json"

    def _delete_timeline_artifact(self, scenario_id: str) -> None:
        path = self.timeline_path(scenario_id)
        if path.exists():
            path.unlink()

    def _delete_sensors_artifact(self, scenario_id: str) -> None:
        # rule 98: sensors.json shares communication's dependency shape;
        # the path contract is shared with InfrastructureService
        path = self.store.derived_dir(scenario_id) / "sensors.json"
        if path.exists():
            path.unlink()

    def _delete_communication_artifact(self, scenario_id: str) -> None:
        # rule 92: communication.json lives beside the other derived artifacts;
        # the path contract is shared with InfrastructureService
        path = self.store.derived_dir(scenario_id) / "communication.json"
        if path.exists():
            path.unlink()

    def _timeline_input_paths(self, scenario_id: str) -> list[Path]:
        # rule 86: network + stopes + the owning centerline artifacts
        return [
            Path(self.store.scenario_path(scenario_id)),
            Path(self.network_path(scenario_id)),
            Path(self.stopes_path(scenario_id)),
            Path(self.smoothed_path(scenario_id)),
            Path(self.levels_path(scenario_id)),
        ]

    def timeline_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return InputFingerprint.capture(self._timeline_input_paths(scenario_id))

    def generate_timeline(self, scenario_id: str) -> TimelinePayload:
        """Synchronous deterministic precedence-only baseline (rules 81–86):
        the task graph is small, so no async job (rule 60). Regenerating the
        timeline touches NOTHING upstream."""
        fingerprint = self.timeline_fingerprint(scenario_id)
        network_payload = self.network(scenario_id)  # NetworkNotFoundError if absent
        stopes_payload = self.stopes(scenario_id)  # 409 if absent
        smoothed_payload = self.smoothed(scenario_id)
        levels_payload = self.levels(scenario_id)
        scenario = self.store.get(scenario_id)
        source_revision = hashlib.sha256(
            json.dumps(fingerprint.entries, sort_keys=True).encode()
        ).hexdigest()[:16]
        builder = MineTimelineBuilder(scenario)
        payload = builder.build(
            network_payload.model_dump(mode="json", by_alias=True),
            stopes_payload.model_dump(mode="json", by_alias=True),
            smoothed_payload,
            levels_payload.model_dump(mode="json", by_alias=True),
            source_revision,
        )
        serialized = json.dumps(payload.model_dump(mode="json", by_alias=True))
        with self.store.lock(scenario_id):
            if self.timeline_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.timeline_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized, encoding="utf-8")
        return payload

    def timeline(self, scenario_id: str) -> TimelinePayload:
        self.store.get(scenario_id)
        path = self.timeline_path(scenario_id)
        if not path.is_file():
            raise TimelineNotGeneratedError(scenario_id)
        return TimelinePayload.model_validate(json.loads(path.read_text(encoding="utf-8")))

    # -- mine network (Phase 07, rules 13, 68–70) ---------------------------- #

    def network_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / "network.json"

    def _delete_network_artifact(self, scenario_id: str) -> None:
        path = self.network_path(scenario_id)
        if path.exists():
            path.unlink()

    def _network_input_paths(self, scenario_id: str) -> list[Path]:
        # the network consumes cross-section config from scenario.json, the
        # RAMP centerlines from the smoothed artifact (rule 68) and the level
        # developments from levels.json (rule 74)
        return [
            Path(self.store.scenario_path(scenario_id)),
            Path(self.smoothed_path(scenario_id)),
            Path(self.levels_path(scenario_id)),
        ]

    def network_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return InputFingerprint.capture(self._network_input_paths(scenario_id))

    def generate_network(self, scenario_id: str) -> NetworkPayload:
        """Synchronous full rebuild from smoothed + levels (rule 74: never
        patched from a stale artifact; rule 60 reserves async jobs for
        long-running operations). Sibling branch of the tunnel mesh: neither
        invalidates the other (rule 68)."""
        fingerprint = self.network_fingerprint(scenario_id)
        smoothed_payload = self.smoothed(scenario_id)  # 409 if not generated
        levels_payload = self.levels(scenario_id)  # 409 if not generated (rule 74)
        scenario = self.store.get(scenario_id)
        source_revision = hashlib.sha256(
            json.dumps(fingerprint.entries, sort_keys=True).encode()
        ).hexdigest()[:16]
        builder = MineNetworkBuilder(scenario)
        result = builder.build(
            smoothed_payload,
            source_revision,
            levels_payload=levels_payload.model_dump(mode="json", by_alias=True),
        )
        # deterministic serialization of the TYPED contract (rule 69): field
        # order is the model definition order, values are JSON-mode primitives
        serialized = json.dumps(result.payload.model_dump(mode="json", by_alias=True))
        with self.store.lock(scenario_id):
            if self.network_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.network_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized, encoding="utf-8")
            self._delete_timeline_artifact(scenario_id)  # rule 86: rebuild, never patch
            self._delete_communication_artifact(scenario_id)  # rule 92
            self._delete_sensors_artifact(scenario_id)  # rule 98
        return result.payload

    def network(self, scenario_id: str) -> NetworkPayload:
        self.store.get(scenario_id)  # 404 for unknown scenarios first
        path = self.network_path(scenario_id)
        if not path.is_file():
            raise NetworkNotFoundError(scenario_id)
        return NetworkPayload.model_validate(json.loads(path.read_text(encoding="utf-8")))

    # -- tunnel mesh (Phase 06, rules 65–67) -------------------------------- #

    def tunnel_report_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / "tunnel_mesh.json"

    def tunnel_glb_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / "tunnel_mesh.glb"

    def _delete_tunnel_artifacts(self, scenario_id: str) -> None:
        for path in (self.tunnel_report_path(scenario_id), self.tunnel_glb_path(scenario_id)):
            if path.exists():
                path.unlink()

    def _tunnel_input_paths(self, scenario_id: str) -> list[Path]:
        return [*self._smoothing_input_paths(scenario_id), Path(self.smoothed_path(scenario_id))]

    def tunnel_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return InputFingerprint.capture(self._tunnel_input_paths(scenario_id))

    def generate_tunnel(
        self, scenario_id: str, on_progress: ProgressCallback = no_progress
    ) -> dict[str, Any]:
        """Phase 06: gravity-aligned sweep of the Phase 05 effective
        centerline (rules 65–67). The fingerprint covers all five upstream
        inputs; persistence follows the locked stale-input protocol
        (rule 60). The GLB is written only on SUCCESS; the report is always
        persisted with an explicit status."""
        fingerprint = self.tunnel_fingerprint(scenario_id)
        smoothed_payload = self.smoothed(scenario_id)  # 409 if not generated
        scenario, _, ev = self.evaluator(scenario_id)
        builder = TunnelMeshBuilder(ev, scenario.ramp, scenario.tunnel_profile)

        def progress(i: int, n: int, label: str, stage: str) -> None:
            on_progress(
                ProgressEvent(
                    stage=ProgressStage(stage),
                    phase="TUNNEL_MESH",
                    level=min(i + 1, n) if n else 1,
                    total_levels=max(n, 1),
                    candidate=0,
                    total_candidates=0,
                    progress=min(i, n) / n if n else 1.0,
                    expanded_states=0,
                    level_id=label,
                )
            )

        result = builder.build(smoothed_payload, on_progress=progress)
        payload = dict(result.report)
        if result.glb is not None:
            revision = hashlib.sha256(result.glb).hexdigest()
            payload["artifactRevision"] = revision
            payload["meshUrl"] = (
                f"/api/v1/scenarios/{scenario_id}/design/tunnel/mesh.glb?v={revision[:16]}"
            )
        else:
            payload["artifactRevision"] = None
            payload["meshUrl"] = None
        with self.store.lock(scenario_id):
            if self.tunnel_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            report_path = self.tunnel_report_path(scenario_id)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(payload), encoding="utf-8")
            glb_path = self.tunnel_glb_path(scenario_id)
            if result.glb is not None:
                glb_path.write_bytes(result.glb)
            elif glb_path.exists():
                glb_path.unlink()  # never leave a stale GLB beside a FAILED report
        return payload

    def tunnel(self, scenario_id: str) -> dict[str, Any]:
        self.store.get(scenario_id)
        if not self.worlds.is_generated(scenario_id):
            from minegen.services.world_service import WorldNotGeneratedError

            raise WorldNotGeneratedError(scenario_id)
        path = self.tunnel_report_path(scenario_id)
        if not path.is_file():
            raise TunnelNotGeneratedError(scenario_id)
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def tunnel_glb(self, scenario_id: str) -> bytes:
        report = self.tunnel(scenario_id)
        glb_path = self.tunnel_glb_path(scenario_id)
        if report.get("status") != "SUCCESS" or not glb_path.is_file():
            raise TunnelNotGeneratedError(scenario_id)
        return glb_path.read_bytes()

    def decline(self, scenario_id: str) -> dict[str, Any]:
        self.store.get(scenario_id)
        if not self.worlds.is_generated(scenario_id):
            from minegen.services.world_service import WorldNotGeneratedError

            raise WorldNotGeneratedError(scenario_id)
        path = self.decline_path(scenario_id)
        if not path.is_file():
            raise DeclineNotGeneratedError(scenario_id)
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def targets(self, scenario_id: str) -> dict[str, Any]:
        self.store.get(scenario_id)  # raises ScenarioNotFoundError
        if not self.worlds.is_generated(scenario_id):
            from minegen.services.world_service import WorldNotGeneratedError

            raise WorldNotGeneratedError(scenario_id)
        path = self.targets_path(scenario_id)
        if not path.is_file():
            raise TargetsNotGeneratedError(scenario_id)
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def targets_if_present(self, scenario_id: str) -> dict[str, Any] | None:
        path = self.targets_path(scenario_id)
        if not path.is_file():
            return None
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
