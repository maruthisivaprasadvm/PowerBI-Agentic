#!/usr/bin/env python3
"""Load a Power BI model straight from PBIP / TMDL **text** files — no Power BI Desktop,
no Analysis Services engine. This is the file-only path (same idea as pbi-lineage-lenz):
a binary .pbix hides its model in a VertiPaq image that only an engine can open, but a
`.pbip` project stores the model as TMDL text we can parse directly.

It reads a `*.SemanticModel/definition` folder (tables/*.tmdl, relationships.tmdl, model.tmdl,
roles/*.tmdl, expressions.tmdl) and emits the SAME JSON shape that scripts/extract_model_dmv.ps1
produces from the live engine (TMSCHEMA_* rows + a synthesised DISCOVER_CALC_DEPENDENCY), plus
TMDL-only extras consumed by the lineage report: calculationItems, fieldParameters, roles (RLS)
and expressions (shared M queries + parameters). evaluate_bpa.py, find_unused_artifacts.py and
build_lineage.py all consume it unchanged.

Dependencies (measure->column / measure->measure / calc-column->…) are inferred by parsing the
DAX, since TMDL has no engine-computed dependency graph — this is the one accuracy trade-off
versus a live read, and it is called out in the agents' "caveats".

Usage:
    python scripts/load_tmdl.py <pbip-or-SemanticModel-or-definition folder> <out.json>
"""
import json
import re
import sys
from pathlib import Path

# text enum -> TMSCHEMA integer (so downstream maps back to the same labels)
DT = {"string": 2, "int64": 6, "double": 8, "datetime": 9, "decimal": 10,
      "boolean": 11, "binary": 17, "variant": 20, "automatic": 19, "unknown": 19}
SB = {"default": 1, "none": 2, "sum": 3, "min": 4, "max": 5, "count": 6,
      "average": 7, "distinctcount": 8}
XFILTER = {"onedirection": 1, "bothdirections": 2, "automatic": 1}
CARD = {"one": 1, "many": 2, "none": 1}


def _unquote(name):
    name = (name or "").strip()
    if len(name) >= 2 and name[0] == "'" and name[-1] == "'":
        return name[1:-1].replace("''", "'")
    return name


def _split_ref(dotted):
    """'Table'.'Col' | Table.Col | Table.'Col' -> (table, col). Splits on the dot that is
    outside single quotes."""
    s = (dotted or "").strip()
    depth = 0
    for i, ch in enumerate(s):
        if ch == "'":
            depth ^= 1
        elif ch == "." and depth == 0:
            return _unquote(s[:i]), _unquote(s[i + 1:])
    return _unquote(s), None


def _detect_unit(lines):
    for ln in lines:
        if ln.strip() and ln[:1] in (" ", "\t"):
            ws = ln[:len(ln) - len(ln.lstrip(" \t"))]
            return "\t" if "\t" in ws else ws or "\t"
    return "\t"


# --------------------------------------------------------------------------- TMDL reader
class Reader:
    """Indent-aware line cursor for one TMDL file."""

    def __init__(self, text):
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.unit = _detect_unit(self.lines)
        self.n = len(self.lines)
        self.i = 0

    def level(self, idx):
        ln = self.lines[idx]
        ws = ln[:len(ln) - len(ln.lstrip(" \t"))]
        u = len(self.unit)
        return len(ws) // u if u else 0

    def _blank(self, idx):
        s = self.lines[idx].strip()
        return (not s) or s.startswith("///")

    def capture_value(self, decl_level, rest):
        """Capture a `= …` value starting after the '='. self.i points at the next line.
        Returns the expression text (DAX or M)."""
        rest = rest.strip()
        if rest.startswith("```"):                       # fenced block
            buf = []
            while self.i < self.n and self.lines[self.i].strip() != "```":
                buf.append(self.lines[self.i])
                self.i += 1
            if self.i < self.n:
                self.i += 1                              # consume closing ```
            return _dedent(buf)
        if rest:                                         # inline, single line
            return rest
        # multi-line, no fence: body sits deeper than the object's properties (decl_level+1)
        buf, body_level = [], None
        while self.i < self.n:
            if not self.lines[self.i].strip():
                buf.append(self.lines[self.i]); self.i += 1
                continue
            lv = self.level(self.i)
            if body_level is None:
                if lv <= decl_level:
                    break
                body_level = lv
            if lv < body_level:
                break
            buf.append(self.lines[self.i]); self.i += 1
        return _dedent(buf)

    def skip_children(self, parent_level):
        while self.i < self.n and (self._blank(self.i) or self.level(self.i) > parent_level):
            self.i += 1


