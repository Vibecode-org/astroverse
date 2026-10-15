"""Shared fixtures for browser smoke tests."""
import os
import pytest
from playwright.sync_api import sync_playwright

URL = "http://localhost:5173"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TIMEOUT_MS = 10_000
LOAD_TIMEOUT_MS = 45_000


@pytest.fixture(scope="session")
def playwright_instance():
    pw = sync_playwright().start()
    yield pw
    pw.stop()


@pytest.fixture(scope="session")
def browser(playwright_instance):
    browser = playwright_instance.chromium.launch(
        executable_path=CHROME,
        headless=os.environ.get("SMOKE_HEADED") != "1",
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