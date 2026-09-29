"""Explicit units (directive §30, rule 218): a metric column is accepted
only in its canonical unit or through an EXPLICIT conversion declared in the
package manifest; nothing is inferred and no silent conversion exists."""

from __future__ import annotations

from minegen.results.errors import ResultUnitUnsupportedError
from minegen.results.models import ResultPackageManifest


def resolve_unit(
    manifest: ResultPackageManifest, metric: str, canonical: str, *, subject: str
) -> tuple[float, float]:
    """→ (factor, offset) mapping the delivered value to the canonical unit."""
    declared = manifest.units.get(metric)
    if declared is None:
        raise ResultUnitUnsupportedError(
            f"metric {metric!r} carries no declared unit in result_manifest.json "
            f"(canonical: {canonical})",
            subject=subject,
        )
    if declared == canonical:
        return 1.0, 0.0
    for conv in manifest.unit_conversions:
        if conv.metric == metric and conv.source_unit == declared:
            if conv.factor == 0.0:
                raise ResultUnitUnsupportedError(
                    f"conversion for {metric!r} declares a zero factor", subject=subject
                )
            return float(conv.factor), float(conv.offset)
    raise ResultUnitUnsupportedError(
        f"metric {metric!r} is delivered in {declared!r}; the canonical unit is "
        f"{canonical!r} and no explicit conversion is declared",
        subject=subject,
    )


def require_canonical_unit(
    manifest: ResultPackageManifest, metric: str, canonical: str, *, subject: str
) -> None:
    """Operations metrics accept the canonical unit only (no conversion table
    in 1.0); an undeclared unit is accepted as canonical ONLY when the column
    is dimensionless / count-like is NOT assumed — the kit declares them."""
    declared = manifest.units.get(metric)
    if declared is None:
        raise ResultUnitUnsupportedError(
            f"metric {metric!r} carries no declared unit (canonical: {canonical})",
            subject=subject,
        )
    if declared != canonical:
        raise ResultUnitUnsupportedError(
            f"metric {metric!r} is delivered in {declared!r}; MineResult 1.0 accepts the "
            f"canonical unit {canonical!r} only for operations metrics",
            subject=subject,
        )
