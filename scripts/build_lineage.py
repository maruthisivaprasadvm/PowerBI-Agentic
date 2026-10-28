#!/usr/bin/env python3
"""Build a Data Lineage graph for a Power BI model + report (MeasureKiller-style).

Traces, in both directions:
  - upstream  (what an object depends on): source -> table -> column -> measure
  - downstream (what consumes an object / impact): column/measure -> measure -> visual -> page

Model edges come from the live engine via ADOMD (DISCOVER_CALC_DEPENDENCY, partitions,
relationships) — see scripts/extract_model_dmv.ps1. Report usage (which visual on which page uses
which field) is parsed from the .pbix report layer. No MCP.

Usage:
    python scripts/build_lineage.py <tmschema.json> <pbix_path> "<model name>"

Output: output/DataLineage/<model>/<model>_<YYYYMMDD-HHMMSS>.html   (+ embedded JSON export)
"""
import io
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mquery  # noqa: E402  (local module; M-query / source-map parser)
import fonts   # noqa: E402  (local module; embeds the iA Writer webfonts)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "lineage-report-template.html"
DATATYPE = {2: "String", 6: "Int64", 8: "Double", 9: "DateTime", 10: "Decimal",
            11: "Boolean", 17: "Binary", 19: "Unknown", 20: "Variant"}


def _safe(name):
    stem = re.sub(r"\.(pbix|json)$", "", str(name), flags=re.IGNORECASE)
    return re.sub(r'[<>:"/\\|?*]+', "_", stem).strip().strip(".") or "model"


def _rows(d, k):
    v = d.get(k, [])
    return v if isinstance(v, list) else ([v] if v else [])


# --------------------------------------------------------------------- report-layer parser
def _collect_fields(node):
    """Return list of (entity, property, kind) referenced in a visual/config JSON subtree."""
    out = []

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
            for kind in ("Measure", "Column", "HierarchyLevel", "Hierarchy", "Aggregation"):
                ref = o.get(kind)
                if isinstance(ref, dict) and isinstance(ref.get("Property"), str):
                    out.append((entity_of(ref), ref["Property"],
                                "Measure" if kind == "Measure" else
                                "Hierarchy" if kind in ("Hierarchy", "HierarchyLevel") else "Column"))
            qr = o.get("queryRef")
            if isinstance(qr, str) and "." in qr:
                ent, _, prop = qr.partition(".")
                out.append((ent, prop, "Field"))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            s = o.strip()
            if s[:1] in "{[" and len(s) > 2:
                try:
                    walk(json.loads(s))
                except ValueError:
                    pass
    walk(node)
    # de-dup
    seen, res = set(), []
    for e, p, k in out:
        key = ((e or "").lower(), p.lower())
        if key not in seen:
            seen.add(key)
            res.append((e, p, k))
    return res


def _report_entries(path):
    """Yield (archive-style name, bytes) for report files from a .pbix/.zip OR a PBIP folder
    (a project dir containing *.Report, or a *.Report dir, or a definition/ dir). Names are
    normalised to start with 'Report/' so the PBIR/legacy logic is identical either way."""
    p = Path(path)
    if p.is_dir():
        defn = None
        if p.name == "definition" and (p / "pages").exists():
            defn = p
        elif (p / "definition" / "pages").exists():
            defn = p / "definition"
        else:
            for d in p.rglob("definition"):
                if d.is_dir() and (d / "pages").exists():
                    defn = d
                    break
        out = []
        if defn:
            for f in defn.rglob("*"):
                if f.is_file() and (f.suffix == ".json" or f.name == "Layout"):
                    out.append(("Report/definition/" + f.relative_to(defn).as_posix(),
                                f.read_bytes()))
        return out
    try:
        z = zipfile.ZipFile(path)
    except Exception:  # noqa: BLE001
        return []
    return [(n, z.read(n)) for n in z.namelist()
            if n.startswith("Report/") and (n.endswith(".json") or n.endswith("Layout"))]


