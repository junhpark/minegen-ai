"""The composite MineNetwork node-id grammar (AC-01I).

Node ids are ``<NodeType>:<key…>`` strings minted by the network builder
(and, for shaft stations, by the shaft planner) and RE-DERIVED by consumers
that need to find a node by its role — the timeline builder looks up
``LEVEL_ENTRY:<level>``, the capability builder ``SHAFT_COLLAR:<shaft>`` and
parses the shaft out of ``SHAFT_STATION:<shaft>:<level>``, the layout
materializer labels the ramp segment that ends at ``RAMP_JUNCTION:<level>``.
Before AC-01I each of those sites spelled the grammar again with its own
f-string (one of them without even naming the ``NodeType``), so a change to
the minting site would have silently broken the lookups. This module is the
ONE spelling. It adds no node type, changes no id and computes nothing.

Ids that are minted in exactly one place and never re-derived
(``JUNCTION``, ``STOPE_ACCESS``, ``SHAFT_BOTTOM``, the ``PORTAL`` literal)
keep their single minting site; they may move here when a second reader
appears.
"""

from __future__ import annotations

from minegen.core.enums import NodeType

PORTAL_NODE_ID = "PORTAL"


def level_entry_id(level_id: str) -> str:
    return f"{NodeType.LEVEL_ENTRY.value}:{level_id}"


def ramp_junction_id(level_id: str) -> str:
    return f"{NodeType.RAMP_JUNCTION.value}:{level_id}"


def shaft_collar_id(shaft_id: str) -> str:
    return f"{NodeType.SHAFT_COLLAR.value}:{shaft_id}"


def shaft_bottom_id(shaft_id: str) -> str:
    return f"{NodeType.SHAFT_BOTTOM.value}:{shaft_id}"


def shaft_station_id(shaft_id: str, level_id: str) -> str:
    return f"{NodeType.SHAFT_STATION.value}:{shaft_id}:{level_id}"


def shaft_station_shaft_id(node_id: str) -> str | None:
    """The shaft a ``SHAFT_STATION:<shaft>:<level>`` node belongs to, or
    ``None`` when the id does not follow the station grammar (a malformed id
    is reported by the caller, never mapped to an empty shaft)."""
    parts = node_id.split(":")
    if len(parts) < 3 or parts[0] != NodeType.SHAFT_STATION.value or not parts[1]:
        return None
    return parts[1]
