# Changelog

All notable changes to this project are documented here.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

### Removed
- The local **Flask dashboard** (`dashboard/`) and its Desktop-only helpers
  (`requirements.txt`, `scripts/extract_model_dmv.ps1`, `scripts/launch_and_extract.ps1`) — this is
  now a **pure online (browser-only) repo**.
- The Claude-Code + Power BI **MCP agent path** (`.claude/`, `.mcp.json`, `setup/`, MCP setup docs,
  `.vscode/tasks.json`) — the app runs the Python parsers directly.
- The **Performance Analyzer** tool (`scripts/render_perf_report.py`, `rules/performance/`,
  `templates/perf-report-template.html`, its instructions and sample).

### Added
- **Online app** (repo root): a static, client-side build that runs the agents in the browser via
  Pyodide (Python → WebAssembly). Pick a PBIP folder or `.zip`; nothing is uploaded. **Zero-config**
  GitHub Pages deploy — `main` / `/ (root)`, no build step and no Action. The browser fetches the
  parsers/templates/rules directly at their repo paths (listed in `manifest.json`).
- **Visual Lineage** tab in the Data Lineage report — a 4-column source → table → measure → visual
  flow with Full / Visual / Source / Impact / Column trace modes.
- Collapsible sections (Source Map, Visuals & Fields), collapsed by default.
- GitHub community files: `LICENSE` (MIT), `CONTRIBUTING`, `CODE_OF_CONDUCT`, `SECURITY`, `.gitignore`,
  and a CI workflow.

### Changed
- Typography switched to **iA Writer** (Quattro + Mono), embedded in every report (offline-safe).
- UI and report theming moved to the **Power BI Desktop palette** (gold accent, Fluent neutrals) as
  glassmorphism, with a light/dark toggle.
- Softer, glass-friendly pass/fail chart bars.

### Notes
- The app is **PBIP/TMDL-only** — a browser cannot open a binary `.pbix` (its VertiPaq model needs
  the Power BI engine). In Power BI Desktop use **File → Save as → Power BI Project (.pbip)** to unlock
  a browser-readable project.
