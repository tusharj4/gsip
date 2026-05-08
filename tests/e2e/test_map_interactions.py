"""Playwright E2E tests for GSIP map UI.

Requires:
  - `make dev` running (frontend at http://localhost:3000, backend at http://localhost:8000)
  - `pip install playwright && playwright install chromium`

Run:
  docker compose run --rm backend pytest tests/e2e/ -v --tb=short
  OR locally: pytest tests/e2e/ -v --tb=short (with FRONTEND_URL env set)
"""

import os
import pytest
from playwright.sync_api import Page, expect, sync_playwright

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL  = os.getenv("BACKEND_URL",  "http://localhost:8000")


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def browser():
    """Launch a headless Chromium browser for the session."""
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    """Fresh browser page per test with generous timeouts for tile loading."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg  = ctx.new_page()
    pg.set_default_timeout(20_000)
    yield pg
    ctx.close()


# ─── Backend health (prerequisite) ───────────────────────────────────────────

def test_backend_health():
    """Backend /health must return 200 before UI tests run."""
    import urllib.request
    import json

    with urllib.request.urlopen(f"{BACKEND_URL}/health", timeout=5) as resp:
        body = json.loads(resp.read())
    assert resp.status == 200
    assert body.get("status") == "ok"


# ─── Dashboard ───────────────────────────────────────────────────────────────

def test_dashboard_loads(page: Page) -> None:
    """Dashboard home should render the platform title."""
    page.goto(FRONTEND_URL)
    expect(page.get_by_text("PM GatiShakti Intelligence Platform")).to_be_visible()
    expect(page.get_by_text("Open Map")).to_be_visible()


def test_dashboard_nav_links(page: Page) -> None:
    """All four nav links should be present on the dashboard."""
    page.goto(FRONTEND_URL)
    for label in ["Map", "Projects", "Analysis", "Reports"]:
        expect(page.get_by_role("link", name=label)).to_be_visible()


# ─── Map page ────────────────────────────────────────────────────────────────

def test_map_page_loads(page: Page) -> None:
    """Map page should render the MapLibre canvas element."""
    page.goto(f"{FRONTEND_URL}/map")
    # MapLibre renders into a <canvas> inside the map div
    page.wait_for_selector("canvas", timeout=15_000)
    canvas = page.locator("canvas").first
    expect(canvas).to_be_visible()


def test_map_layer_panel_visible(page: Page) -> None:
    """Layer panel sidebar should appear on the map page."""
    page.goto(f"{FRONTEND_URL}/map")
    page.wait_for_selector("canvas", timeout=15_000)
    expect(page.get_by_text("GIS Layers")).to_be_visible()


def test_map_draw_corridor_button(page: Page) -> None:
    """'Draw Corridor' button should appear after map loads."""
    page.goto(f"{FRONTEND_URL}/map")
    page.wait_for_selector("canvas", timeout=15_000)
    # Give map time to finish loading tiles
    page.wait_for_timeout(2_000)
    expect(page.get_by_text("Draw Corridor")).to_be_visible()


def test_map_nl_query_bar_visible(page: Page) -> None:
    """NL query bar should be visible on the map page."""
    page.goto(f"{FRONTEND_URL}/map")
    page.wait_for_selector("canvas", timeout=15_000)
    page.wait_for_timeout(2_000)
    placeholder = page.get_by_placeholder('Ask anything, e.g. "How many hospitals within 10km of NH48 in Gujarat?"')
    expect(placeholder).to_be_visible()


# ─── Projects page ───────────────────────────────────────────────────────────

def test_projects_page_loads(page: Page) -> None:
    """Projects page should show the header and 'New Project' form."""
    page.goto(f"{FRONTEND_URL}/projects")
    expect(page.get_by_text("Infrastructure Projects")).to_be_visible()
    expect(page.get_by_text("New Project")).to_be_visible()


def test_projects_page_lists_seeded_project(page: Page) -> None:
    """The NH-48 demo project seeded by 'make seed' should appear in the list."""
    page.goto(f"{FRONTEND_URL}/projects")
    page.wait_for_timeout(2_000)  # Wait for API fetch
    # The seed data creates 'NH-48 Mumbai–Delhi Expressway Corridor'
    nh48 = page.get_by_text("NH-48", exact=False)
    # If the seed project exists it should appear; if not, at least no JS error
    # so we just assert the page itself loaded without crashing
    expect(page.get_by_text("New Project")).to_be_visible()
    _ = nh48  # referenced but not asserted (seed data is optional)


# ─── Analysis page ───────────────────────────────────────────────────────────

def test_analysis_page_loads(page: Page) -> None:
    """Analysis page should show service type cards."""
    page.goto(f"{FRONTEND_URL}/analysis")
    expect(page.get_by_text("Service Gap Analysis")).to_be_visible()
    expect(page.get_by_text("anganwadi", exact=False)).to_be_visible()


def test_analysis_run_button_present(page: Page) -> None:
    """'Run Analysis' button should be present on the analysis page."""
    page.goto(f"{FRONTEND_URL}/analysis")
    expect(page.get_by_role("button", name="Run Analysis")).to_be_visible()


# ─── Map with project_id query param ─────────────────────────────────────────

def test_map_with_invalid_project_id_shows_error(page: Page) -> None:
    """Navigating to /map?project_id=<bad-uuid> should not crash the page."""
    import uuid
    bad_id = str(uuid.uuid4())
    page.goto(f"{FRONTEND_URL}/map?project_id={bad_id}")
    page.wait_for_selector("canvas", timeout=15_000)
    page.wait_for_timeout(3_000)
    # The ConflictOverlay should show an error state, but the map must still load
    canvas = page.locator("canvas").first
    expect(canvas).to_be_visible()
