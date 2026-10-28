# Power BI Unused Artifacts — Agent Instructions

> Finds model artifacts that nothing uses — safe cleanup candidates — and writes a self-contained
> **HTML dashboard**. Same approach as BPA: reads the **live model via ADOMD** (no MCP), and
> additionally parses the **.pbix report layer** to see what's actually on visuals.

## 1. What it flags

Scans **measures, columns, calculated columns, calculated tables, hierarchies, and relationships**.
An artifact is **Unused** only if it is BOTH:
1. **not on any report visual** — parsed from the `.pbix` (PBIR `visual.json` or legacy `Report/Layout`), and
2. **not referenced by any other model object** — measures, calculated columns, relationships,
   sort-by, and hierarchy levels, via the engine's `DISCOVER_CALC_DEPENDENCY` + TMSCHEMA DMVs.

Active relationships count as used; **inactive** relationships are flagged unless a measure activates
them with `USERELATIONSHIP()`.

## 2. Requirements
- Power BI Desktop **open with the model** (for ADOMD/DMV), and
- the **.pbix file** (for report-visual usage — the engine doesn't know visual placement).

## 3. Run it
- Dashboard: open [http://127.0.0.1:8000](http://127.0.0.1:8000), upload the `.pbix`, select **Unused Artifacts**, Execute.
- Agent: `@unused-artifacts-agent analyze "AdventureWorks Sales.pbix"`
- CLI (two steps):
  ```
  powershell -ExecutionPolicy Bypass -File scripts/extract_model_dmv.ps1 -OutFile model.json
  python scripts/find_unused_artifacts.py model.json "AdventureWorks Sales.pbix" "AdventureWorks Sales.pbix"
  ```

Output: `output/UnusedArtifacts/<model>/<model>_<timestamp>.html` (per-model, timestamped history).

## 4. Project files
| Path | Purpose |
|---|---|
| `scripts/extract_model_dmv.ps1` | ADOMD extractor (shared with BPA) — now also pulls partitions, hierarchies, levels, dependencies. |
| `scripts/find_unused_artifacts.py` | Report-layer parser + usage computation + renderer. |
| `templates/unused-report-template.html` | Self-contained dashboard template. |
| `.claude/agents/unused-artifacts-agent.md` | The reusable agent. |
| `output/UnusedArtifacts/<model>/…` | Reports. |

## 5. Guardrails & caveats
- Real data only — model from the live engine, usage from the `.pbix`. Never fabricated.
- Visual matching is by field name (table-qualified where possible) and is **conservative**: when
  ambiguous it marks an artifact *used*, to avoid recommending deletion of something in use.
- Artifacts used only by calculation items, field parameters, bookmarks, or external tools may still
  be flagged — **review before deleting**.
- Without the `.pbix`, visual usage can't be checked; results then reflect model-internal usage only.
