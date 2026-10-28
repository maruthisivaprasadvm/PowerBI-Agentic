#!/usr/bin/env python3
"""Identify UNUSED Power BI artifacts (measures, columns, calculated columns, calculated
tables, hierarchies, relationships).

An artifact is 'unused' only if it is BOTH:
  - not placed on any report visual (parsed from the .pbix report layer), AND
  - not referenced by any other model object (measures/calc columns/relationships/sort-by/
    hierarchy levels), using the live engine's DISCOVER_CALC_DEPENDENCY + TMSCHEMA DMVs.

Model metadata comes from scripts/extract_model_dmv.ps1 (ADOMD, no MCP). Report usage comes
from the .pbix report definition (PBIR visual.json or legacy Report/Layout).

Usage:
    python scripts/find_unused_artifacts.py <tmschema.json> <pbix_path> "<model name>"

Output: output/UnusedArtifacts/<model>/<model>_<YYYYMMDD-HHMMSS>.html
"""
import io
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_lineage import _report_entries  # noqa: E402  (shared .pbix/PBIP reader)
from scripts import fonts  # noqa: E402  (embeds the iA Writer webfonts)
TEMPLATE = ROOT / "templates" / "unused-report-template.html"

DATATYPE = {2: "String", 6: "Int64", 8: "Double", 9: "DateTime", 10: "Decimal",
            11: "Boolean", 17: "Binary", 19: "Unknown", 20: "Variant"}


def _safe(name):
    stem = re.sub(r"\.(pbix|json)$", "", str(name), flags=re.IGNORECASE)
    return re.sub(r'[<>:"/\\|?*]+', "_", stem).strip().strip(".") or "model"


def _rows(d, k):
    v = d.get(k, [])
    return v if isinstance(v, list) else ([v] if v else [])


# --------------------------------------------------------------------- report-layer parser
def report_field_refs(pbix_path):
    """Return (pairs, props): set of (entity_lower, field_lower) and set of field_lower,
    harvested from every Report/* JSON (PBIR) and the legacy Report/Layout.
    Accepts a .pbix zip or a PBIP report folder."""
    pairs, props = set(), set()

    def entity_of(d):
        found = []

        def fe(x):
            if isinstance(x, dict):
                sr = x.get("SourceRef")
                if isinstance(sr, dict) and "Entity" in sr:
                    found.append(sr["Entity"])
                for v in x.values():
                    fe(v)
            elif isinstance(x, list):
                for v in x:
                    fe(v)
        fe(d)
        return found[0] if found else None

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("Property"), str):
                prop = o["Property"].lower()
                props.add(prop)
                ent = entity_of(o)
                if ent:
                    pairs.add((ent.lower(), prop))
            for key in ("queryRef", "nativeQueryRef"):
                v = o.get(key)
                if isinstance(v, str) and v:
                    if "." in v:
                        ent, _, prop = v.partition(".")
                        pairs.add((ent.lower(), prop.lower()))
                        props.add(prop.lower())
                    else:
                        props.add(v.lower())
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            s = o.strip()
            if s[:1] in "{[" and len(s) > 2:          # embedded JSON (legacy config strings)
                try:
                    walk(json.loads(s))
                except ValueError:
                    pass

    for n, raw in _report_entries(pbix_path):
        is_json = n.endswith(".json")
        is_layout = n.endswith("/Layout") or n == "Report/Layout"
        if not (is_json or is_layout):
            continue
        txt = None
        if is_layout:
            for enc in ("utf-16-le", "utf-16", "utf-8-sig"):
                try:
                    txt = raw.decode(enc)
                    break
                except UnicodeError:
                    continue
        else:
            txt = raw.decode("utf-8-sig", errors="ignore")
        if not txt:
            continue
        try:
            walk(json.loads(txt))
        except ValueError:
            # last resort: regex-harvest queryRef / Entity+Property tokens
            for ent, prop in re.findall(r'"Entity"\s*:\s*"([^"]+)"[^}]*?"Property"\s*:\s*"([^"]+)"', txt):
                pairs.add((ent.lower(), prop.lower())); props.add(prop.lower())
            for prop in re.findall(r'"Property"\s*:\s*"([^"]+)"', txt):
                props.add(prop.lower())
    return pairs, props


