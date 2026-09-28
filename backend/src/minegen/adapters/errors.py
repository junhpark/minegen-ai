"""Typed adapter failures (``docs/external-adapters.md`` §8).

One generic failure covering every case is not acceptable: each failure
names the bundle group, entity or parameter concerned in ``detail`` and
carries the contract code the API answers with. Client-side defects
(a parameter the adapter cannot honour) are 422; a bundle the adapter cannot
translate honestly is 409 — never a bare 500, never a partial package.
"""

from __future__ import annotations

from typing import ClassVar


class AdapterError(RuntimeError):
    """Base of every typed adapter failure (``code`` / ``http_status``)."""

    code: ClassVar[str] = "ADAPTER_CONVERSION_FAILED"
    http_status: ClassVar[int] = 409

    def __init__(self, detail: str) -> None:
        super().__init__(f"{self.code}: {detail}")
        self.detail = detail


class MineExchangeBundleInvalidError(AdapterError):
    """The bundle is not a readable, integral MineExchange bundle (bad ZIP,
    missing / malformed manifest, hash mismatch, unlisted or unsafe entry,
    a document that does not validate against its declared DTO)."""

    code = "MINEEXCHANGE_BUNDLE_INVALID"
    http_status = 409


class MineExchangeVersionUnsupportedError(AdapterError):
    code = "MINEEXCHANGE_VERSION_UNSUPPORTED"
    http_status = 409


class RequiredSourceAbsentError(AdapterError):
    """A bundle group the adapter needs is ABSENT or SOURCE_NOT_SUCCESS; the
    bundle's own omission reason is carried through in ``detail``."""

    code = "REQUIRED_SOURCE_ABSENT"
    http_status = 409


class RequiredParameterMissingError(AdapterError):
    code = "REQUIRED_PARAMETER_MISSING"
    http_status = 422


class TargetFormatUnsupportedError(AdapterError):
    code = "TARGET_FORMAT_UNSUPPORTED"
    http_status = 422


class CoordinateMappingUnsupportedError(AdapterError):
    code = "COORDINATE_MAPPING_UNSUPPORTED"
    http_status = 422


class AdapterConversionFailedError(AdapterError):
    """A conversion defect the adapter detected in its own translation
    (duplicate target id, dangling reference, endpoint not welded to its
    topology node, non-finite value)."""

    code = "ADAPTER_CONVERSION_FAILED"
    http_status = 409
