"""AnyLogic operational data adapter (Phase 23B, directive §29–§41).

MineGen network + production + timeline as a normalized data package an
AnyLogic operational model consumes (built-in database / text file import,
network-by-code from XYZ centerline points). The adapter decides nothing
about haulage: fleet, speeds, cycle times, calendars, priorities, dispatch
and capacities have no MineGen authority and stay blank template columns.
"""

from minegen.adapters.anylogic.adapter import (
    ADAPTER_NAME,
    ADAPTER_VERSION,
    build_anylogic_package,
)

__all__ = ["ADAPTER_NAME", "ADAPTER_VERSION", "build_anylogic_package"]
