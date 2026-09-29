"""Typed MineResult failures (Phase 23C, directive §43–§44).

Every refusal carries a wire code and an HTTP status; the router maps them
verbatim. A result package the service cannot bind honestly to the current
mine is refused as a whole — never a partial result directory, never a bare
500.
"""

from __future__ import annotations

from typing import ClassVar


class ResultError(RuntimeError):
    code: ClassVar[str] = "RESULT_PACKAGE_INVALID"
    http_status: ClassVar[int] = 422

    def __init__(self, reason: str, *, subject: str | None = None) -> None:
        self.reason = reason
        self.subject = subject
        detail = reason if subject is None else f"{subject}: {reason}"
        super().__init__(f"{self.code}: {detail}")


class ResultPackageInvalidError(ResultError):
    """Not a readable MineResult package: bad ZIP, unsafe / duplicate member,
    missing required file, malformed manifest, non-UTF-8 text, a persisted
    result folder that no longer validates (READ ≠ TRUST)."""

    code = "RESULT_PACKAGE_INVALID"
    http_status = 422


class ResultVersionUnsupportedError(ResultError):
    code = "RESULT_VERSION_UNSUPPORTED"
    http_status = 422


class ResultSourceScenarioMismatchError(ResultError):
    code = "RESULT_SOURCE_SCENARIO_MISMATCH"
    http_status = 409


class ResultSourceSnapshotMismatchError(ResultError):
    code = "RESULT_SOURCE_SNAPSHOT_MISMATCH"
    http_status = 409


class ResultIdentityUnresolvedError(ResultError):
    code = "RESULT_IDENTITY_UNRESOLVED"
    http_status = 409


class ResultIdentityAmbiguousError(ResultError):
    code = "RESULT_IDENTITY_AMBIGUOUS"
    http_status = 409


class ResultUnitUnsupportedError(ResultError):
    code = "RESULT_UNIT_UNSUPPORTED"
    http_status = 422


class ResultDataInvalidError(ResultError):
    code = "RESULT_DATA_INVALID"
    http_status = 422


class ResultLimitExceededError(ResultError):
    code = "RESULT_LIMIT_EXCEEDED"
    http_status = 413


class ResultNotFoundError(ResultError):
    code = "RESULT_NOT_FOUND"
    http_status = 404


class ResultStaleError(ResultError):
    """A frame / overlay was requested for a result whose source snapshot is
    not the current mine (rule 215): listable, exportable, deletable — never
    drawn over a mine it does not describe."""

    code = "RESULT_STALE"
    http_status = 409


class ResultPublicationFailedError(ResultError):
    code = "RESULT_PUBLICATION_FAILED"
    http_status = 500