def _dedent(buf):
    lines = [b for b in buf]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    indent = min((len(l) - len(l.lstrip(" \t")) for l in lines if l.strip()), default=0)
    return "\n".join(l[indent:] if len(l) >= indent else l for l in lines).strip()


_HEAD = re.compile(r"^(?P<kw>[A-Za-z]+)\s+(?P<name>'(?:[^']|'')*'|[^\s=]+)\s*(?:=(?P<rest>.*))?$")
_PROP = re.compile(r"^(?P<key>[A-Za-z][\w]*)\s*:\s*(?P<val>.*)$")
# a nameless `source =` / `expression =` assignment (e.g. a partition's M/DAX body)
_NAMELESS = re.compile(r"^(?P<kw>source|expression)\s*=(?P<rest>.*)$")


def _parse_object_props(rdr, obj_level):
    """Read scalar properties / boolean flags for an object; skip nested sub-blocks
    (annotation, variation, …). Returns dict of props (bool flags -> True)."""
    props = {}
    while rdr.i < rdr.n:
        if not rdr.lines[rdr.i].strip() or rdr.lines[rdr.i].strip().startswith("///"):
            rdr.i += 1
            continue
        lv = rdr.level(rdr.i)
        if lv <= obj_level:
            break
        if lv > obj_level + 1:          # leftover deeper line (sub-block body) -> skip
            rdr.i += 1
            continue
        raw = rdr.lines[rdr.i].strip()
        hm = _HEAD.match(raw)
        if hm and hm.group("kw") in ("annotation", "variation", "changedProperty",
                                     "extendedProperty", "relationship", "calculationItem",
                                     "level", "column", "measure", "partition", "hierarchy"):
            break                        # another object starts / sub-block -> let caller handle
        pm = _PROP.match(raw)
        if pm:
            props[pm.group("key")] = pm.group("val").strip()
        else:
            props[raw.split()[0]] = True  # boolean flag e.g. isHidden / isKey
        rdr.i += 1
    return props


# --------------------------------------------------------------------------- table file
def parse_table_file(text):
    rdr = Reader(text)
    table = {"name": None, "isHidden": False, "calcGroup": False, "precedence": None,
             "columns": [], "measures": [], "partitions": [], "hierarchies": [],
             "calcItems": []}
    # locate the table header
    while rdr.i < rdr.n:
        raw = rdr.lines[rdr.i].strip()
        m = _HEAD.match(raw)
        if m and m.group("kw") == "table":
            table["name"] = _unquote(m.group("name"))
            rdr.i += 1
            break
        rdr.i += 1
    if table["name"] is None:
        return None
    tlevel = 0

    while rdr.i < rdr.n:
        if not rdr.lines[rdr.i].strip() or rdr.lines[rdr.i].strip().startswith("///"):
            rdr.i += 1
            continue
        lv = rdr.level(rdr.i)
        if lv <= tlevel and rdr.i != 0:
            if lv == tlevel and _HEAD.match(rdr.lines[rdr.i].strip()) \
                    and _HEAD.match(rdr.lines[rdr.i].strip()).group("kw") == "table":
                break
        raw = rdr.lines[rdr.i].strip()
        # `calculationGroup` is a NAMELESS block header, so _HEAD won't match it.
        if raw == "calculationGroup" or raw.startswith("calculationGroup "):
            olevel = lv
            rdr.i += 1
            table["calcGroup"] = True
            prec, items = _read_calc_group(rdr, olevel)
            if prec is not None:
                table["precedence"] = prec
            table["calcItems"] = items
            continue
        m = _HEAD.match(raw)
        if not m:
            rdr.i += 1
            continue
        kw, name = m.group("kw"), _unquote(m.group("name"))
        rest = m.group("rest")
        olevel = lv

        if kw == "column":
            rdr.i += 1
            expr = rdr.capture_value(olevel, rest) if rest is not None else None
            props = _parse_object_props(rdr, olevel)
            table["columns"].append({"name": name, "expr": expr, "props": props})
        elif kw == "measure":
            rdr.i += 1
            expr = rdr.capture_value(olevel, rest if rest is not None else "")
            props = _parse_object_props(rdr, olevel)
            table["measures"].append({"name": name, "expr": expr, "props": props})
        elif kw == "partition":
            rdr.i += 1
            # partition <name> = <mode-kw>  ; the M/DAX is in a child `source =`
            ptype = (rest or "").strip()
            src, mode = None, None
            while rdr.i < rdr.n and (not rdr.lines[rdr.i].strip()
                                     or rdr.level(rdr.i) > olevel):
                if not rdr.lines[rdr.i].strip():
                    rdr.i += 1
                    continue
                craw = rdr.lines[rdr.i].strip()
                nm = _NAMELESS.match(craw)
                if nm and nm.group("kw") == "source":
                    src_level = rdr.level(rdr.i)
                    rdr.i += 1
                    src = rdr.capture_value(src_level, nm.group("rest") or "")
                    continue
                pm = _PROP.match(craw)
                if pm and pm.group("key") == "mode":
                    mode = pm.group("val").strip()
                rdr.i += 1
            table["partitions"].append({"name": name, "ptype": ptype,
                                        "mode": mode, "source": src})
        elif kw == "hierarchy":
            rdr.i += 1
            levels = []
            while rdr.i < rdr.n and (not rdr.lines[rdr.i].strip()
                                     or rdr.level(rdr.i) > olevel):
                craw = rdr.lines[rdr.i].strip()
                lm = _HEAD.match(craw)
                if lm and lm.group("kw") == "level":
                    levels.append(_unquote(lm.group("name")))
                rdr.i += 1
            table["hierarchies"].append({"name": name, "levels": levels})
        else:
            rdr.i += 1
            rdr.skip_children(olevel)
    return table


