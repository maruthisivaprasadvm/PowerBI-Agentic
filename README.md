# Power BI Agentic — Best Practice Analyzer + Performance Analyzer

Two **reusable, agent-driven** tools for any Power BI developer, each producing a self-contained
HTML dashboard with its own rules and its own timestamped output folder:

| Tool | Agent | Checks | From | Output |
|---|---|---|---|---|
| **BPA** (Best Practice Analyzer) | `@bpa-agent` / dashboard | model design vs [TabularEditor rules](https://github.com/TabularEditor/BestPracticeRules) | **PBIP/TMDL text** (offline), live model (ADOMD/DMV), or a launched `.pbix` | `output/BPA/<model>/…` |
| **Unused Artifacts** | `@unused-artifacts-agent` / dashboard | measures/columns/calc tables/hierarchies/relationships not used | model (PBIP/TMDL · live · launched) + report layer (`.pbix` or PBIP `.Report`) | `output/UnusedArtifacts/<model>/…` |
| **Data Lineage** | `@data-lineage-agent` / dashboard | upstream dependencies + downstream impact (source→measure→visual) | model (PBIP/TMDL · live · launched) + report layer (`.pbix` or PBIP `.Report`) | `output/DataLineage/<model>/…` |

### Two ways to run

- **Local app** (`dashboard/`, Flask + waitress) — full features, including reading a binary `.pbix`
  via Power BI Desktop (live or auto-launch). Start with `python dashboard/app.py` → http://127.0.0.1:8000.
- **Online app** (`web/`, static + [Pyodide](https://pyodide.org)) — open a **browser**, pick a
  **PBIP** folder/zip, run an agent; **nothing is uploaded** (all client-side). Deployable to GitHub
  Pages / any static host. Browser-only means **PBIP/TMDL only** (a binary `.pbix` needs Desktop).
  See **[web/README.md](web/README.md)**. Preview locally with `web\serve_web.bat`.

> **On GitHub:** push this repo and enable **Settings → Pages → Source: GitHub Actions**. The
> [`deploy-web`](.github/workflows/deploy-web.yml) workflow builds `web/` and publishes it — users
> then just open `https://<your-user>.github.io/<repo>/` in a browser. [`ci`](.github/workflows/ci.yml)
> smoke-tests the parsers on every push. Generated reports (`output/`) and uploads are git-ignored
> because they embed a full copy of the model. Licensed MIT.

### Three ways to read the model

A binary **`.pbix`** hides its model in a VertiPaq image that only an Analysis Services engine can
load — it can't be parsed from the file alone. So each agent/dashboard gets the model one of three
ways (auto-detected per run):

1. **PBIP / TMDL — fully offline, no Desktop, no engine.** Point at a `.pbip` project or a
   `*.SemanticModel` folder (or drop a `.zip`); the model is parsed straight from TMDL **text** via
   [`scripts/load_tmdl.py`](scripts/load_tmdl.py). Convert a `.pbix` once with **File → Save as →
   Power BI Project (.pbip)** to unlock this.
2. **Already open** — reads the live model from Power BI Desktop's local engine (ADOMD) via
   [`scripts/extract_model_dmv.ps1`](scripts/extract_model_dmv.ps1).
3. **Launch for me** — a `.pbix` with nothing open: [`scripts/launch_and_extract.ps1`](scripts/launch_and_extract.ps1)
   opens it in Desktop (minimized), extracts, then closes it.

BPA is below; Unused Artifacts is in
**[Unused-Artifacts-Instructions.md](Unused-Artifacts-Instructions.md)**.

> A third tool, **Performance Analyzer** (`@perf-analyzer-agent`), is retained in the codebase
> (`scripts/render_perf_report.py`, `rules/performance/`, `templates/perf-report-template.html`)
> but is **hidden from the dashboard UI**. See [Performance-Analyzer-Instructions.md](Performance-Analyzer-Instructions.md)
> to run it directly.

### 🖥️ Main dashboard (one UI for both)

A local web app ties it together — upload a file, pick which agents to run and in what order, execute,
and browse every report:

```
Launch:  double-click dashboard/run_dashboard.bat   (or: python dashboard/app.py)
         or VS Code → Run Task → "Dashboard: Launch web app"
Open:    http://127.0.0.1:8000
```

- **BPA** and **Unused Artifacts** both run **live** when the model is open in Power BI Desktop —
  the dashboard reads it from the local engine (ADOMD → TMSCHEMA DMVs) via
  [`scripts/extract_model_dmv.ps1`](scripts/extract_model_dmv.ps1), then
  [`scripts/evaluate_bpa.py`](scripts/evaluate_bpa.py) / [`scripts/find_unused_artifacts.py`](scripts/find_unused_artifacts.py)
  produce the reports on Execute. BPA falls back to a Claude-agent command if no model is open.
- Agents run **sequentially in an order you can reorder**; the **Reports** page lists every run.
- Performance Analyzer is **hidden from the UI** (code retained — run it via its instructions).

Theme: light/teal, inspired by [cloudbiexpert.com](https://www.cloudbiexpert.com/) — tune the brand in
the `:root` block of [`dashboard/static/style.css`](dashboard/static/style.css).

---

## What's in the box

| Path | Purpose |
|---|---|
| [`setup/setup.bat`](setup/setup.bat) · [`setup/Install-PowerBIModelingMCP.ps1`](setup/Install-PowerBIModelingMCP.ps1) | **One-click** MCP server install + prereq check. |
| [`MCP-Setup-powerbi-modeling.md`](MCP-Setup-powerbi-modeling.md) | Full MCP install/start/activate instructions. |
| [`docs/workflow.html`](docs/workflow.html) | **Visual workflow** page for any Power BI developer. |
| [`.mcp.json`](.mcp.json) | Project-scoped registration of the Power BI Modeling MCP server. |
| [`.claude/agents/bpa-agent.md`](.claude/agents/bpa-agent.md) | The reusable **BPA agent** — invoke with `@bpa-agent`. |
| [`rules/BPARules-PowerBI.json`](rules/BPARules-PowerBI.json) | 26 Power BI rules (default). |
| [`rules/BPARules-standard.json`](rules/BPARules-standard.json) | 29 "standard" rules. |
| [`rules/BPARules-custom-extended.json`](rules/BPARules-custom-extended.json) | 11 community-sourced extra rules (see [gap analysis](rules/EXTENDED-RULES-gap-analysis.md)). |
| [`rules/BPARules-measurekiller.json`](rules/BPARules-measurekiller.json) | 73 [MeasureKiller BPA](https://measurekiller.com/docs/how-tos/best-practice-analysis) rules (model + report-layer). Sets: `measurekiller`, `PowerBI+measurekiller`, `all`. |
| [`templates/bpa-report-template.html`](templates/bpa-report-template.html) | Self-contained HTML dashboard template. |
| [`scripts/render_report.py`](scripts/render_report.py) | Fills the template → `output/BPA/<model>/<model>_<ruleset>_<timestamp>.html`. |
| [`output/BPA/`](output/BPA/) | BPA reports, one **per-pbix subfolder** with a **timestamped** file per run. |
| [`scripts/extract_model_dmv.ps1`](scripts/extract_model_dmv.ps1) | ADOMD extractor — live (open) model metadata → JSON (shared by all three agents). |
| [`scripts/load_tmdl.py`](scripts/load_tmdl.py) | **PBIP/TMDL text → model JSON** (fully offline; same shape as the live extractor). |
| [`scripts/launch_and_extract.ps1`](scripts/launch_and_extract.ps1) | Opens a `.pbix` in Power BI Desktop (minimized), extracts, then closes it. |
| [`scripts/evaluate_bpa.py`](scripts/evaluate_bpa.py) | Offline BPA rule engine over the live model. |
| [`powerbi/Power BI Agentic Instructions.md`](powerbi/Power%20BI%20Agentic%20Instructions.md) | Full BPA agent playbook & tasks. |
| **Unused Artifacts** ↓ | |
| [`.claude/agents/unused-artifacts-agent.md`](.claude/agents/unused-artifacts-agent.md) | The reusable **unused-artifacts agent** — `@unused-artifacts-agent`. |
| [`scripts/find_unused_artifacts.py`](scripts/find_unused_artifacts.py) | Report-layer parser + usage computation + renderer. |
| [`templates/unused-report-template.html`](templates/unused-report-template.html) | Self-contained unused-artifacts dashboard template. |
| [`Unused-Artifacts-Instructions.md`](Unused-Artifacts-Instructions.md) | Full unused-artifacts agent playbook. |
| **Data Lineage** ↓ | |
| [`.claude/agents/data-lineage-agent.md`](.claude/agents/data-lineage-agent.md) | The reusable **lineage agent** — `@data-lineage-agent`. |
| [`scripts/build_lineage.py`](scripts/build_lineage.py) | Graph builder: model deps + Power Query source + per-visual report parse + source map, calc groups, field params, RLS. |
| [`scripts/mquery.py`](scripts/mquery.py) | **Power Query (M) parser** — source kind/connection, source entity, and column renames → the **Source Map** (model column → physical source column). |
| [`templates/lineage-report-template.html`](templates/lineage-report-template.html) | Interactive report: Tables, **Source Map**, Visuals, Dependency Explorer, **Security (RLS)** + JSON export. |
| **Performance Analyzer (hidden from UI, code retained)** ↓ | |
| [`scripts/render_perf_report.py`](scripts/render_perf_report.py) · [`rules/performance/PerfRules.json`](rules/performance/PerfRules.json) · [`Performance-Analyzer-Instructions.md`](Performance-Analyzer-Instructions.md) | Run directly; not shown in the dashboard. |

---

## One-time setup (≈2 min, automated)

1. **Install prerequisites:** Power BI Desktop, Node.js 22+ (`node --version`), VS Code.
2. **Run the one-click installer** — double-click [`setup/setup.bat`](setup/setup.bat) (or
   `powershell -ExecutionPolicy Bypass -File setup/Install-PowerBIModelingMCP.ps1`). It checks
   prerequisites, installs the `powerbi-modeling` MCP server **only if missing** (VS Code
   extension, else zero-install npx), and writes [`.mcp.json`](.mcp.json) in read-only mode.
3. **Reload the VS Code window** once so the MCP server is picked up.

Full details, flags, and troubleshooting: [`MCP-Setup-powerbi-modeling.md`](MCP-Setup-powerbi-modeling.md).
Visual overview: open [`docs/workflow.html`](docs/workflow.html) in a browser.

---

## Run it

1. **Open your model** in Power BI Desktop (e.g. `AI Summaries.pbix`) and keep it open.
2. In Claude Code (this folder), ask:
   ```
   @bpa-agent run the Best Practice Analyzer on "AI Summaries.pbix" using the PowerBI rule set
   ```
3. The agent connects via MCP, evaluates every rule, writes
   `output/BPA/AI Summaries/AI Summaries_PowerBI_<timestamp>.html`, opens it, and prints a summary.

**Inputs you provide:** the `.pbix` **file name**, and optionally the rule set (`PowerBI` | `standard`).
**Output:** an HTML dashboard — KPI cards, pass/fail by category, failures by severity, and a
filterable table of every rule with its offending objects and fix guidance.

**Multiple models / tracking changes:** each `.pbix` gets its own `output/BPA/<model>/` folder and
every run is written to a new **timestamped** file — nothing is overwritten, so you can add more
models over time and compare runs to see what was fixed or introduced.

---

## Preview the UIs now (no model needed)

Labeled **samples** ship so you can see both dashboards before connecting anything:

```
BPA:   output/BPA/SAMPLE AI Summaries (demo)/SAMPLE AI Summaries (demo)_PowerBI_<timestamp>.html
Perf:  output/PerformanceAnalyzer/perf-export-sample/perf-export-sample_<timestamp>.html
```

Open either in a browser. (The BPA sample uses illustrative pass/fail statuses — not a real
analysis. The perf sample is a *real* analysis of the demo export `samples/perf-export-sample.json`.)

---

## Run the Performance Analyzer

1. In Power BI Desktop: **View → Optimize → Performance Analyzer → Start recording → Refresh
   visuals → Export** (saves a `.json`).
2. Ask: `@perf-analyzer-agent analyze the performance export "myreport.json"`
   — or run `python scripts/render_perf_report.py "samples/perf-export-sample.json"`.
3. Writes `output/PerformanceAnalyzer/<export>/<export>_<timestamp>.html` (ranked slow visuals,
   failed perf rules, per-visual DAX/display/other split). Full details:
   [Performance-Analyzer-Instructions.md](Performance-Analyzer-Instructions.md).

---

## How rule evaluation works (short version)

Each rule has a `Scope` (which object types it applies to) and an `Expression`
(Tabular Editor Dynamic LINQ). The agent reads the live model via MCP, and for every in-scope
object evaluates the expression:

- **A matching object = a violation → the rule FAILS** (the report lists the offending objects).
- No matches → **PASS**. No objects in scope → **Pass (N/A)**. Missing data → **Not Evaluated**.

The agent never reads the binary `.pbix` directly and never fabricates results — if the model
isn't connected it stops and shows the setup steps.
