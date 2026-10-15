# Browser Smoke Tests

Run with pytest (requires local Chrome):

```bash
cd tests
python -m pytest browser_smoke/ -v
```

Or run specific test modules:

```bash
python -m pytest browser_smoke/smoke_load.py -v
python -m pytest browser_smoke/smoke_views.py -v
python -m pytest browser_smoke/smoke_time.py -v
python -m pytest browser_smoke/smoke_picking.py -v
python -m pytest browser_smoke/smoke_search.py -v
```

Environment variables:
- `SMOKE_HEADED=1` — run headed (visible browser)
- Default: headless

Requirements:
- Google Chrome at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` (macOS)
- Or update `CHROME` path in `browser_smoke/conftest.py`
- Frontend must be running at `http://localhost:5173`