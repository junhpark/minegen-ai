"""Hardening H1 §4.5 — the guided-workflow shell, end to end in a real browser.

One BASELINE mine is driven through the shell exactly as a user would:
Setup (Create mine → Method) → Layout (Option 1, Activate) → Levels →
Excavation → Network → Capability → Production → Schedule → Communication →
Sensors → Analysis → Export (MineExchange download). Then "Reset from here"
on Levels: the confirm dialog lists the backend reset plan verbatim, the
closure is deleted, and Levels regenerates from that stage. At every stop at
most ONE enabled primary button exists in the DOM.

Hardening PR-2 (§5 header: "e2e: BASELINE + CUT_AND_FILL 데모
Setup→Analysis→Export"): the stack also carries the CUT_AND_FILL demo, baked
into the temporary data directory through the application's own routes
(``minegen.demos.bake``) before the servers start, and a second test opens
it from File › Demos — read-only demo mode (badge, demo panel, ONE primary
"Clone to edit", 4D Loop on, the 4D results card), the full-window Analysis
workspace (no canvas, KPI tiles, Show 3D context) and the Export download.

The stack is real: a uvicorn backend on a temporary data directory and the
Vite dev server pointed at it, both on free ports; the browser is the
Playwright Chromium (``MINEGEN_E2E_CHROMIUM`` or the Playwright default).
The test is skipped — never silently passed — when Playwright, Node or the
browser are unavailable — unless ``MINEGEN_E2E_REQUIRED=1`` (the FULL e2e
release gate, PR #53 review round 3 B3), where every such condition is a
FAILURE: a required gate never skips. Marker ``e2e`` + ``slow`` (FULL only).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

#: round 3 B3 — under the release gate a missing prerequisite fails the test
REQUIRED = os.environ.get("MINEGEN_E2E_REQUIRED") == "1"


def _unavailable(reason: str) -> None:
    """Skip, or FAIL when the e2e is a required gate (a skip is not evidence)."""
    if REQUIRED:
        pytest.fail(f"required browser e2e cannot run: {reason}")
    pytest.skip(reason)


if REQUIRED:
    import playwright.sync_api as playwright  # a missing Playwright fails collection
else:
    playwright = pytest.importorskip("playwright.sync_api")

REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
BACKEND_SRC = REPO / "backend" / "src"

# troika-three-text (drei <Text>) resolves fallback fonts from a CDN; without
# network the pending resolution stalls React commits, so the test serves a
# hermetic resolver + a local TTF through a request route when one exists.
LOCAL_FONTS = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
]
FONT_CDN = "https://cdn.jsdelivr.net/**"

JOB_TIMEOUT_MS = 420_000


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as res:
                if res.status < 500:
                    return
        except Exception as e:
            last = e
        time.sleep(0.25)
    raise RuntimeError(f"{url} not reachable: {last}")


def _chromium_path() -> str | None:
    explicit = os.environ.get("MINEGEN_E2E_CHROMIUM")
    if explicit and Path(explicit).exists():
        return explicit
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if root and (Path(root) / "chromium").exists():
        return str(Path(root) / "chromium")
    return None


#: hardening PR-2 H4 — the demo the second test opens (baked in-process)
DEMO_ID = "demo-tabular-cut-fill"


def _bake_cut_fill_demo(demos_dir: Path) -> None:
    """Bake the CUT_AND_FILL demo recipe into ``demos_dir`` exactly as
    ``scripts/bake_demos.py`` does (the same baker, the same routes), so the
    backend started on this data directory serves it read-only."""
    sys.path.insert(0, str(BACKEND_SRC))
    from minegen.demos.bake import DEMO_RECIPES, DemoBaker, write_index

    recipe = next(r for r in DEMO_RECIPES if r.id == DEMO_ID)
    baker = DemoBaker(demos_dir)
    try:
        entry = baker.bake(recipe)
    finally:
        baker.close()
    write_index(demos_dir, [entry], "shell-e2e")


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    if shutil.which("npm") is None or not (FRONTEND / "node_modules").exists():
        _unavailable("frontend toolchain (npm + node_modules) not available")
    data_dir = tmp_path_factory.mktemp("shell-e2e-data")
    _bake_cut_fill_demo(data_dir / "demos")
    api_port, web_port = _free_port(), _free_port()
    api = f"http://127.0.0.1:{api_port}"
    web = f"http://127.0.0.1:{web_port}"
    env = {
        **os.environ,
        "MINEGEN_DATA_DIR": str(data_dir),
        "MINEGEN_CORS_ORIGINS": json.dumps([web]),
    }
    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "minegen.main:app",
            "--app-dir",
            str(BACKEND_SRC),
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
            "--log-level",
            "warning",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    frontend = subprocess.Popen(
        [
            "npm",
            "run",
            "--silent",
            "dev",
            "--",
            "--host",
            "127.0.0.1",
            "--port",
            str(web_port),
            "--strictPort",
        ],
        cwd=FRONTEND,
        env={**os.environ, "VITE_API_BASE_URL": api},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_http(f"{api}/api/v1/health", 60)
        _wait_http(web, 60)
        yield {"api": api, "web": web, "data_dir": data_dir}
    finally:
        for proc in (frontend, backend):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope="module")
def browser(stack: dict[str, Any]) -> Iterator[tuple[Any, list[str]]]:
    exe = _chromium_path()
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        except Exception as e:
            _unavailable(f"Playwright Chromium not available: {str(e)[:120]}")
            raise
        pg = browser.new_page(viewport={"width": 1600, "height": 950})
        font = next((f for f in LOCAL_FONTS if f.exists()), None)
        if font is not None:
            font_bytes = font.read_bytes()

            def route_cdn(route: Any, request: Any) -> None:
                url = request.url
                if "codepoint-index" in url:
                    body = '[1,{"en":{"latin":"' + "o" * 43 + '"}}]'
                    route.fulfill(status=200, content_type="application/json", body=body)
                elif "font-meta" in url:
                    body = (
                        '[1,{"id":"latin","typeforms":{"sans-serif":{"normal":[400]}},'
                        '"ranges":"0-FFFF"}]'
                    )
                    route.fulfill(status=200, content_type="application/json", body=body)
                elif "font-files" in url:
                    route.fulfill(status=200, content_type="font/ttf", body=font_bytes)
                else:
                    route.abort()

            pg.route(FONT_CDN, route_cdn)
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(stack["web"])
        pg.wait_for_selector('[data-testid="stepper"]', timeout=60_000)
        yield pg, errors
        browser.close()


# --------------------------------------------------------------------------- #
# shell helpers (DOM contracts of the shell — data-testid / data-* only)
# --------------------------------------------------------------------------- #


def _primaries(page: Any) -> int:
    return int(page.locator('button[data-variant="primary"]:enabled').count())


def _current_stage(page: Any) -> str | None:
    loc = page.locator('[data-testid="stepper"] [aria-current="step"]')
    return str(loc.get_attribute("data-stage")) if loc.count() else None


def _assert_single_primary(page: Any, where: str) -> None:
    n = _primaries(page)
    assert n <= 1, f"{n} enabled primary buttons at {where}"


def _glyphs(page: Any) -> dict[str, str]:
    return {
        str(e.get_attribute("data-stage")): str(e.get_attribute("data-glyph"))
        for e in page.locator('[data-testid="stepper"] button').all()
    }


def _wait_glyph(page: Any, stage: str, glyph: str, timeout: int = JOB_TIMEOUT_MS) -> None:
    try:
        page.wait_for_selector(
            f'[data-testid="stepper"] [data-stage="{stage}"][data-glyph="{glyph}"]',
            timeout=timeout,
        )
    except playwright.TimeoutError as e:
        # the failure names the stepper as it IS, not only the glyph it waited for
        raise AssertionError(f"{stage} never became {glyph}; stepper = {_glyphs(page)}") from e


def _click_stage(page: Any, stage: str) -> None:
    page.click(f'[data-testid="stepper"] [data-stage="{stage}"]')
    page.wait_for_selector(f'[data-testid="stepper"] [data-stage="{stage}"][aria-current="step"]')
    _assert_single_primary(page, f"stage {stage}")


def _controls(page: Any, text: str) -> Any:
    return page.locator('[data-testid="controls-host"] button', has_text=text)


def _generate(page: Any, stage: str, button: str, timeout: int = JOB_TIMEOUT_MS) -> None:
    _click_stage(page, stage)
    _controls(page, button).first.click()
    _wait_glyph(page, stage, "DONE", timeout)
    _assert_single_primary(page, f"after {stage}")


# --------------------------------------------------------------------------- #
# the flow
# --------------------------------------------------------------------------- #


def test_baseline_setup_to_export_single_primary_and_reset(
    browser: tuple[Any, list[str]], stack: dict[str, Any]
) -> None:
    page, errors = browser
    # 1 Setup › Scenario: ONE primary — Create mine (create + world in one step)
    assert _current_stage(page) == "SCENARIO"
    assert _primaries(page) == 1
    _controls(page, "Create mine").click()
    _wait_glyph(page, "SCENARIO", "DONE", 180_000)
    page.wait_for_selector('[data-testid="stepper"] [data-stage="METHOD"][aria-current="step"]')
    _assert_single_primary(page, "Method")
    # the mine exists on disk under the temporary data dir
    scenarios = list((stack["data_dir"] / "scenarios").iterdir())
    assert len(scenarios) == 1
    assert (scenarios[0] / "arrays.npz").exists()

    # 1 Setup › Access (PR #54 review B3): the access strategy is declared
    # BEFORE the layout — Ramp only is done already; Ramp + Shaft is applied
    # through the scenario PUT behind the reset-plan confirmation and makes
    # Shafts a real (waiting) stage instead of an optional one
    _wait_glyph(page, "ACCESS", "DONE")
    _wait_glyph(page, "SHAFTS", "OPTIONAL")
    _click_stage(page, "ACCESS")
    assert _primaries(page) == 0  # a clean declaration offers no primary action
    page.check('[data-testid="access-ramp-shaft"]')
    page.wait_for_selector('[data-testid="shaft-editor"] [data-testid="shaft-spec"]')
    suggest = page.locator('[data-testid="shaft-editor"] button:has-text("Suggest collar")')
    assert suggest.count() == 0  # no level development yet: the planner derives the collar
    _assert_single_primary(page, "Access with a dirty declaration")
    _controls(page, "Apply access strategy").click()
    page.wait_for_selector('[data-testid="access-will-delete"], [role="dialog"]')
    page.click('[role="dialog"] button:has-text("Apply access strategy")')
    _wait_glyph(page, "ACCESS", "DONE", 180_000)
    _wait_glyph(page, "SHAFTS", "WAITING")
    assert _primaries(page) == 0
    page.wait_for_selector('[data-testid="access-ramp-shaft"]:checked')

    # 2 Design › Layout: Generate → Option 1 → Activate
    _click_stage(page, "LAYOUT")
    _controls(page, "Generate candidates").click()
    page.wait_for_selector(
        '[data-testid="controls-host"] button:has-text("Option 1")', timeout=JOB_TIMEOUT_MS
    )
    rows = page.locator('[data-testid="controls-host"] [aria-label="layout candidates"] button')
    assert rows.first.inner_text().startswith("Option 1")
    _controls(page, "Activate").first.click()
    _wait_glyph(page, "LAYOUT", "DONE")
    _assert_single_primary(page, "after activate")

    # Levels, Excavation (ramp mesh first, then development mesh)
    _generate(page, "LEVELS", "Generate level development")
    _click_stage(page, "EXCAVATION")
    _controls(page, "Generate ramp tunnel mesh").click()
    page.wait_for_selector(
        '[data-testid="controls-host"] button:has-text("Regenerate ramp tunnel mesh"):enabled',
        timeout=JOB_TIMEOUT_MS,
    )
    _assert_single_primary(page, "between the two meshes")
    _controls(page, "Generate development mesh").click()
    _wait_glyph(page, "EXCAVATION", "DONE")

    # Shafts (PR #54 review B3): PLAN the declared shaft, then its mesh — the
    # stage is done only with both; the declaration itself is not editable here
    _click_stage(page, "SHAFTS")
    assert page.locator('[data-testid="controls-host"] [data-testid="shaft-editor"]').count() == 0
    _controls(page, "Plan shafts").click()
    page.wait_for_selector(
        '[data-testid="controls-host"] button:has-text("Generate shaft mesh"):enabled',
        timeout=JOB_TIMEOUT_MS,
    )
    _wait_glyph(page, "SHAFTS", "NEXT")  # the plan alone is not the stage: still next
    _assert_single_primary(page, "between the shaft plan and its mesh")
    _controls(page, "Generate shaft mesh").click()
    _wait_glyph(page, "SHAFTS", "DONE")
    assert (scenarios[0] / "derived" / "shaft_mesh.glb").exists()

    # 3 Network · 4 Mining · 5 Systems
    _generate(page, "NETWORK", "Build network")
    _generate(page, "CAPABILITY", "Build capabilities")
    _generate(page, "PRODUCTION", "Generate Stopes")
    _generate(page, "SCHEDULE", "Schedule development")
    _generate(page, "COMMUNICATION", "Plan communication")
    _generate(page, "SENSORS", "Place sensors")

    # 6 Analysis is NEXT once the Systems stages are done (review round 2 S2:
    # the guided flow has no dead end). Round 3 B1: opened from the 4D VIEW it
    # must still show the centre workspace — the stage click alone never
    # completes it, the shown workspace does
    _wait_glyph(page, "ANALYSIS", "NEXT")
    _wait_glyph(page, "EXPORT", "WAITING")
    page.click('[data-testid="view-switcher"] button:has-text("4D")')
    page.wait_for_selector('[data-testid="stepper"]')
    assert page.locator('[data-testid="analysis-center"]').count() == 0
    # PR-2 H3 §7: the 4D view carries Restart / Play / Loop / speed and the
    # backend time-series results card in the right column
    for tid in ("timeline-restart", "timeline-play", "timeline-loop", "timeline-speed-20"):
        assert page.locator(f'[data-testid="{tid}"]').count() == 1, tid
    page.wait_for_selector('[data-testid="fourd-results"]')
    _click_stage(page, "ANALYSIS")
    page.wait_for_selector('[data-testid="analysis-center"]')
    assert _primaries(page) == 0
    # PR-2 H3 §8.3: the Analysis workspace is full-window — no canvas unless
    # "Show 3D context" is on — and heads every tab with the KPI tiles
    assert page.locator("canvas").count() == 0
    page.wait_for_selector('[data-testid="analysis-kpis"]')
    page.check('[data-testid="analysis-show-3d"]')
    page.wait_for_selector("canvas")
    assert page.locator('[data-testid="analysis-center"][data-split="true"]').count() == 1
    page.uncheck('[data-testid="analysis-show-3d"]')
    page.wait_for_selector("canvas", state="detached")
    _wait_glyph(page, "ANALYSIS", "DONE")
    _wait_glyph(page, "EXPORT", "NEXT")

    # 7 Export: the MineExchange bundle downloads, which completes the stage
    _click_stage(page, "EXPORT")
    with page.expect_download(timeout=JOB_TIMEOUT_MS) as dl:
        _controls(page, "Export MineExchange").click()
    assert dl.value.suggested_filename.endswith(".zip")
    _wait_glyph(page, "EXPORT", "DONE")

    # Reset from Levels: the dialog lists the backend plan; the closure is deleted
    derived = scenarios[0] / "derived"
    assert (derived / "levels.json").exists() and (derived / "network.json").exists()
    _click_stage(page, "LEVELS")
    page.click('[data-testid="reset-from-here"]')
    page.wait_for_selector('[data-testid="reset-will-delete"]')
    listed = page.locator('[data-testid="reset-will-delete"] li').all_inner_texts()
    assert "levels.json" in listed and "network.json" in listed and "timeline.json" in listed
    assert "shafts.json" in listed and "shaft_mesh.json" in listed  # planned on the levels
    assert "layout_v2_selected.json" not in listed  # upstream is never part of the closure
    page.click('[role="dialog"] button:has-text("Delete")')
    _wait_glyph(page, "LEVELS", "NEXT")
    # review round 2 S1 / S2: Excavation waits for Levels (the tunnel survives
    # the reset, rule 74, but the stage is not next), and the viewer-completed
    # Analysis / Export wait again behind the broken chain
    _wait_glyph(page, "EXCAVATION", "WAITING")
    _wait_glyph(page, "ANALYSIS", "WAITING")
    _wait_glyph(page, "EXPORT", "WAITING")
    assert not (derived / "levels.json").exists()
    assert not (derived / "network.json").exists()
    assert (derived / "layout_v2_selected.json").exists()
    _assert_single_primary(page, "after reset")
    # …and the stage regenerates from here
    _controls(page, "Generate level development").click()
    _wait_glyph(page, "LEVELS", "DONE")
    assert (derived / "levels.json").exists()
    # round 3 B2: rebuilding the whole chain on the NEW mine state brings
    # Analysis back as NEXT — the completions established on the previous
    # mine never revive (Export stays WAITING behind it) — and showing the
    # workspace again completes it for the new revision
    _click_stage(page, "EXCAVATION")
    _controls(page, "Generate development mesh").click()
    _wait_glyph(page, "EXCAVATION", "DONE")
    # the declared shaft survives the reset (it is the scenario's), its plan does not
    _wait_glyph(page, "SHAFTS", "NEXT")
    _click_stage(page, "SHAFTS")
    _controls(page, "Plan shafts").click()
    page.wait_for_selector(
        '[data-testid="controls-host"] button:has-text("Generate shaft mesh"):enabled',
        timeout=JOB_TIMEOUT_MS,
    )
    _controls(page, "Generate shaft mesh").click()
    _wait_glyph(page, "SHAFTS", "DONE")
    _generate(page, "NETWORK", "Build network")
    _generate(page, "CAPABILITY", "Build capabilities")
    _generate(page, "PRODUCTION", "Generate Stopes")
    _generate(page, "SCHEDULE", "Schedule development")
    _generate(page, "COMMUNICATION", "Plan communication")
    _generate(page, "SENSORS", "Place sensors")
    _wait_glyph(page, "ANALYSIS", "NEXT")
    _wait_glyph(page, "EXPORT", "WAITING")
    _click_stage(page, "ANALYSIS")
    page.wait_for_selector('[data-testid="analysis-center"]')
    _wait_glyph(page, "ANALYSIS", "DONE")
    _wait_glyph(page, "EXPORT", "NEXT")
    assert errors == []


def test_cut_fill_demo_opens_read_only_then_analysis_and_export(
    browser: tuple[Any, list[str]], stack: dict[str, Any]
) -> None:
    """Hardening PR-2 H4 — File › Demos › the CUT_AND_FILL demo: read-only
    demo mode, then Analysis (full-window) and the Export download."""
    page, errors = browser
    demos_dir = stack["data_dir"] / "demos"
    before = {
        str(p.relative_to(demos_dir)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(demos_dir.rglob("*"))
        if p.is_file()
    }
    page.click('header button:has-text("File")')
    page.click('[role="menu"] [role="menuitem"]:has-text("Demos")')
    page.wait_for_selector('[data-testid="demo-list"] button:not([disabled])')
    page.click('[data-testid="demo-list"] button:not([disabled])')
    # demo mode: the badge, the demo panel instead of the controls host,
    # exactly ONE primary ("Clone to edit"), no "Reset from here"
    page.wait_for_selector('[data-testid="demo-badge"]')
    page.wait_for_selector('[data-testid="demo-panel"]')
    assert page.locator('[data-testid="controls-host"]').count() == 0
    assert page.locator('[data-testid="reset-from-here"]').count() == 0
    assert _primaries(page) == 1
    # text_content, not inner_text: the button's `plate` style upper-cases its rendering
    primary = page.locator('button[data-variant="primary"]:enabled').text_content() or ""
    assert primary.strip() == "Clone to edit", primary
    assert page.locator('[data-testid="demo-auto-tour"]').is_checked()
    # every baked stage reads DONE in the stepper (the demo's artifacts)
    for stage in ("SCENARIO", "LAYOUT", "LEVELS", "NETWORK", "PRODUCTION", "SCHEDULE"):
        _wait_glyph(page, stage, "DONE")
    # 4D: Loop is on for a demo; the results card reads the backend series
    page.click('[data-testid="view-switcher"] button:has-text("4D")')
    page.wait_for_selector('[data-testid="timeline-loop"]')
    # Loop is a toggle BUTTON (aria-pressed), on for a demo
    assert page.locator('[data-testid="timeline-loop"]').get_attribute("aria-pressed") == "true"
    page.wait_for_selector('[data-testid="fourd-results"]')
    # Analysis: full-window, KPI tiles, the Sensitivity tab's what-if label
    _click_stage(page, "ANALYSIS")
    page.wait_for_selector('[data-testid="analysis-center"]')
    assert page.locator("canvas").count() == 0
    page.wait_for_selector('[data-testid="analysis-kpis"]')
    page.click('[data-testid="analysis-center"] button:has-text("Sensitivity")')
    page.wait_for_selector('[data-testid="what-if-label"]', timeout=JOB_TIMEOUT_MS)
    assert page.locator('[data-testid="what-if-form"]').count() == 1
    # Export stays available for a demo (its controls host is shown there)
    _click_stage(page, "EXPORT")
    with page.expect_download(timeout=JOB_TIMEOUT_MS) as dl:
        _controls(page, "Export MineExchange").click()
    assert dl.value.suggested_filename.endswith(".zip")
    # nothing in the demo directory moved: byte- and stat-identical
    after = {
        str(p.relative_to(demos_dir)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(demos_dir.rglob("*"))
        if p.is_file()
    }
    assert after == before
    assert errors == []