def _read_calc_group(rdr, parent_level):
    """Read a calculationGroup block's children: `precedence: N` + calculationItem <name> = DAX."""
    prec, items, ordinal = None, [], 0
    while rdr.i < rdr.n and (not rdr.lines[rdr.i].strip()
                             or rdr.level(rdr.i) > parent_level):
        if not rdr.lines[rdr.i].strip():
            rdr.i += 1
            continue
        lv = rdr.level(rdr.i)
        raw = rdr.lines[rdr.i].strip()
        m = _HEAD.match(raw)
        if m and m.group("kw") == "calculationItem":
            iname = _unquote(m.group("name"))
            rdr.i += 1
            expr = rdr.capture_value(lv, m.group("rest") or "")
            props = _parse_object_props(rdr, lv)
            items.append({"name": iname, "expr": expr,
                          "ordinal": props.get("ordinal", ordinal)})
            ordinal += 1
            continue
        pm = _PROP.match(raw)
        if pm and pm.group("key") == "precedence":
            prec = pm.group("val").strip()
        rdr.i += 1
    return prec, items


def parse_roles(text):
    """Parse RLS `role` blocks: modelPermission + tablePermission <Table> = <filter DAX>."""
    rdr = Reader(text)
    roles = []
    while rdr.i < rdr.n:
        raw = rdr.lines[rdr.i].strip()
        m = _HEAD.match(raw)
        if not (m and m.group("kw") == "role"):
            rdr.i += 1
            continue
        rname = _unquote(m.group("name"))
        olevel = rdr.level(rdr.i)
        rdr.i += 1
        perm, tperms = None, []
        while rdr.i < rdr.n and (not rdr.lines[rdr.i].strip()
                                 or rdr.level(rdr.i) > olevel):
            if not rdr.lines[rdr.i].strip():
                rdr.i += 1
                continue
            clv = rdr.level(rdr.i)
            craw = rdr.lines[rdr.i].strip()
            cm = _HEAD.match(craw)
            if cm and cm.group("kw") == "tablePermission":
                tname = _unquote(cm.group("name"))
                rdr.i += 1
                filt = rdr.capture_value(clv, cm.group("rest") or "")
                tperms.append({"table": tname, "filter": filt})
                continue
            pm = _PROP.match(craw)
            if pm and pm.group("key") == "modelPermission":
                perm = pm.group("val").strip()
            rdr.i += 1
        roles.append({"name": rname, "modelPermission": perm, "tablePermissions": tperms})
    return roles


