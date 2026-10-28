# Contributing

Thanks for your interest in improving Power BI Agentic.

## Project shape

- `scripts/` — the pure-Python parsers (shared by both apps; standard library only).
- `dashboard/` — the local Flask app (full features, incl. live / launch Power BI Desktop).
- `web/` — the static browser app (Pyodide; PBIP/TMDL only; nothing uploaded; deployed to Pages).
- `templates/` — the self-contained HTML report templates.
- `rules/` — Best-Practice and Performance rule sets (JSON).
- `samples/` — a small PBIP fixture used for tests and demos.

The online app reuses the Python in `scripts/` unchanged — run `python web/build_web.py` to
re-vendor it into `web/vendor/` after any parser change (CI and `web/serve_web.bat` do this for you).

## Dev setup

```bash
pip install -r requirements.txt           # Flask + waitress (local app)
python dashboard/app.py                    # local app  -> http://127.0.0.1:8000
web\serve_web.bat                          # online app -> http://127.0.0.1:8778
```

## Before a PR

- Keep the parsers **standard-library only** — the online app depends on them running in Pyodide.
- Match the surrounding code style (comment density, naming, idiom).
- Sanity-check an agent against the bundled fixture:
  `python scripts/build_lineage.py <model.json> <pbix-or-pbip> "<name>"`.
- **Never commit generated reports** (`output/`) or uploads (`dashboard/uploads/`) — they embed a full
  copy of the source model. `.gitignore` already excludes them.

## Reporting bugs

A bug report that names the **PBIP shape** the tool got wrong (a table/partition/measure pattern) is
the most useful thing you can send. A minimal `.pbip` that reproduces it is gold.
