"""Phase 11 infrastructure service (rules 87–92).

Handles persistence, fingerprinting, prerequisite loading, locking and
invalidation integration for ``derived/communication.json``. Algorithms
stay in ``minegen/infrastructure``; the API stays thin.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from minegen.infrastructure.builder import CommunicationBuilder
from minegen.infrastructure.models import CommunicationPayload
from minegen.services.design_service import (
    DesignService,
    InputFingerprint,
    StaleInputsError,
)
from minegen.services.scenario_service import ScenarioStore


class CommunicationNotGeneratedError(LookupError):
    """communication.json does not exist for the scenario."""


class InfrastructureService:
    def __init__(self, store: ScenarioStore, design: DesignService) -> None:
        self.store = store
        self.design = design

    def communication_path(self, scenario_id: str) -> Path:
        return self.store.derived_dir(scenario_id) / "communication.json"

    def _communication_input_paths(self, scenario_id: str) -> list[Path]:
        # rule 92 direct inputs: scenario + network + owning centerlines.
        # stopes/timeline/tunnel are deliberately NOT inputs (§6).
        return [
            Path(self.store.scenario_path(scenario_id)),
            Path(self.design.network_path(scenario_id)),
            Path(self.design.smoothed_path(scenario_id)),
            Path(self.design.levels_path(scenario_id)),
        ]

    def communication_fingerprint(self, scenario_id: str) -> InputFingerprint:
        return InputFingerprint.capture(self._communication_input_paths(scenario_id))

    def generate_communication(self, scenario_id: str) -> CommunicationPayload:
        """Synchronous deterministic communication baseline. Regenerating
        communication touches NOTHING upstream (rule 92)."""
        fingerprint = self.communication_fingerprint(scenario_id)
        network_payload = self.design.network(scenario_id)  # NetworkNotFoundError -> 409
        smoothed_payload = self.design.smoothed(scenario_id)  # SmoothedNotGeneratedError
        levels_payload = self.design.levels(scenario_id)  # LevelsNotGeneratedError
        scenario = self.store.get(scenario_id)
        source_revision = hashlib.sha256(
            json.dumps(fingerprint.entries, sort_keys=True).encode()
        ).hexdigest()[:16]
        builder = CommunicationBuilder(scenario)
        payload = builder.build(
            network_payload.model_dump(mode="json", by_alias=True),
            smoothed_payload,
            levels_payload.model_dump(mode="json", by_alias=True),
            source_revision,
        )
        serialized = json.dumps(payload.model_dump(mode="json", by_alias=True))
        with self.store.lock(scenario_id):
            if self.communication_fingerprint(scenario_id) != fingerprint:
                raise StaleInputsError(scenario_id)
            path = self.communication_path(scenario_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized, encoding="utf-8")
        return payload

    def communication(self, scenario_id: str) -> CommunicationPayload:
        self.store.get(scenario_id)
        path = self.communication_path(scenario_id)
        if not path.is_file():
            raise CommunicationNotGeneratedError(scenario_id)
        return CommunicationPayload.model_validate(json.loads(path.read_text(encoding="utf-8")))