def parse_expressions(text):
    """Parse `definition/expressions.tmdl`: named M queries + M parameters
    (`expression <name> = <M>` ; parameters carry an IsParameterQuery meta tag)."""
    rdr = Reader(text)
    out = []
    while rdr.i < rdr.n:
        raw = rdr.lines[rdr.i].strip()
        m = _HEAD.match(raw)
        if not (m and m.group("kw") == "expression"):
            rdr.i += 1
            continue
        name = _unquote(m.group("name"))
        lv = rdr.level(rdr.i)
        rest = m.group("rest")
        rdr.i += 1
        expr = rdr.capture_value(lv, rest if rest is not None else "")
        _parse_object_props(rdr, lv)        # consume lineageTag/queryGroup/annotation children
        kind = "parameter" if "isparameterquery" in (expr or "").lower() else "query"
        out.append({"name": name, "expr": expr, "kind": kind})
    return out


def parse_relationships(text):
    rdr = Reader(text)
    rels = []
    while rdr.i < rdr.n:
        raw = rdr.lines[rdr.i].strip()
        m = _HEAD.match(raw)
        if m and m.group("kw") == "relationship":
            rid = _unquote(m.group("name"))
            olevel = rdr.level(rdr.i)
            rdr.i += 1
            props = _parse_object_props(rdr, olevel)
            rels.append({"id": rid, **props})
        else:
            rdr.i += 1
    return rels


# --------------------------------------------------------------------------- field parameters
# a field-parameter row: ("Display Name", NAMEOF('Table'[Field]), ordinal)
_FP_ROW = re.compile(
    r'\(\s*"((?:[^"]|"")*)"\s*,\s*NAMEOF\s*\(\s*([^)]*?)\s*\)\s*,\s*(\d+)\s*\)',
    re.IGNORECASE)


def _field_param_rows(source):
    """If a calc-table source is a field parameter (uses NAMEOF), return its rows
    [(display, ref, ordinal)]; else []."""
    if not source or "NAMEOF" not in source.upper():
        return []
    return [(disp, ref.strip(), int(ordn)) for disp, ref, ordn in _FP_ROW.findall(source)]


# --------------------------------------------------------------------------- DAX deps
_REF = re.compile(r"(?P<q>'(?:[^']|'')*')?\s*\[(?P<name>[^\]]+)\]")


def _dax_refs(expr, measure_names, col_index):
    """Yield (ref_type, ref_table, ref_name) for a DAX expression.
    col_index: {(tableLower,colLower): (table,col)} and {colLower:(table,col)} fallback."""
    out = []
    for m in _REF.finditer(expr or ""):
        q = _unquote(m.group("q")) if m.group("q") else None
        name = m.group("name")
        nl = name.lower()
        if q:                                   # qualified: Table[Name]
            if nl in measure_names:
                out.append(("MEASURE", measure_names[nl][0], measure_names[nl][1]))
            else:
                key = (q.lower(), nl)
                if key in col_index:
                    t, c = col_index[key]
                    out.append(("COLUMN", t, c))
        else:                                   # [Name] -> measure first, else column by name
            if nl in measure_names:
                out.append(("MEASURE", measure_names[nl][0], measure_names[nl][1]))
            elif ("", nl) in col_index:
                t, c = col_index[("", nl)]
                out.append(("COLUMN", t, c))
    # de-dup
    seen, res = set(), []
    for r in out:
        if r not in seen:
            seen.add(r)
            res.append(r)
    return res


# --------------------------------------------------------------------------- assemble DMV JSON
def _find_definition(root):
    root = Path(root)
    if (root / "model.tmdl").exists() and (root / "tables").exists():
        return root
    hits = list(root.rglob("model.tmdl"))
    for h in hits:
        if (h.parent / "tables").exists():
            return h.parent
    # fall back: any folder containing tables/*.tmdl
    for t in root.rglob("tables"):
        if t.is_dir() and any(t.glob("*.tmdl")):
            return t.parent
    return None


