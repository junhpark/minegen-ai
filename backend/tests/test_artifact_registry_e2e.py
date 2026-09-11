"""AC-01E — black-box lifecycle proof through the real API.

For each ramp-source state, EVERY artifact is built through its real route,
then each one is regenerated through its real route and the set of files
that disappeared from ``derived/`` must equal the registry closure
``invalidated_by(written, source)`` — a cascade that deletes one file too
many or too few fails. The inline cascade blocks (which cannot be called in
isolation) are thereby held to the registry by the real code paths, not by
transcription. Cases the equivalence probe found unpinned are included:
the idempotent re-select / re-activate deletes NOTHING (tunnel, levels and
network survive), a same-source ``PUT …/ramp-source`` deletes nothing, and
a legacy regeneration under LAYOUT_V2 leaves the v2 chain alone.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from minegen.core.artifact_registry import derived_artifacts, invalidated_by
from minegen.core.artifacts import RampSource
from minegen.services.design_service import DesignService
from tests.test_artifact_registry import (
    CG,
    CM,
    DM,
    LA,
    LS,
    LV,
    RS,
    SH,
    SM,
    SN,
    SOURCES,
    ST,
    TL,
    TM,
    D,
    L,
    N,
    T,
)
from tests.test_shafts_api import _prepare_with_shaft

ALL_FILES: frozenset[str] = frozenset(f.name for a in derived_artifacts() for f in a.files)


def _files(derived: Path) -> frozenset[str]:
    return frozenset(p.name for p in derived.iterdir() if p.is_file())


class _Chain:
    """Builds every artifact that is missing, through the API, under ONE
    ramp source, and records the candidate it selected."""

    def __init__(
        self, client: TestClient, design: DesignService, sid: str, source: RampSource
    ) -> None:
        self.client = client
        self.design = design
        self.sid = sid
        self.source = source
        self.base = f"/api/v1/scenarios/{sid}"
        self.derived = design.store.derived_dir(sid)
        self.chosen: str | None = None
        self.other: str | None = None

    def _post(self, route: str, json: dict[str, str] | None = None, **params: str) -> dict:  # type: ignore[type-arg]
        r = self.client.post(f"{self.base}/{route}", params=params or None, json=json)
        assert r.status_code == 200, (route, r.text)
        body: dict = r.json()  # type: ignore[type-arg]
        return body

    def _missing(self, name: str) -> bool:
        return not (self.derived / name).is_file()

    def ensure_all(self) -> None:
        if self._missing(T):
            self._post("design/targets")
        if self._missing(D):
            self._post("design/decline", maxLevels="2", sync="true")
        if self._missing(SM):
            self._post("design/decline/smooth", sync="true")
        if self._missing(L):
            cat = self._post("design/layout-v2", sync="true")
            assert cat["status"] == "SUCCESS", cat
            feasible = [c for c in cat["ranking"] if c.startswith("SPIRAL")] or cat["ranking"]
            if self.chosen is None:
                self.chosen = str(feasible[0])
                feasible_ids = {
                    c["candidateId"] for c in cat["candidates"] if c["status"] == "FEASIBLE"
                }
                others = [c for c in cat["ranking"] if c != self.chosen and c in feasible_ids]
                assert others, "the small scenario must offer a second FEASIBLE candidate"
                self.other = str(others[0])
        assert self.chosen is not None
        if self._missing(LS) or self._missing(LA):
            self._post("design/layout-v2/select", {"candidateId": self.chosen})
        src = self.client.get(f"{self.base}/design/ramp-source").json()["activeSource"]
        if src != self.source:
            r = self.client.put(
                f"{self.base}/design/ramp-source", json={"activeSource": self.source}
            )
            assert r.status_code == 200, r.text
        if self._missing(TM):
            self._post("design/tunnel", sync="true")
        if self._missing(LV):
            lv = self._post("design/levels")
            assert lv["status"] == "SUCCESS", lv.get("failureReason")
        if self._missing(DM):
            self._post("design/development-mesh", sync="true")
        if self._missing(SH):
            sh = self._post("design/shafts")
            assert sh["status"] == "SUCCESS", sh.get("failureReason")
        if self._missing(N):
            net = self._post("network/generate")
            assert net["status"] == "SUCCESS", net.get("failureReason")
        if self._missing(CG):
            self._post("design/capability-graph")
        if self._missing(ST):
            self._post("design/stopes")
        if self._missing(TL):
            self._post("design/timeline")
        if self._missing(CM):
            self._post("infrastructure/communication")
        if self._missing(SN):
            self._post("infrastructure/sensors")
        present = _files(self.derived)
        # ramp_source.json is a ROOT of the cascade (never in a closure) and
        # exists only after an explicit switch: absent means LEGACY
        assert present >= ALL_FILES - {RS}, sorted(ALL_FILES - {RS} - present)
        assert (RS in present) or self.source == "LEGACY"
        assert self.client.get(f"{self.base}/design/ramp-source").json()["activeSource"] == (
            self.source
        )

    def case(self, written: tuple[str, ...], action: Callable[[], None], label: str) -> None:
        self.ensure_all()
        expected = frozenset(f.name for s in invalidated_by(written, self.source) for f in s.files)
        before = _files(self.derived)
        assert expected <= before  # the whole closure exists, so equality is meaningful
        action()
        removed = before - _files(self.derived)
        assert removed == expected, (label, self.source, sorted(removed ^ expected))
        assert "world.json" in _files(self.derived)  # outside every cascade


@pytest.mark.parametrize("source", SOURCES)
def test_every_regeneration_deletes_exactly_the_registry_closure(
    client: TestClient, design_service: DesignService, source: RampSource
) -> None:
    sid = _prepare_with_shaft(client)
    chain = _Chain(client, design_service, sid, source)
    base = chain.base
    post = chain._post
    assert not (chain.derived / RS).exists()  # the default state: no switch file yet

    def other_source() -> RampSource:
        return "LAYOUT_V2" if source == "LEGACY" else "LEGACY"

    # -- writers with an EMPTY closure (siblings / leaves) ------------------- #
    chain.case((TM,), lambda: post("design/tunnel", sync="true"), "tunnel")
    chain.case((DM,), lambda: post("design/development-mesh", sync="true"), "development mesh")
    chain.case((CG,), lambda: post("design/capability-graph"), "capability graph")
    chain.case((TL,), lambda: post("design/timeline"), "timeline")
    chain.case((CM,), lambda: post("infrastructure/communication"), "communication")
    chain.case((SN,), lambda: post("infrastructure/sensors"), "sensors")

    # -- no-op writers: nothing written, nothing deleted (probe R7 / R8 gaps) - #
    def same_source_put() -> None:
        r = client.put(f"{base}/design/ramp-source", json={"activeSource": source})
        assert r.status_code == 200 and r.json()["activeSource"] == source

    chain.ensure_all()
    before = _files(chain.derived)
    same_source_put()
    assert _files(chain.derived) == before, "a same-source switch must delete nothing"
    assert chain.chosen is not None and chain.other is not None
    post("design/layout-v2/select", {"candidateId": chain.chosen})  # idempotent re-select
    assert _files(chain.derived) == before, "an idempotent re-select must delete nothing"
    if source == "LAYOUT_V2":
        post("design/layout-v2/activate", {"candidateId": chain.chosen})  # idempotent re-activate
        assert _files(chain.derived) == before, "an idempotent re-activate must delete nothing"
        for route in ("design/tunnel", "design/levels", "network"):
            assert client.get(f"{base}/{route}").status_code == 200, route

    # -- level chain writers ------------------------------------------------ #
    chain.case((ST,), lambda: post("design/stopes"), "stopes")
    chain.case((N,), lambda: post("network/generate"), "network")
    chain.case((SH,), lambda: post("design/shafts"), "shafts")
    chain.case((LV,), lambda: post("design/levels"), "levels")

    # -- the selection: a DIFFERENT candidate is a real write --------------- #
    chain.case(
        (LS, LA),
        lambda: post("design/layout-v2/select", {"candidateId": chain.other or ""}),
        "select another candidate",
    )
    post("design/layout-v2/select", {"candidateId": chain.chosen})  # back to the known-good one

    # -- legacy chain writers (LEGACY-gated cascade) ------------------------ #
    chain.case((SM,), lambda: post("design/decline/smooth", sync="true"), "smoothed")
    chain.case((D,), lambda: post("design/decline", maxLevels="2", sync="true"), "decline")
    chain.case((T,), lambda: post("design/targets"), "targets")

    # -- the catalogue (LAYOUT_V2-gated cascade; selection pair always) ----- #
    chain.case((L,), lambda: post("design/layout-v2", sync="true"), "layout-v2 catalogue")

    # -- the source switch (unconditional cascade; selection + legacy kept) -- #
    def switch_away() -> None:
        r = client.put(f"{base}/design/ramp-source", json={"activeSource": other_source()})
        assert r.status_code == 200 and r.json()["activeSource"] == other_source()

    chain.case((RS,), switch_away, f"switch {source} → {other_source()}")
    assert (chain.derived / RS).is_file()
    for kept in (T, D, SM, L, LS, LA):
        assert (chain.derived / kept).is_file(), kept
