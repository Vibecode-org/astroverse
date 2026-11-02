"""Shared fixtures for browser smoke tests."""
import os
import pytest
from playwright.sync_api import sync_playwright

from common import DEFAULT_OBJECTS, STRESS_OBJECTS, served_object_count

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TIMEOUT_MS = 10_000
LOAD_TIMEOUT_MS = 45_000


def pytest_collection_modifyitems(config, items):
    """Skip modules that do not match the stack that is actually running.

    Both stacks serve http://localhost:5173, so the catalog size is the only
    reliable signal. Without this a forgotten `docker compose up` switch shows
    up as a wall of unrelated timeouts instead of one clear skip reason.
    """
    served = served_object_count()
    reasons = {
        "stack3471": (DEFAULT_OBJECTS, f"needs the {DEFAULT_OBJECTS}-object stack"),
        "stack100k": (STRESS_OBJECTS, f"needs the {STRESS_OBJECTS}-object stress stack"),
    }
    for item in items:
        for marker, (expected, reason) in reasons.items():
            if marker in item.keywords and served != expected:
                item.add_marker(pytest.mark.skip(
                    reason=f"{reason} (served catalog: {served or 'unreachable'})"
                ))
                break


@pytest.fixture(scope="session")
def playwright_instance():
    pw = sync_playwright().start()
    yield pw
    pw.stop()


@pytest.fixture(scope="session")
def browser(playwright_instance):
    headless = os.environ.get("SMOKE_HEADED") != "1"
    # Headless Chrome без GPU не создаёт WebGL-контекст, если не разрешить
    # программный рендер. На машинах с GPU флаги безвредны.
    args = ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"] if headless else []
    browser = playwright_instance.chromium.launch(
        executable_path=CHROME,
        headless=headless,
        args=args,
    )
    yield browser
    browser.close()


@pytest.fixture
def context(browser):
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000},
        locale="ru-RU",
        timezone_id="UTC",
        device_scale_factor=1,
    )
    yield context
    context.close()


@pytest.fixture
def page(context):
    page = context.new_page()
    page.set_default_timeout(TIMEOUT_MS)
    page.set_default_navigation_timeout(LOAD_TIMEOUT_MS)
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    yield page
    assert page_errors == [], f"Uncaught browser pageerror: {page_errors}"
    page.close()