def load(root):
    defn = _find_definition(root)
    if not defn:
        raise FileNotFoundError(
            "No TMDL definition found (expected a *.SemanticModel/definition folder with "
            "model.tmdl and a tables/ folder). Save the report as a Power BI Project (.pbip).")
    tables_dir = defn / "tables"
    parsed = []
    for f in sorted(tables_dir.glob("*.tmdl")):
        t = parse_table_file(f.read_text(encoding="utf-8-sig"))
        if t:
            parsed.append(t)

    tables_out, columns_out, measures_out, partitions_out, hiers_out, levels_out = \
        [], [], [], [], [], []
    col_index, measure_names = {}, {}

    for t in parsed:
        tname = t["name"]
        tables_out.append({"ID": tname, "Name": tname,
                           "CalculationGroupID": tname if t["calcGroup"] else None})
        for c in t["columns"]:
            cid = f"{tname}C{c['name']}"
            p = c["props"]
            dt = (p.get("dataType") or "").lower()
            calc = c["expr"] is not None
            columns_out.append({
                "ID": cid, "TableID": tname,
                "ExplicitName": c["name"], "InferredName": c["name"],
                "ExplicitDataType": DT.get(dt, 19), "InferredDataType": DT.get(dt, 19),
                "Type": 2 if calc else 1,
                "IsHidden": bool(p.get("isHidden")),
                "FormatString": p.get("formatString"),
                "SummarizeBy": SB.get((p.get("summarizeBy") or "default").lower(), 1),
                "DataCategory": p.get("dataCategory"),
                "Description": None, "DisplayFolder": p.get("displayFolder"),
                "SortByColumnID": None, "Expression": c["expr"],
                "SourceColumn": p.get("sourceColumn"),
                "IsKey": bool(p.get("isKey")),
                "IsAvailableInMDX": not bool(p.get("isHidden")),
            })
            col_index[(tname.lower(), c["name"].lower())] = (tname, c["name"])
            col_index.setdefault(("", c["name"].lower()), (tname, c["name"]))
        for mm in t["measures"]:
            mid = f"{tname}M{mm['name']}"
            p = mm["props"]
            measures_out.append({
                "ID": mid, "TableID": tname, "Name": mm["name"],
                "Expression": mm["expr"] or "",
                "FormatString": p.get("formatString"),
                "IsHidden": bool(p.get("isHidden")),
                "DisplayFolder": p.get("displayFolder"),
                "Description": None, "DataType": None,
            })
            measure_names[mm["name"].lower()] = (tname, mm["name"])
        for pt in t["partitions"]:
            mode = (pt["mode"] or "").lower()
            modeval = 1 if mode in ("directquery",) else (2 if pt["ptype"] == "calculated" else 0)
            partitions_out.append({
                "TableID": tname, "Name": pt["name"],
                "QueryDefinition": pt["source"],
                "Mode": modeval,
                "Type": 7 if pt["ptype"] in ("calculated", "calculationGroup") else 4,
            })
        for h in t["hierarchies"]:
            hid = f"{tname}H{h['name']}"
            hiers_out.append({"ID": hid, "TableID": tname, "Name": h["name"],
                              "IsHidden": False})
            for ordinal, lv in enumerate(h["levels"]):
                levels_out.append({"ID": f"{hid}{ordinal}", "HierarchyID": hid,
                                   "Name": lv, "Ordinal": ordinal})

    # relationships -> TMSCHEMA shape (default many(from)->one(to), one-directional)
    rels_out = []
    rel_src = []
    for rf in sorted(defn.glob("relationships.tmdl")):
        rel_src += parse_relationships(rf.read_text(encoding="utf-8-sig"))
    for r in rel_src:
        ft, fc = _split_ref(r.get("fromColumn", ""))
        tt, tc = _split_ref(r.get("toColumn", ""))
        if not (ft and tt):
            continue
        active = True
        if "isActive" in r:
            active = str(r["isActive"]).strip().lower() not in ("false", "0")
        rels_out.append({
            "ID": r["id"],
            "IsActive": active,
            "CrossFilteringBehavior": XFILTER.get((r.get("crossFilteringBehavior") or "").lower(), 1),
            "FromCardinality": CARD.get((r.get("fromCardinality") or "many").lower(), 2),
            "ToCardinality": CARD.get((r.get("toCardinality") or "one").lower(), 1),
            "FromTableID": ft, "ToTableID": tt,
            "FromColumnID": f"{ft}C{fc}", "ToColumnID": f"{tt}C{tc}",
        })

    # synthesise DISCOVER_CALC_DEPENDENCY from DAX
    deps = []
    for mm in measures_out:
        for rt, rtab, robj in _dax_refs(mm["Expression"], measure_names, col_index):
            deps.append({"OBJECT_TYPE": "MEASURE", "TABLE": mm["TableID"], "OBJECT": mm["Name"],
                         "REFERENCED_OBJECT_TYPE": rt, "REFERENCED_TABLE": rtab,
                         "REFERENCED_OBJECT": robj})
    for c in columns_out:
        if c["Type"] == 2 and c["Expression"]:
            for rt, rtab, robj in _dax_refs(c["Expression"], measure_names, col_index):
                deps.append({"OBJECT_TYPE": "CALC_COLUMN", "TABLE": c["TableID"],
                             "OBJECT": c["ExplicitName"], "REFERENCED_OBJECT_TYPE": rt,
                             "REFERENCED_TABLE": rtab, "REFERENCED_OBJECT": robj})

    def _refs(expr):
        return [{"type": rt, "table": rtab, "name": robj}
                for rt, rtab, robj in _dax_refs(expr, measure_names, col_index)]

    def _resolve(ref):
        m = _REF.search(ref or "")
        if not m:
            return None
        q = _unquote(m.group("q")) if m.group("q") else None
        nl = m.group("name").lower()
        if q is not None and (q.lower(), nl) in col_index:
            return {"type": "COLUMN", "table": col_index[(q.lower(), nl)][0],
                    "name": col_index[(q.lower(), nl)][1]}
        if nl in measure_names:
            return {"type": "MEASURE", "table": measure_names[nl][0], "name": measure_names[nl][1]}
        if ("", nl) in col_index:
            return {"type": "COLUMN", "table": col_index[("", nl)][0],
                    "name": col_index[("", nl)][1]}
        return None

    # calculation groups -> items (with their DAX references)
    calc_items_out = []
    for t in parsed:
        if not t["calcGroup"]:
            continue
        for it in t["calcItems"]:
            calc_items_out.append({
                "Table": t["name"], "Name": it["name"], "Ordinal": it.get("ordinal"),
                "Expression": it["expr"] or "", "refs": _refs(it["expr"])})

    # field parameters (calc tables whose source uses NAMEOF)
    field_params_out = []
    for t in parsed:
        rows = []
        for pt in t["partitions"]:
            rows = _field_param_rows(pt["source"])
            if rows:
                break
        if not rows:
            continue
        fields = []
        for disp, ref, ordn in rows:
            r = _resolve(ref)
            fields.append({"display": disp, "ordinal": ordn,
                           "refType": (r or {}).get("type"), "refTable": (r or {}).get("table"),
                           "refName": (r or {}).get("name"), "ref": ref})
        field_params_out.append({"Table": t["name"], "fields": fields})

    # RLS roles (definition/roles/*.tmdl and any inline role blocks in model.tmdl)
    roles_out = []
    role_files = list((defn / "roles").glob("*.tmdl")) if (defn / "roles").is_dir() else []
    role_texts = [rf.read_text(encoding="utf-8-sig") for rf in sorted(role_files)]
    if (defn / "model.tmdl").exists():
        role_texts.append((defn / "model.tmdl").read_text(encoding="utf-8-sig"))
    seen_roles = set()
    for txt in role_texts:
        for role in parse_roles(txt):
            if role["name"] in seen_roles:
                continue
            seen_roles.add(role["name"])
            tperms = []
            for tp in role["tablePermissions"]:
                cols = [{"table": rr["table"], "name": rr["name"]}
                        for rr in _refs(tp["filter"]) if rr["type"] == "COLUMN"]
                tperms.append({"table": tp["table"], "filter": tp["filter"], "columns": cols})
            roles_out.append({"name": role["name"],
                              "modelPermission": role["modelPermission"],
                              "tablePermissions": tperms})

    # named M expressions (shared queries + parameters) from definition/expressions.tmdl
    expressions_out = []
    expr_file = defn / "expressions.tmdl"
    if expr_file.exists():
        for e in parse_expressions(expr_file.read_text(encoding="utf-8-sig")):
            expressions_out.append({"Name": e["name"], "Kind": e["kind"],
                                    "Expression": e["expr"] or ""})

    return {"tables": tables_out, "columns": columns_out, "measures": measures_out,
            "relationships": rels_out, "partitions": partitions_out,
            "hierarchies": hiers_out, "levels": levels_out, "dependencies": deps,
            "calculationItems": calc_items_out, "fieldParameters": field_params_out,
            "roles": roles_out, "expressions": expressions_out, "model": []}


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    model = load(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(model, ensure_ascii=False, indent=0),
                                 encoding="utf-8")
    print(f"OK tmdl out={sys.argv[2]} tables={len(model['tables'])} "
          f"columns={len(model['columns'])} measures={len(model['measures'])} "
          f"relationships={len(model['relationships'])} deps={len(model['dependencies'])} "
          f"calcItems={len(model['calculationItems'])} "
          f"fieldParams={len(model['fieldParameters'])} roles={len(model['roles'])} "
          f"expressions={len(model['expressions'])}")


if __name__ == "__main__":
    main()
