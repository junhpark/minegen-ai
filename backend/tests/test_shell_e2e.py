"""Hardening H1 §4.5 — the guided-workflow shell, end to end in a real browser.

One BASELINE mine is driven through the shell exactly as a user would:
Setup (Create mine → Method) → Layout (Option 1, Activate) → Levels →
Excavation → Network → Capability → Production → Schedule → Communication →
Sensors → Analysis → Export (MineExchange download). Then "Reset from here"
on Levels: the confirm dialog lists the backend reset plan verbatim, the
closure is deleted, and Levels regenerates from that stage. At every stop at
most ONE enabled primary button exists in the DOM.

The stack is real: a uvicorn backend on a temporary data directory and the
Vite dev server pointed at it, both on free ports; the browser is the
Playwright Chromium (``MINEGEN_E2E_CHROMIUM`` or the Playwright default).
The test is skipped — never silently passed — when Playwright, Node or the
browser are unavailable. Marker ``e2e`` + ``slow`` (FULL only).
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


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    if shutil.which("npm") is None or not (FRONTEND / "node_modules").exists():
        pytest.skip("frontend toolchain (npm + node_modules) not available")
    data_dir = tmp_path_factory.mktemp("shell-e2e-data")
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
            pytest.skip(f"Playwright Chromium not available: {str(e)[:120]}")
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


def _wait_glyph(page: Any, stage: str, glyph: str, timeout: int = JOB_TIMEOUT_MS) -> None:
    page.wait_for_selector(
        f'[data-testid="stepper"] [data-stage="{stage}"][data-glyph="{glyph}"]',
        timeout=timeout,
    )


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

    # 3 Network · 4 Mining · 5 Systems
    _generate(page, "NETWORK", "Build network")
    _generate(page, "CAPABILITY", "Build capabilities")
    _generate(page, "PRODUCTION", "Generate Stopes")
    _generate(page, "SCHEDULE", "Schedule development")
    _generate(page, "COMMUNICATION", "Plan communication")
    _generate(page, "SENSORS", "Place sensors")

    # 6 Analysis opens in the centre workspace (no primary action)
    _click_stage(page, "ANALYSIS")
    page.wait_for_selector('[data-testid="analysis-center"]')
    assert _primaries(page) == 0

    # 7 Export: the MineExchange bundle downloads
    _click_stage(page, "EXPORT")
    with page.expect_download(timeout=JOB_TIMEOUT_MS) as dl:
        _controls(page, "Export MineExchange").click()
    assert dl.value.suggested_filename.endswith(".zip")

    # Reset from Levels: the dialog lists the backend plan; the closure is deleted
    derived = scenarios[0] / "derived"
    assert (derived / "levels.json").exists() and (derived / "network.json").exists()
    _click_stage(page, "LEVELS")
    page.click('[data-testid="reset-from-here"]')
    page.wait_for_selector('[data-testid="reset-will-delete"]')
    listed = page.locator('[data-testid="reset-will-delete"] li').all_inner_texts()
    assert "levels.json" in listed and "network.json" in listed and "timeline.json" in listed
    assert "layout_v2_selected.json" not in listed  # upstream is never part of the closure
    page.click('[role="dialog"] button:has-text("Delete")')
    _wait_glyph(page, "LEVELS", "NEXT")
    assert not (derived / "levels.json").exists()
    assert not (derived / "network.json").exists()
    assert (derived / "layout_v2_selected.json").exists()
    _assert_single_primary(page, "after reset")
    # …and the stage regenerates from here
    _controls(page, "Generate level development").click()
    _wait_glyph(page, "LEVELS", "DONE")
    assert (derived / "levels.json").exists()
    assert errors == []
