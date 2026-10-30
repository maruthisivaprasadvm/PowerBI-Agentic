# Contributing

Thanks for your interest in improving Power BI Agentic.

## Project shape

- `index.html` — the static online app's entry page (served from the repo root by GitHub Pages).
- `pyagent.py` — the in-browser bridge that runs the parsers inside Pyodide.
- `assets/` — browser assets: `app.js`, `style.css`, `fonts/`, favicons, and the generated
  `py-bundle.js` / `manifest.json`.
- `scripts/` — the pure-Python parsers that run in the browser (standard library only).
- `templates/` — the self-contained HTML report templates.
- `rules/` — Best-Practice rule sets (JSON).
- `samples/` — a small PBIP fixture used for tests and demos.
- `tools/` — `build_web.py` (bundles the Python/templates/rules into `assets/py-bundle.js`) and
  `serve_web.bat`.

The app loads its Python from `assets/py-bundle.js` (all of `scripts/`, `templates/`, `rules/`
inlined as text) — it never fetches `.py` files, so corporate proxies that block `.py` can't break
it. If you **change** any parser/template/rule file, re-run `python tools/build_web.py` to refresh the
bundle (CI verifies it matches the repo).

## Dev setup

```bash
tools\serve_web.bat                        # -> http://127.0.0.1:8777  (regenerates the bundle, then serves)
# or: python tools/build_web.py  &&  python -m http.server 8777   (from the repo root)
```

No Python packages are required to run or deploy the app — the parsers use only the standard
library and run in the browser via Pyodide. (You just need Python installed to run `tools/build_web.py`.)

## Before a PR

- Keep the parsers **standard-library only** — the app depends on them running in Pyodide.
- Match the surrounding code style (comment density, naming, idiom).
- Sanity-check an agent against the bundled fixture:
  `python scripts/build_lineage.py <model.json> <pbip-folder> "<name>"`.
- **Never commit generated reports** (`output/`) — they embed a full copy of the source model.
  `.gitignore` already excludes them.

## Reporting bugs

A bug report that names the **PBIP shape** the tool got wrong (a table/partition/measure pattern) is
the most useful thing you can send. A minimal `.pbip` that reproduces it is gold.
