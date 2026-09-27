"""Phase 22A/B — Mine Analysis Core and Planning Economics.

A downstream READ-ONLY projection of the authoritative persisted mine state
(scenario document, MineNetwork, the active production artifact, the
MineTimeline) plus the user-authored ``economics.json`` into planning
quantities: development lengths / gross excavation volumes, planned mined
tonnes, schedule KPIs, planning ratios, cost / revenue summaries, a bucketed
Planning Cashflow and a Baseline Planning NPV.

Nothing here generates, regenerates, persists or modifies a derived artifact;
the analysis is computed per request from ONE validated snapshot (rule 189
analogue). Synthetic planning economics — never a resource / reserve estimate,
a feasibility study or an investment recommendation.
"""
