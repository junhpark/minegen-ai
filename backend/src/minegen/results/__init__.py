"""MineResult 1.0 — external simulation results imported over MineExchange
bundles and overlaid on the mine (Phase 23C, rules 213–218).

    package.py        ZIP / manifest / CSV reader with explicit input budgets
    importers/        Ventsim (ventilation) and AnyLogic (operations) importers
    normalization.py  canonical arrays, digest and deterministic resultId
    geometry.py       source-snapshot edge centerlines, chainage → XYZ
    frames.py         ventilation / operations frame builders (hold-last)
    store.py          results/<resultId>/ atomic publication (outside derived/)
    export.py         canonical MineResult ZIP re-export
    services/result_service.py  import (observe → parse → validate →
                      re-observe → publish), list / detail / delete / export / frames
"""

from minegen.results.models import MINE_RESULT_VERSION

__all__ = ["MINE_RESULT_VERSION"]
