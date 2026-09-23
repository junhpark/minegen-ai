"""Typed MineExchange projection failures (Phase 23A, PR #44 correction B4).

Every semantic defect the exporter detects in its own projection — an
unresolvable network geometry reference, a duplicated entity id or bundle
path, a dangling parent, an unrecognised development id, a closed-solid QA
failure — is raised as ``ExchangeExportError`` and answered as a typed
409 ``MINE_EXCHANGE_EXPORT_FAILED``; never a bare 500, never a partial
bundle with a silent null. Validated-read refusals (STALE / MALFORMED /
READ_SNAPSHOT_CHANGED) keep their own typed codes upstream of this one.
"""

from __future__ import annotations


class ExchangeExportError(RuntimeError):
    """A mandatory bundle member cannot be produced honestly — the whole
    export fails; no partial bundle is ever returned."""

    code = "MINE_EXCHANGE_EXPORT_FAILED"
    http_status = 409

    def __init__(self, detail: str) -> None:
        super().__init__(f"MineExchange export failed: {detail}")
        self.detail = detail