def parse_report(pbix_path):
    """Return list of visuals: {page, id, type, fields:[(entity,prop,kind)]}.
    Accepts a .pbix zip or a PBIP report folder."""
    visuals = []
    entries = _report_entries(pbix_path)
    if not entries:
        return visuals
    data = {n: b for n, b in entries}
    names = list(data)
    pbir = any("definition/pages/" in n for n in names)
    if pbir:
        pagename = {}
        for n in names:
            if re.search(r"definition/pages/[^/]+/page\.json$", n):
                folder = n.split("definition/pages/")[1].split("/")[0]
                try:
                    pj = json.loads(data[n].decode("utf-8-sig"))
                    pagename[folder] = pj.get("displayName", folder)
                except ValueError:
                    pagename[folder] = folder
        for n in names:
            m = re.search(r"definition/pages/([^/]+)/visuals/([^/]+)/visual\.json$", n)
            if not m:
                continue
            folder, vid = m.group(1), m.group(2)
            try:
                vj = json.loads(data[n].decode("utf-8-sig"))
            except ValueError:
                continue
            vtype = (vj.get("visual") or {}).get("visualType") or "visual"
            visuals.append({"page": pagename.get(folder, folder), "id": vid,
                            "type": vtype, "fields": _collect_fields(vj)})
    else:
        raw = None
        legacy = data.get("Report/Layout")
        for enc in ("utf-16-le", "utf-16", "utf-8-sig"):
            try:
                raw = legacy.decode(enc) if legacy is not None else None
                if raw:
                    break
            except UnicodeError:
                continue
        if raw:
            try:
                lay = json.loads(raw)
                for si, sec in enumerate(lay.get("sections", [])):
                    pname = sec.get("displayName") or sec.get("name") or f"Page {si + 1}"
                    for vi, vc in enumerate(sec.get("visualContainers", [])):
                        fields = _collect_fields(vc)
                        vtype = "visual"
                        cfg = vc.get("config")
                        if isinstance(cfg, str):
                            try:
                                vtype = ((json.loads(cfg).get("singleVisual") or {})
                                         .get("visualType")) or "visual"
                            except ValueError:
                                pass
                        visuals.append({"page": pname, "id": f"v{vi}", "type": vtype, "fields": fields})
            except ValueError:
                pass
    return visuals


# --------------------------------------------------------------------- source (M) parser
def _source_label(qdef):
    """Short data-source label for the Source node (e.g. 'SQL · server / DB')."""
    parsed = mquery.parse(qdef)
    if parsed["kind"] in ("Blank",) and not parsed["label"]:
        return None
    return parsed["label"] or ("Source" if (qdef and qdef != "None") else None)


_DAX_TABLE = re.compile(
    r"\b(DATATABLE|GENERATESERIES|CALENDAR|CALENDARAUTO|UNION|SUMMARIZE|SUMMARIZECOLUMNS|"
    r"ADDCOLUMNS|SELECTCOLUMNS|FILTER|VALUES|DISTINCT|ROW|CROSSJOIN|NATURALINNERJOIN|"
    r"GROUPBY|TOPN|NAMEOF)\s*\(", re.IGNORECASE)


def _looks_like_dax_table(qdef, parsed):
    """True when a partition's source is a DAX table expression (calculated table / field
    parameter) rather than Power Query M — i.e. nothing M-like but a DAX table function."""
    q = (qdef or "").strip()
    if not q or q == "None":
        return False
    if parsed["kind"] not in ("Unknown", "Blank"):
        return False
    if "let" in q.split("\n", 1)[0].lower() or "Source =" in q:
        return False
    return bool(_DAX_TABLE.search(q))


