"""Build the Korean–English UI glossary workbook from the frontend dictionary.

    python scripts/i18n_glossary.py            # writes docs/i18n/glossary-ko-en.xlsx
    python scripts/i18n_glossary.py --out X    # elsewhere

Sheet "UI strings": every entry of ``frontend/src/i18n/ko.ts`` (English source
string → Korean), grouped by a coarse area guess, with a blank "검토" column for
the reviewer. Sheet "Terminology": ``docs/i18n/terminology.json`` — the mining
terms the translations follow, with the reasoning per term. The dictionary
file is read line by line (one JSON-encoded pair per line, see ko.ts), so no
TypeScript parser is needed; ``openpyxl`` is the only dependency (install it
in any environment — it is not a project dependency).
"""

# ruff: noqa: E501  (the area rules are long alternations — a data table, not prose)
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KO_TS = ROOT / "frontend" / "src" / "i18n" / "ko.ts"
TERMS = ROOT / "docs" / "i18n" / "terminology.json"
DEFAULT_OUT = ROOT / "docs" / "i18n" / "glossary-ko-en.xlsx"

TOKEN = re.compile(
    r"""'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|([A-Za-z_$][A-Za-z0-9_$]*)|(//[^\n]*|/\*.*?\*/)""",
    re.S,
)
ESCAPES = {"n": "\n", "t": "\t", "'": "'", '"': '"', "\\": "\\"}


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: ESCAPES.get(m.group(1), m.group(1)), s)


def read_dictionary(path: Path) -> list[tuple[str, str]]:
    """The `KO` object literal as (key, value) pairs.

    Prettier formats the file (unquoted identifier keys, single quotes, a long
    value on its own line), so the literal is tokenized — quoted strings,
    identifiers, comments — and consecutive (key, value) string tokens are
    paired; a TypeScript parser is not needed.
    """
    text = path.read_text(encoding="utf-8")
    start = text.index("= {", text.index("export const KO")) + 3
    body = text[start : text.rindex("}")]
    tokens: list[str] = []
    for m in TOKEN.finditer(body):
        if m.group(4) is not None:
            continue  # a comment
        if m.group(3) is not None:
            tokens.append(m.group(3))
        else:
            tokens.append(_unescape(m.group(1) if m.group(1) is not None else m.group(2)))
    if len(tokens) % 2 != 0 or not tokens:
        raise SystemExit(f"could not pair the dictionary tokens of {path}")
    return list(zip(tokens[0::2], tokens[1::2], strict=True))