# --------------------------------------------------------------------- model loader
def load(path):
    d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    tables = {t["ID"]: t for t in _rows(d, "tables")}
    cols = []
    for c in _rows(d, "columns"):
        if c.get("Type") == 3:                         # RowNumber system column
            continue
        dt = c.get("ExplicitDataType") or c.get("InferredDataType")
        cols.append({
            "id": c["ID"], "tableId": c["TableID"],
            "table": tables.get(c["TableID"], {}).get("Name", "?"),
            "name": c.get("ExplicitName") or c.get("InferredName") or "?",
            "type": c.get("Type"), "isHidden": bool(c.get("IsHidden")),
            "dataType": DATATYPE.get(dt, str(dt)),
            "sortById": c.get("SortByColumnID"),
        })
    meas = [{
        "id": m["ID"], "tableId": m["TableID"],
        "table": tables.get(m["TableID"], {}).get("Name", "?"),
        "name": m.get("Name"), "isHidden": bool(m.get("IsHidden")),
        "expression": m.get("Expression") or "",
    } for m in _rows(d, "measures")]
    rels, cid = [], {c["id"]: c for c in cols}
    for r in _rows(d, "relationships"):
        rels.append({
            "id": r["ID"], "isActive": bool(r.get("IsActive")),
            "fromColId": r.get("FromColumnID"), "toColId": r.get("ToColumnID"),
            "fromTable": tables.get(r.get("FromTableID"), {}).get("Name", "?"),
            "toTable": tables.get(r.get("ToTableID"), {}).get("Name", "?"),
            "fromCol": cid.get(r.get("FromColumnID"), {}).get("name", "?"),
            "toCol": cid.get(r.get("ToColumnID"), {}).get("name", "?"),
        })
    hiers = [{"id": h["ID"], "name": h.get("Name"),
              "table": tables.get(h["TableID"], {}).get("Name", "?"),
              "isHidden": bool(h.get("IsHidden"))} for h in _rows(d, "hierarchies")]
    parts = _rows(d, "partitions")
    deps = _rows(d, "dependencies")
    levels = _rows(d, "levels")
    return {"tablesById": tables, "columns": cols, "measures": meas, "relationships": rels,
            "hierarchies": hiers, "partitions": parts, "dependencies": deps, "levels": levels}