# --------------------------------------------------------------------- graph build
def build(tmschema_path, pbix_path):
    d = json.loads(Path(tmschema_path).read_text(encoding="utf-8-sig"))
    tables = {t["ID"]: t for t in _rows(d, "tables")}
    cols = []
    for c in _rows(d, "columns"):
        if c.get("Type") == 3:
            continue
        dt = c.get("ExplicitDataType") or c.get("InferredDataType")
        cols.append({"id": c["ID"], "table": tables.get(c["TableID"], {}).get("Name", "?"),
                     "name": c.get("ExplicitName") or c.get("InferredName") or "?",
                     "type": c.get("Type"), "hidden": bool(c.get("IsHidden")),
                     "dataType": DATATYPE.get(dt, str(dt))})
    meas = [{"id": m["ID"], "table": tables.get(m["TableID"], {}).get("Name", "?"),
             "name": m.get("Name"), "hidden": bool(m.get("IsHidden")),
             "expr": m.get("Expression") or ""} for m in _rows(d, "measures")]

    # named M expressions (shared queries + parameters). A table whose partition M references a
    # shared query would otherwise resolve to "Unknown"; prepend the referenced query's text so
    # the real data source (and its renames) are seen by the parser.
    expressions = _rows(d, "expressions")
    query_exprs = {e["Name"]: (e.get("Expression") or "")
                   for e in expressions if e.get("Kind") == "query"}

    def resolve_m(qdef):
        q = qdef or ""
        if not q:
            return q
        used = [txt for name, txt in query_exprs.items()
                if txt and (f'#"{name}"' in q
                            or re.search(r"\b" + re.escape(name) + r"\b", q))]
        return ("\n".join(used) + "\n" + q) if used else q

    nodes, edges = {}, []

    def node(nid, ntype, label, **extra):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "type": ntype, "label": label, **extra}
        return nid

    def edge(a, b, kind, **extra):
        edges.append({"from": a, "to": b, "kind": kind, **extra})

    # table / column / measure nodes
    for t in tables.values():
        node(f"T:{t['Name']}", "Table", t["Name"],
             calcGroup=bool(t.get("CalculationGroupID")))
    for c in cols:
        ntype = "Calculated Column" if c["type"] == 2 else "Column"
        node(f"C:{c['table']}|{c['name']}", ntype, f"{c['table']}[{c['name']}]",
             table=c["table"], dataType=c["dataType"], hidden=c["hidden"])
    for m in meas:
        node(f"M:{m['table']}|{m['name']}", "Measure", m["name"],
             table=m["table"], hidden=m["hidden"])

    name_to_measure = {m["name"].lower(): m for m in meas}
    col_lookup = {(c["table"].lower(), c["name"].lower()): c for c in cols}
    col_by_name = {}
    for c in cols:
        col_by_name.setdefault(c["name"].lower(), c)

    # source -> table (from M partitions). Parse each partition's M once; remember the
    # parsed result + whether the table is a DAX (calculated) table, for the source map.
    parsed_by_table = {}          # table name -> mquery.parse(...) result
    calc_tables = set()           # table names produced by DAX, not Power Query
    for p in _rows(d, "partitions"):
        t = tables.get(p.get("TableID"))
        if not t:
            continue
        tname = t["Name"]
        qdef = resolve_m(p.get("QueryDefinition"))
        parsed = mquery.parse(qdef)
        is_calc = p.get("Type") == 7 or _looks_like_dax_table(qdef, parsed)
        if is_calc:
            calc_tables.add(tname)
        # keep the first partition that actually resolved a data source
        if tname not in parsed_by_table or (parsed["label"] and not parsed_by_table[tname]["label"]):
            parsed_by_table[tname] = parsed
        if is_calc:
            continue
        lbl = parsed["label"] or (_source_label(qdef) if qdef else None)
        if lbl:
            sid = node(f"S:{lbl}", "Source", lbl,
                       kind=parsed["kind"], detail=parsed["detail"])
            edge(sid, f"T:{tname}", "source")

    # model dependencies: REFERENCED feeds OBJECT
    def dep_node(otype, table, obj):
        if otype == "MEASURE":
            return f"M:{table}|{obj}"
        if otype in ("COLUMN", "CALC_COLUMN", "CALCULATED_COLUMN"):
            return f"C:{table}|{obj}"
        if otype in ("TABLE", "CALC_TABLE", "CALCULATED_TABLE"):
            return f"T:{table}"
        return None

    node_ids = set(nodes)
    for r in _rows(d, "dependencies"):
        if r.get("OBJECT_TYPE") == "ATTRIBUTE_HIERARCHY":
            continue
        a = dep_node(r.get("REFERENCED_OBJECT_TYPE"), r.get("REFERENCED_TABLE"), r.get("REFERENCED_OBJECT"))
        b = dep_node(r.get("OBJECT_TYPE"), r.get("TABLE"), r.get("OBJECT"))
        if a and b and a != b and a in node_ids and b in node_ids:
            edge(a, b, "dax")

    # relationships: dimension (to/one side) feeds fact (from/many side)
    colname = {c["id"]: c for c in
               [{"id": x["ID"], "table": tables.get(x["TableID"], {}).get("Name", "?"),
                 "name": x.get("ExplicitName") or x.get("InferredName")} for x in _rows(d, "columns")]}
    for r in _rows(d, "relationships"):
        ft = tables.get(r.get("FromTableID"), {}).get("Name")
        tt = tables.get(r.get("ToTableID"), {}).get("Name")
        if ft and tt and f"T:{ft}" in node_ids and f"T:{tt}" in node_ids:
            key = (colname.get(r.get("FromColumnID"), {}).get("name")
                   or colname.get(r.get("ToColumnID"), {}).get("name"))
            edge(f"T:{tt}", f"T:{ft}", "relationship", key=key)

    # calculation groups: an item node per calculationItem; the measures/columns it
    # references feed the item (upstream), and the item belongs to its group table.
    for ci in _rows(d, "calculationItems"):
        cid = node(f"CI:{ci['Table']}|{ci['Name']}", "Calculation Item", ci["Name"],
                   table=ci["Table"], ordinal=ci.get("Ordinal"))
        if f"T:{ci['Table']}" in nodes:
            edge(cid, f"T:{ci['Table']}", "calcgroup")
        for ref in ci.get("refs", []):
            src = dep_node(ref.get("type"), ref.get("table"), ref.get("name"))
            if src and src in nodes and src != cid:
                edge(src, cid, "dax")
        node_ids = set(nodes)

    # field parameters: flag the table, and wire each exposed field -> the parameter table.
    for fp in _rows(d, "fieldParameters"):
        tnode = nodes.get(f"T:{fp['Table']}")
        if tnode:
            tnode["fieldParameter"] = True
            tnode["exposes"] = [f.get("display") for f in fp.get("fields", [])]
        for f in fp.get("fields", []):
            src = dep_node(f.get("refType"), f.get("refTable"), f.get("refName"))
            if src and src in nodes and f"T:{fp['Table']}" in nodes:
                edge(src, f"T:{fp['Table']}", "fieldparam")

    # RLS roles: a Role node per role; the secured table and each column used in its
    # filter feed the role (so impact analysis shows which roles a column/table breaks).
    for role in _rows(d, "roles"):
        rid = node(f"R:{role['name']}", "Role", role["name"],
                   modelPermission=role.get("modelPermission"))
        for tp in role.get("tablePermissions", []):
            if f"T:{tp['table']}" in nodes:
                edge(f"T:{tp['table']}", rid, "rls")
            for c in tp.get("columns", []):
                cn = f"C:{c['table']}|{c['name']}"
                if cn in nodes:
                    edge(cn, rid, "rls")
    node_ids = set(nodes)

    # report: page / visual nodes; field feeds visual
    visuals = parse_report(pbix_path) if pbix_path else []
    pages = {}
    for v in visuals:
        pid = node(f"P:{v['page']}", "Page", v["page"])
        pages.setdefault(v["page"], 0)
        pages[v["page"]] += 1
        vlabel = f"{v['type']} · {v['page']}"
        vid = node(f"V:{v['page']}/{v['id']}", "Visual", vlabel, page=v["page"], visualType=v["type"])
        edge(vid, pid, "page")                 # visual belongs to page (visual feeds page)
        for ent, prop, kind in v["fields"]:
            target = None
            if kind == "Measure" and prop.lower() in name_to_measure:
                mm = name_to_measure[prop.lower()]
                target = f"M:{mm['table']}|{mm['name']}"
            else:
                key = ((ent or "").lower(), prop.lower())
                if key in col_lookup:
                    cc = col_lookup[key]
                    target = f"C:{cc['table']}|{cc['name']}"
                elif prop.lower() in name_to_measure:
                    mm = name_to_measure[prop.lower()]
                    target = f"M:{mm['table']}|{mm['name']}"
                elif prop.lower() in col_by_name:
                    cc = col_by_name[prop.lower()]
                    target = f"C:{cc['table']}|{cc['name']}"
            if target and target in node_ids:
                edge(target, vid, "visual")

    # de-dup edges
    seen, uedges = set(), []
    for e in edges:
        k = (e["from"], e["to"], e["kind"])
        if k not in seen and e["from"] in nodes and e["to"] in nodes:
            seen.add(k)
            uedges.append(e)

    # ---- source map: each model column -> its physical origin (source col / custom / DAX) ----
    sourcemap = []
    for c in cols:
        tname = c["table"]
        parsed = parsed_by_table.get(tname)
        if c["type"] == 2:                      # calculated column (DAX)
            origin, srccol, kind, slabel, stable = "calculated", None, "DAX", None, None
        elif tname in calc_tables:              # column of a DAX / calculated table
            origin, srccol, kind, slabel, stable = "calculated", None, "DAX", None, None
        elif parsed and parsed["kind"] not in ("Blank", "Unknown"):
            origin, srccol = mquery.column_origin(parsed, c["name"])
            kind, slabel, stable = parsed["kind"], parsed["label"], parsed["sourceTable"]
        else:
            origin, srccol, kind, slabel, stable = "unknown", None, None, None, None
        sourcemap.append({
            "table": tname, "column": c["name"], "dataType": c["dataType"],
            "colType": "Calculated Column" if c["type"] == 2 else "Column",
            "origin": origin, "sourceKind": kind, "sourceLabel": slabel,
            "sourceTable": stable, "sourceColumn": srccol,
        })
    sourcemap.sort(key=lambda r: (r["table"].lower(), r["column"].lower()))

    # stats
    by_type = {}
    for n in nodes.values():
        by_type[n["type"]] = by_type.get(n["type"], 0) + 1
    indeg = {nid: 0 for nid in nodes}
    outdeg = {nid: 0 for nid in nodes}
    for e in uedges:
        outdeg[e["from"]] += 1
        indeg[e["to"]] += 1
    # orphan measures/columns: no downstream consumers and not on a visual
    orphans = [nodes[nid]["label"] for nid in nodes
               if nodes[nid]["type"] in ("Measure", "Column", "Calculated Column")
               and outdeg[nid] == 0]
    traced = sum(1 for r in sourcemap if r["origin"] == "source")
    roles = _rows(d, "roles")
    calc_items = _rows(d, "calculationItems")
    field_params = _rows(d, "fieldParameters")

    # expressions for display: shared queries get a parsed source label; parameters get their value
    expr_display = []
    for e in expressions:
        if e.get("Kind") == "query":
            p = mquery.parse(e.get("Expression"))
            expr_display.append({"name": e["Name"], "kind": "query",
                                 "source": p["label"], "sourceKind": p["kind"]})
        else:
            val = (e.get("Expression") or "").split(" meta ")[0].strip().strip('"')
            expr_display.append({"name": e["Name"], "kind": "parameter", "value": val})
    stats = {"byType": by_type, "nodes": len(nodes), "edges": len(uedges),
             "pages": len(pages), "visuals": sum(1 for n in nodes.values() if n["type"] == "Visual"),
             "orphanCount": len(orphans),
             "sourceMapped": traced, "columnsTotal": len(sourcemap),
             "roles": len(roles),
             "calcGroups": sum(1 for t in tables.values() if t.get("CalculationGroupID")),
             "fieldParams": len(field_params),
             "expressions": len(expr_display)}
    extras = {"roles": roles, "calcItems": calc_items, "fieldParams": field_params,
              "expressions": expr_display}
    return list(nodes.values()), uedges, stats, sourcemap, extras