AREA_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "셸 · 리본 · 흐름",
        re.compile(
            r"^(Setup|Design$|Network$|Mining$|Systems$|Analysis$|Export$|View$|Reset|Quick|File|Demo|"
            r"Controls|Status & results|Layers|Camera|Panels|Flow|Iso|Top|Fit|3D|4D|Walk|Mine development|"
            r"click a stage|Hide the|New mine|Open|Demos|Import results|Loading|Baking|No demos|No saved|"
            r"backend|Cancel|Retry|Delete|Reading|Regenerating|Clear design|The mine changed|"
            r"The backend will|Nothing to reset|Back to the generated|No design artifact|The reset plan|"
            r"Show or hide|Terrain|Scenario fault|Spatial-field|The active ramp|Level development:|"
            r"Shaft axes|Mine network nodes|Production geometry \(|Communication routers|"
            r"Generate a world first|Open a mine first|Not in Walk|Walk shows|This stage|A job is|"
            r"Delete the|Create or open|Mining method and|Access strategy:|Layout v2 candidates|"
            r"Excavation meshes|Plan the declared|Mine network:|Capability graph over|"
            r"Production geometry of|Schedule:|Communication placement|Gas sensor placement|"
            r"Analysis workspace|Export:|The static|The scheduled|First-person|Isometric|Plan view|"
            r"Fit the|UI language|\{tab\}|\{n\} (level|shaft|edge|capab|router|sensor|more)|ramp \+|"
            r"ramp tunnel|none declared|ends day|shown|downloaded|legacy|layout|\{feasible\}|ready|"
            r"not generated|no mine|none|failed|Ready|Running|Failed|Not generated|Active|Inactive|"
            r"Details|Advanced|About|development stages|mine development|ribbon|view mode|"
            r"camera presets|\{title\}|\{id\}|demo|unavailable|▾|Switch to the 4D|Schedule the mine)"
        ),
    ),
    (
        "설정 · 시나리오 · 채광법 · 접근",
        re.compile(
            r"^(Scenario|Name|Preset|Seed|Faults|Randomize|Create mine|Creating|Generate world|"
            r"Regenerate world|Generating world|Same seed|Edited|Saved mines|No mine|World|Model depth|"
            r"Orebody|Strike|Dip|Thickness|Nominal|Morphology|Add fault|Core|Infl|Damage|Corr|Density|"
            r"Outline|Warp|Pinch|Variab|Field|A synthetic mine|Mining method|Method|Apply method|"
            r"Applying|Sublevel|Stope length|Minimum pillar|Lift|Cut length|Panel|Rib|Room|Pillar|"
            r"Boundary|Heading|Bench|Block order|Stoping|Overhand|Underhand|Shallow|Deep|Concurrent|"
            r"Sill|Change|Access strategy|Apply access|Add shaft|Shaft id|Role|Suggest|Ramp only|"
            r"Ramp \+|How the mine|The mining method|Persist|Preview|Rewrites|Longhole|Cut & Fill|"
            r"Room & Pillar|Sublevel Caving|Shrinkage|Implemented|Not implemented|TABULAR|ELLIPSOID|"
            r"WARPED|Irregular|Thickness var|synthetic|numerical|Below terrain|Origin|Center|Ore z|"
            r"access strategy|default collar|explicit collar|Irregular)"
        ),
    ),
    (
        "설계 · 배치 · 레벨 · 굴착 · 수갱",
        re.compile(
            r"^(Mine layout|Layout|Option|Candidate|Generate candidates|Regenerate candidates|Searching|"
            r"Select|Activat|Current design|Active ramp|Clearance|Access reach|Search|Enumerates|"
            r"Generate candidate|show infeasible|Level|Drifts|Crosscuts|Entries|Station|"
            r"Production development|Geometry|Generate level|Regenerate level|Laying|Development mesh|"
            r"Generate development|Regenerate development|Sweeping|Ramp tunnel|Generate ramp|"
            r"Regenerate ramp|Rings|Triangles|Nominal volume|Mesh|Wall|Draw|Generated in|Shafts|Shaft|"
            r"Plan shafts|Regenerate shafts|Planning shafts|Optional vertical|The excavation|"
            r"The ramp excavation|No shaft|Plan the shafts|Validated effective|Raw|Legacy|"
            r"Effective ramp|Drifts and|Design assessment|DESIGN ASSESSMENT|Read-only|Authority|"
            r"Evidence|Source|Why not|Detail|By group|Score|\{a\}|\{s\}|\{m\}|\{total\}|\{option\}|"
            r"grade|ramp \{|access \{|rank|Hard design|Derived|Design (validation|advisory)|"
            r"Informational|Active design|Inactive|Egress|criterion|satisfied|not satisfied|NOT |"
            r"All required|Capability graph valid|Delivered|Dual-egress|Orebody clearance|"
            r"Required capability|Selected candidate|\(inactive\)|SPIRAL|SWITCHBACK|LONGITUDINAL|"
            r"FEASIBLE|INFEASIBLE|NOT_VALIDATED|Along strike|Footwall|Rock quality|Fault|Cost / m|"
            r"Next level|Rejected|rejected|valid|Position|Nothing selected|Exclusion|Inspector|"
            r"Decline profile|Completed decline|option detail|check detail|candidate|current design|"
            r"design (assessment|rulebook)|engineering|ranking|selection|layout|level access|"
            r"preferred|ramp source|generate|no feasible|no layout|Teleport|Go to|Minimap)"
        ),
    ),
    (
        "네트워크 · 기능",
        re.compile(
            r"^(Mine network|Build network|Rebuild network|Building|Ramps|Drop|Surface|Capabilit|"
            r"Build capab|Rebuild capab|Assigning|Where connections|What each connection|"
            r"Requires a successful|connected|split|watertight|open$|Network)"
        ),
    ),
    (
        "생산 · 일정",
        re.compile(
            r"^(Production|Generate Stopes|Generate Cuts|Generate Rooms|Generating|Stopes|Cuts|Backfill|"
            r"Lifts|Blocks|Cemented|Mean|Geometric|Tonnes|Grade proxy|Rooms|Headings|Pillars|Mined|"
            r"Extraction|The planned|Schedule|Reschedule|Scheduling|Development tasks|First stoping|"
            r"An earliest|Deterministic|Tasks|Task|Start|End|Days|Cumulative|Current day|Play|Pause|"
            r"Restart|Loop|Return to 4D|Timeline|stopes|cuts|benches|units|\{n\} \{noun\}|\{n\} tasks|"
            r"authoritative|rerun|Snapshot)"
        ),
    ),
    (
        "시스템 · 통신 · 센서",
        re.compile(
            r"^(Communication|Plan communication|Replan|Planning communication|Routers|Mesh router|"
            r"Coverage|Backhaul|Candidate / demand|Underground mesh|Sensors|Place sensors|Replace|"
            r"Placing|Gas|Monitoring|Required coverage|Serving|Gas-sensor|Hop|Asset|Sensor OSP|"
            r"Communication OSP|Distance)"
        ),
    ),
    (
        "분석 · 경제성",
        re.compile(
            r"^(Analysis|Overview|Economics|Sensitivity|Rules|Layouts|Simulation|Planning|Mine life|"
            r"Mine duration|First production|Baseline|Development|Gross|Ratios|Total|Currency|"
            r"Processing|Fixed|Initial|Revenue|Net|Undiscounted|Discount|Cost|Rates|Comparable|"
            r"Included|Ranking|Engineering|Load a scenario|Save assumptions|Saving|Use demo|Configure|"
            r"Reset to scenario|Writes economics|Loads illustrative|Evaluate|Evaluating|Percent|"
            r"Base \(|All cases|Parameter|Metric|Maximum|Minimum|Std|Quantities|Level coverage|"
            r"Levels excluded|Required levels|The figures|Design Rulebook|Category|Rule|Scope|Status|"
            r"Info|planning|No Planning|Cost, revenue|comparable|assessment scope|rulebook|scores|"
            r"Available|Not available|Not configured|Type|Samples|Show 3D|Available)"
        ),
    ),
    (
        "내보내기 · 결과 · 워크스루",
        re.compile(
            r"^(Export|MineExchange|Ventsim|AnyLogic|Unity|Unreal|Package|Import|Importing|MineResult|"
            r"Result|Download|Show overlay|Hide overlay|Heatmap|Edge metric|Ventilation|Operations|"
            r"Loading frame|E Inspect|Timeline snapshot|display range|result clock|no value|file|"
            r"Export contents|Export group|Migration|Note|Description|Remove|Error|Expanded|Target)"
        ),
    ),
]