# --------------------------------------------------------------------- usage computation
def compute(model, pbix_path):
    cols, meas, rels = model["columns"], model["measures"], model["relationships"]
    tables = model["tablesById"]
    vis_pairs, vis_props = report_field_refs(pbix_path) if pbix_path else (set(), set())

    # model-internal references from DISCOVER_CALC_DEPENDENCY
    ref_measures, ref_cols = set(), set()
    for r in model["dependencies"]:
        ot = r.get("OBJECT_TYPE")
        if ot == "ATTRIBUTE_HIERARCHY":                # auto per-column, not meaningful usage
            continue
        rot, rtab, robj = r.get("REFERENCED_OBJECT_TYPE"), r.get("REFERENCED_TABLE"), r.get("REFERENCED_OBJECT")
        if r.get("TABLE") == rtab and r.get("OBJECT") == robj:
            continue
        if rot == "MEASURE":
            ref_measures.add(robj)
        elif rot == "COLUMN":
            ref_cols.add((rtab, robj))
    # columns used by relationships / sort-by / hierarchy levels
    colname = {c["id"]: (c["table"], c["name"]) for c in cols}
    for rel in rels:
        for k in ("fromColId", "toColId"):
            if rel[k] in colname:
                ref_cols.add(colname[rel[k]])
    for c in cols:
        if c["sortById"] in colname:
            ref_cols.add(colname[c["sortById"]])
    for lv in model["levels"]:
        if lv.get("ColumnID") in colname:
            ref_cols.add(colname[lv["ColumnID"]])
    all_dax = " \n ".join(m["expression"] for m in meas)

    def on_visual(table, name):
        return (table.lower(), name.lower()) in vis_pairs or name.lower() in vis_props

    records = []

    def add(typ, table, name, used_model, used_visual, extra=""):
        unused = not used_model and not used_visual
        if unused:
            reason = "Not on any visual; not referenced by any other model object." + (" " + extra if extra else "")
        else:
            bits = []
            if used_visual:
                bits.append("on a report visual")
            if used_model:
                bits.append("referenced in the model")
            reason = "Used (" + " & ".join(bits) + ")."
        records.append({"type": typ, "table": table, "name": name,
                        "usedModel": used_model, "usedVisual": used_visual,
                        "status": "Unused" if unused else "Used", "reason": reason})

    # measures
    for m in meas:
        add("Measure", m["table"], m["name"],
            used_model=m["name"] in ref_measures,
            used_visual=on_visual(m["table"], m["name"]))

    # calc-table detection via partitions (Type not Query/M and not a calc group)
    cg_tables = {t["ID"] for t in tables.values() if t.get("CalculationGroupID")}
    calc_table_ids = set()
    for p in model["partitions"]:
        if p.get("Type") not in (1, 4) and p.get("TableID") not in cg_tables:
            calc_table_ids.add(p.get("TableID"))

    # columns
    for c in cols:
        typ = "Calculated Column" if c["type"] == 2 else "Column"
        if c["tableId"] in calc_table_ids:
            continue  # handled under its calc table
        add(typ, c["table"], c["name"],
            used_model=(c["table"], c["name"]) in ref_cols,
            used_visual=on_visual(c["table"], c["name"]))

    # calculated tables (whole table)
    for tid in calc_table_ids:
        t = tables.get(tid, {})
        tname = t.get("Name", "?")
        tcols = [c for c in cols if c["tableId"] == tid]
        tmeas = [m for m in meas if m["tableId"] == tid]
        used_visual = any(on_visual(tname, c["name"]) for c in tcols) \
            or any(on_visual(tname, m["name"]) for m in tmeas) \
            or (tname.lower(), None) in {(e, None) for e, _ in vis_pairs}
        used_model = any((tname, c["name"]) in ref_cols for c in tcols) \
            or any(m["name"] in ref_measures for m in tmeas) \
            or any(r["fromTable"] == tname or r["toTable"] == tname for r in rels)
        add("Calculated Table", "", tname, used_model, used_visual,
            extra="Calculated table and its columns/measures appear unused.")

    # hierarchies (used only via visuals)
    for h in model["hierarchies"]:
        add("Hierarchy", h["table"], h["name"],
            used_model=False, used_visual=on_visual(h["table"], h["name"]),
            extra="Hierarchies are only consumed by visuals.")

    # relationships: inactive ones not activated by USERELATIONSHIP are unused
    for rel in rels:
        label = f'{rel["fromTable"]}[{rel["fromCol"]}] -> {rel["toTable"]}[{rel["toCol"]}]'
        if rel["isActive"]:
            add("Relationship", "", label, used_model=True, used_visual=False,
                extra="")
        else:
            activated = ("USERELATIONSHIP" in all_dax.upper()
                         and rel["fromCol"] in all_dax and rel["toCol"] in all_dax)
            add("Relationship", "", label, used_model=activated, used_visual=False,
                extra="Inactive relationship not activated by any USERELATIONSHIP() call.")

    # summary by type
    by_type = {}
    for r in records:
        bt = by_type.setdefault(r["type"], {"total": 0, "unused": 0})
        bt["total"] += 1
        if r["status"] == "Unused":
            bt["unused"] += 1
    summary = {"byType": by_type,
               "totalScanned": len(records),
               "totalUnused": sum(1 for r in records if r["status"] == "Unused")}
    return records, summary


def render(records, summary, model_name, pbix_name, out_path=None):
    html = fonts.apply(TEMPLATE.read_text(encoding="utf-8"))
    ts = datetime.now()
    for k, v in {
        "{{MODEL_NAME}}": model_name, "{{PBIX_NAME}}": pbix_name or "(not provided)",
        "{{RUN_TIMESTAMP}}": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "{{RECORDS_JSON}}": json.dumps(records, ensure_ascii=False),
        "{{SUMMARY_JSON}}": json.dumps(summary, ensure_ascii=False),
    }.items():
        html = html.replace(k, v)
    if out_path is None:
        stem = _safe(model_name)
        out_dir = ROOT / "output" / "UnusedArtifacts" / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{stem}_{ts.strftime('%Y%m%d-%H%M%S')}.html"
    Path(out_path).write_text(html, encoding="utf-8")
    return out_path


def run(tmschema_path, pbix_path, model_name):
    model = load(tmschema_path)
    records, summary = compute(model, pbix_path)
    pbix_name = Path(pbix_path).name if pbix_path else None
    out = render(records, summary, model_name, pbix_name)
    return out, records, summary


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    out, records, summary = run(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"Report: {out}")
    print(f"  scanned {summary['totalScanned']}, unused {summary['totalUnused']}")
    for t, s in summary["byType"].items():
        print(f"    {t}: {s['unused']} unused / {s['total']}")
