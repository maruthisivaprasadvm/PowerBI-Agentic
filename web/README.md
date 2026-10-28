# Power BI Agentic — online (browser) app

A **static, client-side** version of the Power BI Agentic tools. Open it in a browser, pick your
**Power BI Project (PBIP)** folder (or a `.zip` of it), and run an agent — **Data Lineage**,
**Unused Artifacts**, or **Best Practice Analyzer**. The report opens as a self-contained HTML file
you can download and share.

It reuses the exact same Python parsers as the local app, compiled to WebAssembly with
[Pyodide](https://pyodide.org) and run **inside the browser tab**.

## 🔒 Privacy

**Nothing is uploaded.** Your files are read in the page and parsed in WebAssembly in your browser.
There is no server and no network call with your data — close the tab and nothing remains. (The
only network fetch is the Pyodide runtime and the app's own code from the host/CDN.)

## What's supported online

| Input | Model | Report layer (visuals) |
|-------|-------|------------------------|
| **PBIP / TMDL** (folder or `.zip`) | ✅ full | ✅ (from the project's `*.Report`) |
| Binary **`.pbix`** | ❌ not in a browser¹ | — |

¹ A `.pbix` stores its model as a binary VertiPaq image that only the Power BI engine can open, so a
browser cannot read it. In Power BI Desktop use **File → Save as → Power BI Project (.pbip)** once to
unlock a fully offline, browser-readable project. (This is the same constraint as every browser-only
Power BI lineage tool.) For binary `.pbix` + live/launch-Desktop features, use the local
`dashboard/` app instead.

## Browsers

Chrome and Edge give the best **folder picker**. Firefox also reads folders; Safari is more limited —
there you can always zip the PBIP project and choose the `.zip`.

## Run it locally (preview)

```
web\serve_web.bat            # Windows: refreshes vendor/ then serves http://127.0.0.1:8777
```

or manually:

```
python web/build_web.py      # copy the parsers/templates/rules into web/vendor/
cd web && python -m http.server 8777
```

Then open <http://127.0.0.1:8777>. (A static server is required — opening `index.html` as a `file://`
won't work because the browser blocks `fetch()` of the local assets.)

## Deploy (so anyone can just open a URL)

The app is 100% static — host the `web/` folder on any static host.

- **GitHub Pages (automated):** the workflow at `.github/workflows/deploy-web.yml` runs
  `build_web.py` and publishes `web/` on every push to `main`. Enable **Settings → Pages → Build and
  deployment → Source: GitHub Actions** once.
- **Netlify / Vercel / Cloudflare Pages / Azure Static Web Apps / S3:** publish the `web/` directory.
  Run `python web/build_web.py` first (or as the build command) so `web/vendor/` is current.

## How it fits the project

```
dashboard/   local Flask app — full features incl. live / launch Power BI Desktop (.pbix)
web/         this static browser app — PBIP/TMDL only, nothing uploaded, deployable anywhere
scripts/     the shared pure-Python parsers (used by both)
```

`web/build_web.py` vendors `scripts/`, `templates/`, `rules/`, and the embedded fonts into
`web/vendor/` so the browser can load them. Re-run it whenever the parsers change (the GitHub Action
does this automatically on deploy).
