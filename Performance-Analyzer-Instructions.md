# Power BI Performance Analyzer — Agent Instructions

> An agent-driven tool that analyzes a **Power BI Desktop Performance Analyzer export** and
> produces a self-contained **HTML dashboard** of the slowest visuals and failed performance
> rules. Built to mirror the BPA tool — separate rules, separate output folder — so a developer
> works the same way for both.
>
> Based on the Microsoft sample:
> <https://github.com/microsoft/powerbi-desktop-samples/tree/main/Performance%20Analyzer>

---

## 1. What it does (functionalities from the Microsoft sample)

The Microsoft sample ships an export JSON schema (`performanceAnalyzerExport.schema.json`) and a
PBIX to visualize it. This agent replicates and extends that workflow:

- **Parse** the exported JSON event tree (`{ version, events:[{id,parentId,name,component,start,end,metrics}] }`).
- **Aggregate** each visual into the three categories Power BI reports: **DAX query**,
  **Visual display**, **Other** — plus **DirectQuery** counts, **row counts**, and the **DAX query text**.
- **Evaluate** performance rules (editable thresholds) and flag the offending visuals.
- **Visualize** as an HTML dashboard (KPI cards, ranked stacked bars, rules table, per-visual table).

---

## 2. Project layout (Performance Analyzer side)

```
Power BI Agentic/
├─ rules/performance/PerfRules.json         # performance threshold rules (editable)
├─ templates/perf-report-template.html      # self-contained dashboard template
├─ scripts/render_perf_report.py            # parser + rule engine + renderer (offline)
├─ samples/perf-export-sample.json          # demo export (to preview the dashboard)
├─ docs/perf-workflow.html                  # visual workflow for developers
├─ .claude/agents/perf-analyzer-agent.md    # the reusable agent (@perf-analyzer-agent)
└─ output/PerformanceAnalyzer/<export>/<export>_<timestamp>.html   # reports (per export, timestamped)
```

This is parallel to the BPA tool, which uses `rules/BPARules-*.json`, `templates/bpa-report-template.html`,
`scripts/render_report.py`, and `output/BPA/<model>/...`.

---

## 3. Produce an export (the input)

1. Power BI Desktop → **View** → **Optimize** ribbon → **Performance Analyzer**.
2. **Start recording** → **Refresh visuals** (or interact with the page you want to measure).
3. **Export** → save the `.json`. Put it in the project (e.g. a `perf-exports/` folder).

No live connection is needed at analysis time — the export is self-contained.

---

## 4. Run it

```
@perf-analyzer-agent analyze the performance export "perf-export-sample.json"
```

or directly:

```
python scripts/render_perf_report.py "samples/perf-export-sample.json"
```

Output: `output/PerformanceAnalyzer/<export>/<export>_<timestamp>.html` (opens in the browser).

---

## 5. The rules (`rules/performance/PerfRules.json`)

Each rule: `id`, `name`, `category`, `severity` (1–5), `scope` (`visual` | `report`), `metric`,
`operator`, `threshold`, `description`, `remediation`. Metrics available:

| Metric | Scope | Meaning |
|---|---|---|
| `totalMs` | visual | DAX + display + other for the visual |
| `daxMs` | visual | DAX query time |
| `renderMs` | visual | visual display / render time |
| `otherMs` | visual | overhead (queue/prepare/blocked) |
| `directQueryCount` | visual | number of DirectQuery calls |
| `daxShareOfSlow` | visual | DAX share of total, for visuals > 1000 ms |
| `visualCount` | report | number of visuals measured |
| `totalDaxMs` | report | sum of DAX time across the capture |

Shipped rules flag: slow / very slow visuals, slow / very slow DAX, slow render, high overhead,
DirectQuery usage, too many visuals, query-heavy capture, and DAX-dominant slow visuals.
**Edit the thresholds** in the file to match your performance budget.

`categoryKeywords` at the top of the file maps event name/component text to the DAX / Display /
DirectQuery categories — adjust if a future export uses different lifecycle labels.

---

## 6. Output contract (the UI page)

`output/PerformanceAnalyzer/<export>/<export>_<timestamp>.html` — one self-contained file per run
(history preserved per export):
- **KPI cards:** visuals measured, slowest visual (ms), total DAX, total display, rules failed.
- **Ranked stacked bars:** top visuals by total time, split into DAX / Display / Other.
- **Rules table:** pass/fail, severity, threshold, offending visuals, remediation.
- **Per-visual table:** sortable DAX/Display/Other/Total/Rows + expandable DAX query text;
  filter by DirectQuery.

---

## 7. Guardrails

- All numbers come from the parsed export — nothing is invented. Missing metrics are reported as such.
- Each export keeps its own timestamped history; runs are never overwritten, so you can track whether
  changes made the report faster or slower.
- Attribute every failed rule to the specific offending visual(s).