def render(nodes, edges, stats, sourcemap, extras, model_name, pbix_name, out_path=None):
    html = fonts.apply(TEMPLATE.read_text(encoding="utf-8"))
    ts = datetime.now()
    extras = extras or {}
    for k, v in {
        "{{MODEL_NAME}}": model_name, "{{PBIX_NAME}}": pbix_name or "(not provided)",
        "{{RUN_TIMESTAMP}}": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "{{NODES_JSON}}": json.dumps(nodes, ensure_ascii=False),
        "{{EDGES_JSON}}": json.dumps(edges, ensure_ascii=False),
        "{{STATS_JSON}}": json.dumps(stats, ensure_ascii=False),
        "{{SOURCEMAP_JSON}}": json.dumps(sourcemap, ensure_ascii=False),
        "{{ROLES_JSON}}": json.dumps(extras.get("roles", []), ensure_ascii=False),
        "{{CALCITEMS_JSON}}": json.dumps(extras.get("calcItems", []), ensure_ascii=False),
        "{{FIELDPARAMS_JSON}}": json.dumps(extras.get("fieldParams", []), ensure_ascii=False),
        "{{EXPRESSIONS_JSON}}": json.dumps(extras.get("expressions", []), ensure_ascii=False),
    }.items():
        html = html.replace(k, v)
    if out_path is None:
        stem = _safe(model_name)
        out_dir = ROOT / "output" / "DataLineage" / stem
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{stem}_{ts.strftime('%Y%m%d-%H%M%S')}.html"
    Path(out_path).write_text(html, encoding="utf-8")
    return out_path


def run(tmschema_path, pbix_path, model_name):
    nodes, edges, stats, sourcemap, extras = build(tmschema_path, pbix_path)
    out = render(nodes, edges, stats, sourcemap, extras, model_name,
                 Path(pbix_path).name if pbix_path else None)
    return out, nodes, edges, stats


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    out, nodes, edges, stats = run(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"Report: {out}")
    print(f"  nodes {stats['nodes']} ({stats['byType']}), edges {stats['edges']}, "
          f"pages {stats['pages']}, visuals {stats['visuals']}, orphans {stats['orphanCount']}, "
          f"source-mapped {stats['sourceMapped']}/{stats['columnsTotal']}, "
          f"roles {stats['roles']}, calcGroups {stats['calcGroups']}, fieldParams {stats['fieldParams']}")
