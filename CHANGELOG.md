# Changelog

All notable changes to this project are documented here.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com).

## [Unreleased]

### Added
- **Online app** (`web/`): a static, client-side build that runs the agents in the browser via
  Pyodide (Python → WebAssembly). Pick a PBIP folder or `.zip`; nothing is uploaded. Deployable to
  GitHub Pages (`.github/workflows/deploy-web.yml`) or any static host.
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
- Local dashboard served via a production WSGI server (waitress); Reports/history UI removed.

### Notes
- Reading a binary `.pbix` model requires Power BI Desktop and is available only in the local app;
  the online app is PBIP/TMDL-only (a browser cannot open a VertiPaq model).