def area_of(key: str) -> str:
    for name, rx in AREA_RULES:
        if rx.search(key):
            return name
    return "기타"


def build(out: Path) -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit("openpyxl is required: pip install openpyxl") from exc

    pairs = read_dictionary(KO_TS)
    terms = json.loads(TERMS.read_text(encoding="utf-8"))
    wb = Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="2C353E")
    wrap = Alignment(wrap_text=True, vertical="top")

    ws = wb.active
    ws.title = "UI strings"
    ws.append(["#", "영역", "English (source string)", "한국어", "검토 (OK / 수정안)", "비고"])
    rows = sorted(pairs, key=lambda kv: (area_of(kv[0]), kv[0].lower()))
    for i, (en, ko) in enumerate(rows, 1):
        ws.append([i, area_of(en), en, ko, "", ""])
    for col, width in zip("ABCDEF", (6, 22, 70, 60, 18, 24), strict=True):
        ws.column_dimensions[col].width = width
    for cell in ws[1]:
        cell.font = head_font
        cell.fill = head_fill
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"

    wt = wb.create_sheet("Terminology")
    wt.append(["분야", "English", "한국어 (채택)", "근거 · 대안", "검토 (OK / 수정안)"])
    for area, en, ko, note in terms:
        wt.append([area, en, ko, note, ""])
    for col, width in zip("ABCDE", (16, 34, 30, 80, 18), strict=True):
        wt.column_dimensions[col].width = width
    for cell in wt[1]:
        cell.font = head_font
        cell.fill = head_fill
    for row in wt.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
    wt.freeze_panes = "A2"

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"{out}: {len(rows)} UI strings, {len(terms)} terms")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    build(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
