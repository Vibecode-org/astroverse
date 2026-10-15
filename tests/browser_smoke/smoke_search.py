"""Smoke test: search and filter functionality."""
import pytest


class TestSearch:
    def test_search_filters_list(self, page):
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)

        # Search for Earth
        search = page.locator(".searchBar input")
        search.fill("земля")
        page.wait_for_timeout(500)  # debounce

        rows = page.locator(".objectRow")
        # Should have at least Earth visible
        assert rows.count() >= 1
        names = page.locator(".objectName")
        assert any("Земля" in names.nth(i).text_content() for i in range(names.count()))

        # Clear search
        search.fill("")
        page.wait_for_timeout(500)
        # All objects should be visible again (at least solar system ones)
        assert page.locator(".objectRow").count() > 10

    def test_search_by_latin_name(self, page):
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)

        search = page.locator(".searchBar input")
        search.fill("earth")
        page.wait_for_timeout(500)

        names = page.locator(".objectName")
        assert any("Земля" in names.nth(i).text_content() for i in range(names.count()))

    def test_search_by_description(self, page):
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)

        search = page.locator(".searchBar input")
        search.fill("планета")
        page.wait_for_timeout(500)

        rows = page.locator(".objectRow")
        assert rows.count() > 1  # Multiple planets