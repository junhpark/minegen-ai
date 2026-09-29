"""Typed adapter failures (``docs/external-adapters.md`` §8, directive §51).

One generic failure covering every case is not acceptable: every failure
names the ADAPTER, the bundle SOURCE GROUP (when one is concerned), the
ENTITY / FILE / PARAMETER (``subject``) and the REASON, and carries the
contract code the API answers with. A bundle the adapter cannot translate
honestly is a typed 409 — never a bare 500, never a partial package.
"""

from __future__ import annotations

from typing import ClassVar


class AdapterError(RuntimeError):
    """Base of every typed adapter failure (``code`` / ``http_status``)."""

    code: ClassVar[str] = "ADAPTER_CONVERSION_FAILED"
    http_status: ClassVar[int] = 409

    def __init__(
        self,
        reason: str,
        *,
        adapter: str,
        source_group: str | None = None,
        subject: str | None = None,
    ) -> None:
        self.adapter = adapter
        self.source_group = source_group
        self.subject = subject
        self.reason = reason
        parts = [f"adapter={adapter}"]
        if source_group is not None:
            parts.append(f"group={source_group}")
        if subject is not None:
            parts.append(f"subject={subject}")
        parts.append(f"reason={reason}")
        self.detail = "; ".join(parts)
        super().__init__(f"{self.code}: {self.detail}")


class MineExchangeBundleInvalidError(AdapterError):
    """The input is not a readable, integral MineExchange bundle (bad ZIP,
    missing / malformed manifest, hash mismatch, unlisted or unsafe entry,
    a document that does not validate against its declared DTO, a dangling
    reference the bundle preflight should have refused)."""

    code = "ADAPTER_MINEEXCHANGE_BUNDLE_INVALID"


class MineExchangeVersionUnsupportedError(AdapterError):
    code = "ADAPTER_MINEEXCHANGE_VERSION_UNSUPPORTED"


class RequiredSourceAbsentError(AdapterError):
    """A bundle group the adapter needs was never generated (the bundle
    records ``ARTIFACT_ABSENT`` / ``NOT_IN_V1``)."""

    code = "ADAPTER_REQUIRED_SOURCE_ABSENT"


class RequiredSourceNotSuccessError(AdapterError):
    """A bundle group the adapter needs exists but its authority is FAILED
    (the bundle records ``SOURCE_NOT_SUCCESS``)."""

    code = "ADAPTER_SOURCE_NOT_SUCCESS"


class AdapterConversionFailedError(AdapterError):
    """A conversion defect the adapter detected in its own translation
    (duplicate target id, dangling reference, a polyline whose end points
    are not its topology nodes, an invalid GLB, a non-finite value)."""

    code = "ADAPTER_CONVERSION_FAILED"


class AdapterTargetUnsupportedError(AdapterError):
    """The requested target application / format is not one this adapter
    set produces."""

    code = "ADAPTER_TARGET_UNSUPPORTED"
    http_status = 422
