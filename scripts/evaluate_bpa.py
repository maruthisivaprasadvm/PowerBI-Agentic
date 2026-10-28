#!/usr/bin/env python3
"""Evaluate the Best Practice rules against model metadata extracted from the live
Power BI Desktop engine (TMSCHEMA DMVs via ADOMD — see scripts/extract_model_dmv.ps1).

Usage:
    python scripts/evaluate_bpa.py <tmschema.json> "<model file name>" <rule_set>

Produces the BPA results array and renders the HTML dashboard via render_report.py
(output/BPA/<model>/<model>_<ruleset>_<timestamp>.html).

Evaluated offline from real metadata — no fabrication. Rules that require objects not present
(perspectives, cultures/translations) are reported as Pass (N/A). DAX-text rules use documented
heuristics and are labelled as such in their descriptions.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.render_report import render  # noqa: E402

DATATYPE = {2: "String", 6: "Int64", 8: "Double", 9: "DateTime", 10: "Decimal",
            11: "Boolean", 17: "Binary", 19: "Unknown", 20: "Variant"}
SUMMARIZE = {1: "Default", 2: "None", 3: "Sum", 4: "Min", 5: "Max", 6: "Count",
             7: "Average", 8: "DistinctCount"}
NUMERIC = {"Int64", "Double", "Decimal"}
NUMERIC_OR_DATE = NUMERIC | {"DateTime"}


def _rows(d, key):
    v = d.get(key, [])
    return v if isinstance(v, list) else [v]


def load_model(path):
    d = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    tables = {t["ID"]: t for t in _rows(d, "tables")}
    cols, meas, rels = [], [], []
    for c in _rows(d, "columns"):
        if c.get("Type") == 3:            # RowNumber system column
            continue
        dt = c.get("ExplicitDataType") or c.get("InferredDataType")
        cols.append({
            "id": c["ID"], "tableId": c["TableID"],
            "table": tables.get(c["TableID"], {}).get("Name", "?"),
            "name": c.get("ExplicitName") or c.get("InferredName") or "?",
            "dataType": DATATYPE.get(dt, str(dt)),
            "isHidden": bool(c.get("IsHidden")),
            "type": c.get("Type"),               # 1 data, 2 calculated, 4 calc-table col
            "formatString": c.get("FormatString"),
            "summarizeBy": SUMMARIZE.get(c.get("SummarizeBy"), str(c.get("SummarizeBy"))),
            "dataCategory": c.get("DataCategory"),
            "description": c.get("Description"),
            "displayFolder": c.get("DisplayFolder"),
            "sortById": c.get("SortByColumnID"),
            "expression": c.get("Expression"),
            "sourceColumn": c.get("SourceColumn"),
            "isKey": bool(c.get("IsKey")),
            "isAvailableInMdx": bool(c.get("IsAvailableInMDX")),
        })
    for m in _rows(d, "measures"):
        meas.append({
            "id": m["ID"], "tableId": m["TableID"],
            "table": tables.get(m["TableID"], {}).get("Name", "?"),
            "name": m.get("Name"), "expression": m.get("Expression") or "",
            "formatString": m.get("FormatString"), "isHidden": bool(m.get("IsHidden")),
            "displayFolder": m.get("DisplayFolder"), "description": m.get("Description"),
            "dataType": DATATYPE.get(m.get("DataType"), str(m.get("DataType"))),
        })
    colname = {c["id"]: c["name"] for c in cols}
    coltable = {c["id"]: c["table"] for c in cols}
    for r in _rows(d, "relationships"):
        rels.append({
            "id": r["ID"], "isActive": bool(r.get("IsActive")),
            "crossFilter": r.get("CrossFilteringBehavior"),   # 1 one-way, 2 both
            "fromCard": r.get("FromCardinality"), "toCard": r.get("ToCardinality"),
            "fromTable": tables.get(r.get("FromTableID"), {}).get("Name", "?"),
            "toTable": tables.get(r.get("ToTableID"), {}).get("Name", "?"),
            "fromColId": r.get("FromColumnID"), "toColId": r.get("ToColumnID"),
            "fromCol": colname.get(r.get("FromColumnID"), "?"),
            "toCol": colname.get(r.get("ToColumnID"), "?"),
        })
    hiers = [{"id": h["ID"], "name": h.get("Name"),
              "table": tables.get(h["TableID"], {}).get("Name", "?"),
              "isHidden": bool(h.get("IsHidden"))} for h in _rows(d, "hierarchies")]
    return {"tablesById": tables, "tables": list(tables.values()),
            "columns": cols, "measures": meas, "relationships": rels,
            "hierarchies": hiers, "partitions": _rows(d, "partitions"),
            "dependencies": _rows(d, "dependencies"), "levels": _rows(d, "levels")}


# --------------------------------------------------------------------------- DAX helpers
MEASURE_NAMES = set()
COLUMN_NAMES = set()
_REF = re.compile(r"(?P<qual>'[^']+'|\b[A-Za-z_]\w*)?\s*\[(?P<name>[^\]]+)\]")


def _col_refs_unqualified(expr):
    """Column references used without a table qualifier (heuristic)."""
    out = []
    for m in _REF.finditer(expr or ""):
        name, qual = m.group("name"), m.group("qual")
        if name in COLUMN_NAMES and name not in MEASURE_NAMES and not qual:
            out.append(name)
    return out


def _measure_refs_qualified(expr):
    out = []
    for m in _REF.finditer(expr or ""):
        name, qual = m.group("name"), m.group("qual")
        if name in MEASURE_NAMES and qual:
            out.append(name)
    return out


def _uses_division(expr):
    e = re.sub(r"//.*", "", expr or "")           # strip line comments
    for m in re.finditer(r"/(?!/)\s*([^\s)]+)", e):
        tok = m.group(1)
        if not re.match(r"^-?\d", tok):            # denominator not a literal number
            return True
    return False


CAMEL = re.compile(r"^[a-z]+[A-Z]")

MONTHS = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
          "january", "february", "march", "april", "june", "july", "august", "september",
          "october", "november", "december"}
TI_FUNCS = ("TOTALYTD", "TOTALQTD", "TOTALMTD", "DATESYTD", "DATESQTD", "DATESMTD",
            "SAMEPERIODLASTYEAR", "DATEADD", "DATESINPERIOD", "PARALLELPERIOD",
            "PREVIOUSMONTH", "PREVIOUSQUARTER", "PREVIOUSYEAR", "NEXTMONTH", "NEXTYEAR",
            "STARTOFYEAR", "ENDOFYEAR", "FIRSTDATE", "LASTDATE", "OPENINGBALANCE", "CLOSINGBALANCE")
GEO_RE = re.compile(r"(?i)(country|city|state|province|postal|zip|latitude|longitude|region|continent)")
SPECIAL_RE = re.compile(r"[^0-9A-Za-z %()\-/&.,_]")
INVALID_RE = re.compile(r"[\x00-\x1f\[\]\"]")


def _norm_dax(expr):
    return re.sub(r"\s+", " ", re.sub(r"//.*", "", expr or "")).strip().lower()


def obj(table, name):
    return f"{table}[{name}]" if table else name


# --------------------------------------------------------------------------- evaluation
def evaluate(model, rules):
    global MEASURE_NAMES, COLUMN_NAMES
    cols, meas, rels = model["columns"], model["measures"], model["relationships"]
    MEASURE_NAMES = {m["name"] for m in meas}
    COLUMN_NAMES = {c["name"] for c in cols}
    tables = model["tables"]
    from_col_ids = {r["fromColId"] for r in rels}
    to_col_ids = {r["toColId"] for r in rels}
    sortby_ids = {c["sortById"] for c in cols if c["sortById"]}
    all_expr = " \n ".join([m["expression"] for m in meas] +
                           [c["expression"] or "" for c in cols])
    col_by_id = {c["id"]: c for c in cols}
    tname_by_id = {t["ID"]: t.get("Name", "?") for t in tables}
    # calc-table detection via partitions (Type not Query/M, and not a calculation group)
    cg_table_ids = {t["ID"] for t in tables if t.get("CalculationGroupID")}
    calc_table_ids = {p.get("TableID") for p in model.get("partitions", [])
                      if p.get("Type") not in (1, 4) and p.get("TableID") not in cg_table_ids}
    is_directquery = any(p.get("Mode") == 1 for p in model.get("partitions", []))

    def visible_cols_of(tid):
        return [c for c in cols if c["tableId"] == tid and not c["isHidden"]]

    def auto_datetime_tables():
        return [t for t in tables if re.match(r"(LocalDateTable_|DateTableTemplate_)",
                                              t.get("Name", ""))]

    # id -> result
    R = {}

    def res(rid, status, offenders=()):
        R[rid] = {"status": status, "offenders": list(offenders)}

    for r in rules:
        rid = r["ID"]
        off = []

        if rid == "DAX_TODO":
            for m in meas:
                if "todo" in (m["expression"] or "").lower():
                    off.append(obj(m["table"], m["name"]))
            for c in cols:
                if c["expression"] and "todo" in c["expression"].lower():
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "DAX_DIVISION_COLUMNS":
            for m in meas:
                if _uses_division(m["expression"]):
                    off.append(obj(m["table"], m["name"]))
            for c in cols:
                if c["expression"] and _uses_division(c["expression"]):
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "DAX_COLUMNS_FULLY_QUALIFIED":
            for m in meas:
                if _col_refs_unqualified(m["expression"]):
                    off.append(obj(m["table"], m["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "DAX_MEASURES_UNQUALIFIED":
            for m in meas:
                if _measure_refs_qualified(m["expression"]):
                    off.append(obj(m["table"], m["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "APPLY_FORMAT_STRING_COLUMNS":
            for c in cols:
                if (not c["isHidden"] and not (c["formatString"] or "").strip()
                        and c["dataType"] in NUMERIC_OR_DATE):
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "APPLY_FORMAT_STRING_MEASURES":
            for m in meas:
                if (not m["isHidden"] and not (m["formatString"] or "").strip()
                        and m["dataType"] in NUMERIC):
                    off.append(obj(m["table"], m["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "META_AVOID_FLOAT":
            for c in cols:
                if c["dataType"] == "Double":
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "META_SUMMARIZE_NONE":
            for c in cols:
                if (not c["isHidden"] and c["dataType"] in NUMERIC
                        and c["summarizeBy"] != "None"):
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "LAYOUT_HIDE_FK_COLUMNS":
            for c in cols:
                if not c["isHidden"] and c["id"] in from_col_ids:
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "LAYOUT_COLUMNS_HIERARCHIES_DF":
            for t in tables:
                vc = visible_cols_of(t["ID"])
                if len(vc) > 10 and any(not (c["displayFolder"] or "").strip() for c in vc):
                    off.append(t["Name"])
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "LAYOUT_MEASURES_DF":
            for t in tables:
                vm = [m for m in meas if m["tableId"] == t["ID"] and not m["isHidden"]]
                if len(vm) >= 10 and any(not (m["displayFolder"] or "").strip() for m in vm):
                    off.append(t["Name"])
            res(rid, "Fail" if off else "Pass", off)

        elif rid in ("NO_CAMELCASE_COLUMNS_HIERARCHIES",):
            for c in cols:
                if not c["isHidden"] and CAMEL.match(c["name"] or ""):
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "NO_CAMELCASE_MEASURES_TABLES":
            for m in meas:
                if not m["isHidden"] and CAMEL.match(m["name"] or ""):
                    off.append(obj(m["table"], m["name"]))
            for t in tables:
                if not t.get("IsHidden") and CAMEL.match(t.get("Name") or ""):
                    off.append(t["Name"])
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "UPPERCASE_FIRST_LETTER_COLUMNS_HIERARCHIES":
            for c in cols:
                n = c["name"] or ""
                if not c["isHidden"] and n[:1].islower():
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "UPPERCASE_FIRST_LETTER_MEASURES_TABLES":
            for m in meas:
                n = m["name"] or ""
                if not m["isHidden"] and n[:1].islower():
                    off.append(obj(m["table"], m["name"]))
            for t in tables:
                n = t.get("Name") or ""
                if not t.get("IsHidden") and n[:1].islower():
                    off.append(t["Name"])
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "RELATIONSHIP_COLUMN_NAMES":
            pair_count = {}
            for rel in rels:
                key = (rel["fromTable"], rel["toTable"])
                pair_count[key] = pair_count.get(key, 0) + 1
            for rel in rels:
                key = (rel["fromTable"], rel["toTable"])
                if pair_count[key] == 1 and rel["fromCol"] != rel["toCol"]:
                    off.append(f'{rel["fromTable"]}[{rel["fromCol"]}] -> {rel["toTable"]}[{rel["toCol"]}]')
                elif pair_count[key] > 1 and not rel["fromCol"].endswith(rel["toCol"]):
                    off.append(f'{rel["fromTable"]}[{rel["fromCol"]}] -> {rel["toTable"]}[{rel["toCol"]}]')
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "DIABLE_AUTO_DATE/TIME":
            adt = auto_datetime_tables()
            res(rid, "Fail" if adt else "Pass", [t["Name"] for t in adt])

        elif rid == "AVOID_SINGLE_ATTRIBUTE_DIMENSIONS":
            for t in tables:
                vc = visible_cols_of(t["ID"])
                if len(vc) == 1:
                    off.append(t["Name"])
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "PERF_UNUSED_COLUMNS":
            for c in cols:
                if c["isHidden"] and c["id"] not in from_col_ids \
                        and c["id"] not in {r["toColId"] for r in rels} \
                        and c["id"] not in sortby_ids:
                    nm = c["name"]
                    if nm and (f"[{nm}]" not in all_expr):
                        off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "PERF_UNUSED_MEASURES":
            for m in meas:
                if m["isHidden"] and f'[{m["name"]}]' not in all_expr:
                    off.append(obj(m["table"], m["name"]))
            res(rid, "Fail" if off else "Pass", off)

        # ---------------- extended rule set (BPARules-custom-extended.json) ----------------
        elif rid == "PROVIDE_DESCRIPTION_MEASURES":
            for m in meas:
                if not m["isHidden"] and not (m["description"] or "").strip():
                    off.append(obj(m["table"], m["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "PROVIDE_DESCRIPTION_COLUMNS":
            for c in cols:
                if not c["isHidden"] and not (c["description"] or "").strip():
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "PROVIDE_DESCRIPTION_TABLES":
            for t in tables:
                if not t.get("IsHidden") and not (t.get("Description") or "").strip():
                    off.append(t["Name"])
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "AVOID_CALCULATED_COLUMNS":
            for c in cols:
                if c["type"] == 2:                      # calculated column
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "AVOID_BIDIRECTIONAL_RELATIONSHIPS":
            for rel in rels:
                if rel["crossFilter"] == 2:
                    off.append(f'{rel["fromTable"]} <-> {rel["toTable"]}')
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "AVOID_MANYTOMANY_RELATIONSHIPS":
            for rel in rels:
                if rel["fromCard"] == 2 and rel["toCard"] == 2:
                    off.append(f'{rel["fromTable"]} <-> {rel["toTable"]}')
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "RELATIONSHIP_COLUMNS_INTEGER_KEY":
            dtype_by_id = {c["id"]: c["dataType"] for c in cols}
            for rel in rels:
                if dtype_by_id.get(rel["fromColId"]) in ("String", "DateTime", "Double"):
                    off.append(f'{rel["fromTable"]}[{rel["fromCol"]}] ({dtype_by_id.get(rel["fromColId"])})')
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "MARK_DATE_TABLE":
            for t in tables:
                if (t.get("DataCategory") != "Time"
                        and any(c["tableId"] == t["ID"] and c["dataType"] == "DateTime" for c in cols)
                        and re.search(r"(?i)date|calendar", t.get("Name") or "")):
                    off.append(t["Name"])
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "SET_GEO_DATA_CATEGORY":
            geo = re.compile(r"(?i)(country|city|state|province|postal|zip|latitude|longitude|region|continent)")
            for c in cols:
                if (not c["isHidden"] and not (c["dataCategory"] or "").strip()
                        and geo.search(c["name"] or "")):
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "AVOID_DATETIME_COLUMNS":
            tdc = {t["ID"]: t.get("DataCategory") for t in tables}
            for c in cols:
                if c["dataType"] == "DateTime" and tdc.get(c["tableId"]) != "Time":
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)

        elif rid == "SINGULAR_TABLE_NAMES":
            plural = re.compile(r"(?i)[a-rt-z]s$")
            nonplural = re.compile(r"(?i)(ss|us|is|status|analysis|series|species)$")
            for t in tables:
                n = t.get("Name") or ""
                if not t.get("IsHidden") and plural.search(n) and not nonplural.search(n):
                    off.append(n)
            res(rid, "Fail" if off else "Pass", off)

        # ======================= MeasureKiller rule set (MK_*) =======================
        elif rid == "MK_AVOID_FLOAT":
            off = [obj(c["table"], c["name"]) for c in cols if c["dataType"] == "Double"]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_ISAVAILABLEINMDX_FALSE":
            off = [obj(c["table"], c["name"]) for c in cols
                   if c["isHidden"] and c["isAvailableInMdx"]]
            res(rid, "Fail" if off else "Pass", off)
        elif rid in ("MK_BIDI_HIGH_CARDINALITY", "MK_VALIDATE_BIDI_M2M"):
            off = [f'{r["fromTable"]} <-> {r["toTable"]}' for r in rels if r["crossFilter"] == 2]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_CALCCOL_RELATED":
            off = [obj(c["table"], c["name"]) for c in cols
                   if c["type"] == 2 and "RELATED(" in (c["expression"] or "").upper().replace(" ", "")]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_UNPIVOT_MONTHS":
            off = []
            for t in tables:
                mcols = [c for c in cols if c["tableId"] == t["ID"]
                         and (c["name"] or "").strip().lower() in MONTHS]
                if len(mcols) >= 6:
                    off.append(t["Name"])
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_SPLIT_DATE_TIME":
            tdc = {t["ID"]: t.get("DataCategory") for t in tables}
            off = [obj(c["table"], c["name"]) for c in cols
                   if c["dataType"] == "DateTime" and tdc.get(c["tableId"]) != "Time"]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_HAS_DATE_TABLE":
            has = any(t.get("DataCategory") == "Time" for t in tables) or any(
                re.search(r"(?i)date|calendar", t.get("Name") or "")
                and any(c["tableId"] == t["ID"] and c["dataType"] == "DateTime" for c in cols)
                for t in tables)
            res(rid, "Pass" if has else "Fail", [] if has else ["(model has no date table)"])
        elif rid == "MK_MARK_DATE_TABLE":
            off = []
            for t in tables:
                if (t.get("DataCategory") != "Time"
                        and any(c["tableId"] == t["ID"] and c["dataType"] == "DateTime" for c in cols)
                        and re.search(r"(?i)date|calendar", t.get("Name") or "")):
                    off.append(t["Name"])
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_REMOVE_AUTO_DATE":
            adt = auto_datetime_tables()
            res(rid, "Fail" if adt else "Pass", [t["Name"] for t in adt])
        elif rid in ("MK_EXCESSIVE_BIDI_M2M",):
            off = [f'{r["fromTable"]} <-> {r["toTable"]}' for r in rels
                   if r["crossFilter"] == 2 or (r["fromCard"] == 2 and r["toCard"] == 2)]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_M2M_SINGLE_DIRECTION":
            off = [f'{r["fromTable"]} <-> {r["toTable"]}' for r in rels
                   if r["fromCard"] == 2 and r["toCard"] == 2 and r["crossFilter"] == 2]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_MIN_POWER_QUERY":
            off = []
            for p in model.get("partitions", []):
                q = p.get("QueryDefinition") or ""
                if q and q != "None" and q.count("=") > 30:
                    off.append(tname_by_id.get(p.get("TableID"), "?"))
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_REDUCE_CALC_TABLES":
            off = [tname_by_id.get(tid, "?") for tid in calc_table_ids]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_TI_DIRECTQUERY":
            if is_directquery:
                off = [obj(m["table"], m["name"]) for m in meas
                       if any(fn in (m["expression"] or "").upper() for fn in TI_FUNCS)]
                res(rid, "Fail" if off else "Pass", off)
            else:
                res(rid, "Pass (N/A: model is not DirectQuery)")
        elif rid == "MK_DUP_MEASURE_DEF":
            seen = {}
            for m in meas:
                seen.setdefault(_norm_dax(m["expression"]), []).append(obj(m["table"], m["name"]))
            off = [n for k, v in seen.items() if k and len(v) > 1 for n in v]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_DUP_CALCCOL_DEF":
            seen = {}
            for c in cols:
                if c["type"] == 2 and c["expression"]:
                    seen.setdefault(_norm_dax(c["expression"]), []).append(obj(c["table"], c["name"]))
            off = [n for k, v in seen.items() if len(v) > 1 for n in v]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_COLUMNS_FULLY_QUALIFIED":
            off = [obj(m["table"], m["name"]) for m in meas if _col_refs_unqualified(m["expression"])]
            off += [obj(c["table"], c["name"]) for c in cols
                    if c["type"] == 2 and _col_refs_unqualified(c["expression"])]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_TREATAS_OVER_INTERSECT":
            off = [obj(m["table"], m["name"]) for m in meas if "INTERSECT(" in (m["expression"] or "").upper().replace(" ", "")]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_USE_DIVIDE":
            off = [obj(m["table"], m["name"]) for m in meas if _uses_division(m["expression"])]
            off += [obj(c["table"], c["name"]) for c in cols if c["expression"] and _uses_division(c["expression"])]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_AVOID_IFERROR":
            off = [obj(m["table"], m["name"]) for m in meas if "IFERROR(" in (m["expression"] or "").upper().replace(" ", "")]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_NO_WRAPPER_MEASURES":
            off = [obj(m["table"], m["name"]) for m in meas
                   if re.match(r"^\s*('[^']+'|[A-Za-z_]\w*)?\s*\[[^\]]+\]\s*$", m["expression"] or "")]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_INACTIVE_REL_UNUSED":
            up = all_expr.upper()
            off = [f'{r["fromTable"]}[{r["fromCol"]}] -> {r["toTable"]}[{r["toCol"]}]' for r in rels
                   if not r["isActive"] and not ("USERELATIONSHIP" in up and r["fromCol"] in all_expr and r["toCol"] in all_expr)]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_AVOID_1_MINUS_DIV":
            off = [obj(m["table"], m["name"]) for m in meas
                   if re.search(r"1\s*-\s*\([^)]*/", m["expression"] or "")]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_NO_EVALUATEANDLOG":
            off = [obj(m["table"], m["name"]) for m in meas if "EVALUATEANDLOG(" in (m["expression"] or "").upper().replace(" ", "")]
            off += [obj(c["table"], c["name"]) for c in cols if c["expression"] and "EVALUATEANDLOG(" in c["expression"].upper().replace(" ", "")]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_DATA_COL_SOURCE":
            off = [obj(c["table"], c["name"]) for c in cols
                   if c["type"] == 1 and not (c["sourceColumn"] or "").strip()
                   and c["tableId"] not in calc_table_ids and c["tableId"] not in cg_table_ids]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_EXPR_OBJECTS_HAVE_EXPR":
            off = [obj(m["table"], m["name"]) for m in meas if not (m["expression"] or "").strip()]
            off += [obj(c["table"], c["name"]) for c in cols if c["type"] == 2 and not (c["expression"] or "").strip()]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_REL_SAME_DATATYPE":
            off = []
            for r in rels:
                fc, tc = col_by_id.get(r["fromColId"]), col_by_id.get(r["toColId"])
                if fc and tc and fc["dataType"] != tc["dataType"]:
                    off.append(f'{r["fromTable"]}[{r["fromCol"]}]({fc["dataType"]}) <> {r["toTable"]}[{r["toCol"]}]({tc["dataType"]})')
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_INVALID_CHARS_NAMES":
            off = [obj(c["table"], c["name"]) for c in cols if INVALID_RE.search(c["name"] or "")]
            off += [obj(m["table"], m["name"]) for m in meas if INVALID_RE.search(m["name"] or "")]
            off += [t["Name"] for t in tables if INVALID_RE.search(t.get("Name") or "")]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_INVALID_CHARS_DESC":
            off = [obj(c["table"], c["name"]) for c in cols if c["description"] and INVALID_RE.search(c["description"])]
            off += [obj(m["table"], m["name"]) for m in meas if m["description"] and INVALID_RE.search(m["description"])]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_ISAVAILABLEINMDX_TRUE":
            off = [obj(c["table"], c["name"]) for c in cols
                   if c["id"] in sortby_ids and not c["isAvailableInMdx"]]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_REMOVE_UNUSED_COLUMNS":
            off = []
            for c in cols:
                if c["isHidden"] and c["id"] not in from_col_ids and c["id"] not in to_col_ids \
                        and c["id"] not in sortby_ids and c["name"] and f'[{c["name"]}]' not in all_expr:
                    off.append(obj(c["table"], c["name"]))
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_REMOVE_UNUSED_MEASURES":
            off = [obj(m["table"], m["name"]) for m in meas if m["isHidden"] and f'[{m["name"]}]' not in all_expr]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_TABLES_HAVE_RELATIONSHIPS":
            in_rel = {r["fromTable"] for r in rels} | {r["toTable"] for r in rels}
            off = []
            for t in tables:
                nm = t.get("Name", "")
                if nm in in_rel or t["ID"] in cg_table_ids:
                    continue
                if t.get("DataCategory") == "Time" or re.match(r"(LocalDateTable_|DateTableTemplate_)", nm):
                    continue
                off.append(nm)
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_AVOID_ONE_TO_ONE":
            off = [f'{r["fromTable"]} <-> {r["toTable"]}' for r in rels
                   if r["fromCard"] == 1 and r["toCard"] == 1]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_VISIBLE_NO_DESCRIPTION":
            off = [obj(m["table"], m["name"]) for m in meas if not m["isHidden"] and not (m["description"] or "").strip()]
            off += [obj(c["table"], c["name"]) for c in cols if not c["isHidden"] and not (c["description"] or "").strip()]
            off += [t["Name"] for t in tables if not t.get("IsHidden") and not (t.get("Description") or "").strip()]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_NO_SPECIAL_CHARS":
            off = [obj(c["table"], c["name"]) for c in cols if not c["isHidden"] and SPECIAL_RE.search(c["name"] or "")]
            off += [obj(m["table"], m["name"]) for m in meas if not m["isHidden"] and SPECIAL_RE.search(m["name"] or "")]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_TRIM_NAMES":
            off = [obj(c["table"], c["name"]) for c in cols if (c["name"] or "") != (c["name"] or "").strip()]
            off += [obj(m["table"], m["name"]) for m in meas if (m["name"] or "") != (m["name"] or "").strip()]
            off += [t["Name"] for t in tables if (t.get("Name") or "") != (t.get("Name") or "").strip()]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_FIRST_LETTER_CAPITAL":
            off = [obj(c["table"], c["name"]) for c in cols if not c["isHidden"] and (c["name"] or "")[:1].islower()]
            off += [obj(m["table"], m["name"]) for m in meas if not m["isHidden"] and (m["name"] or "")[:1].islower()]
            off += [t["Name"] for t in tables if not t.get("IsHidden") and (t.get("Name") or "")[:1].islower()]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_FORMAT_STRING_MEASURES":
            off = [obj(m["table"], m["name"]) for m in meas
                   if not m["isHidden"] and not (m["formatString"] or "").strip() and m["dataType"] in NUMERIC]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_FORMAT_STRING_DATE_COLUMNS":
            off = [obj(c["table"], c["name"]) for c in cols
                   if c["dataType"] == "DateTime" and not (c["formatString"] or "").strip()]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_DO_NOT_SUMMARIZE":
            off = [obj(c["table"], c["name"]) for c in cols
                   if not c["isHidden"] and c["dataType"] in NUMERIC and c["summarizeBy"] != "None"]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_ADD_DATA_CATEGORY":
            off = [obj(c["table"], c["name"]) for c in cols
                   if not c["isHidden"] and not (c["dataCategory"] or "").strip() and GEO_RE.search(c["name"] or "")]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_PERCENT_FORMAT":
            off = [obj(m["table"], m["name"]) for m in meas
                   if "%" in (m["name"] or "") and "0.0%" not in (m["formatString"] or "")]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_WHOLE_NUMBER_FORMAT":
            off = [obj(m["table"], m["name"]) for m in meas
                   if m["dataType"] == "Int64" and "#,##0" not in (m["formatString"] or "")]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_REL_INTEGER":
            off = []
            for r in rels:
                fc = col_by_id.get(r["fromColId"])
                if fc and fc["dataType"] in ("String", "DateTime", "Double"):
                    off.append(f'{r["fromTable"]}[{r["fromCol"]}] ({fc["dataType"]})')
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_HIDE_FOREIGN_KEYS":
            off = [obj(c["table"], c["name"]) for c in cols if not c["isHidden"] and c["id"] in from_col_ids]
            res(rid, "Fail" if off else "Pass", off)
        elif rid == "MK_MARK_PRIMARY_KEYS":
            off = [obj(c["table"], c["name"]) for c in cols if c["id"] in to_col_ids and not c["isKey"]]
            res(rid, "Fail" if off else "Pass", off)

        # Report-layer MeasureKiller rules — need the .pbix report (not the model engine)
        elif rid.startswith("MK_REPORT_") or rid.startswith("MK_PAGE_") or rid in (
                "MK_HIDE_TOOLTIP_PAGES", "MK_UNUSED_CUSTOM_VISUALS", "MK_VISUAL_OBJECT_COUNT",
                "MK_SHOW_ITEMS_NO_DATA", "MK_THEME_COLORS", "MK_ALT_TEXT", "MK_PIE_DONUT_CAUTION",
                "MK_AVOID_IMPLICIT_MEASURES"):
            res(rid, "Not Evaluated (report-layer rule — analyze the .pbix report)")

        # Rules that need objects this model doesn't have -> Pass (N/A)
        elif rid in ("LAYOUT_ADD_TO_PERSPECTIVES", "LAYOUT_LOCALIZE_DF",
                     "TRANSLATE_DESCRIPTIONS", "TRANSLATE_HIDEABLE_OBJECT_NAMES",
                     "TRANSLATE_HIERARCHY_LEVEL_NAMES", "TRANSLATE_OTHER_NAMES"):
            res(rid, "Pass (N/A: no perspectives/cultures)")

        else:
            res(rid, "Not Evaluated")

    # Build results array in render schema
    results = []
    for r in rules:
        rr = R.get(r["ID"], {"status": "Not Evaluated", "offenders": []})
        results.append({
            "id": r["ID"], "name": r["Name"], "category": r["Category"],
            "severity": r["Severity"], "status": rr["status"],
            "violationCount": len(rr["offenders"]),
            "violations": rr["offenders"],
            "description": (r.get("Description") or "").strip(),
        })
    return results


RULE_FILES = {
    "PowerBI": ["BPARules-PowerBI.json"],
    "standard": ["BPARules-standard.json"],
    "extended": ["BPARules-custom-extended.json"],
    "measurekiller": ["BPARules-measurekiller.json"],
    "PowerBI+extended": ["BPARules-PowerBI.json", "BPARules-custom-extended.json"],
    "standard+extended": ["BPARules-standard.json", "BPARules-custom-extended.json"],
    "PowerBI+measurekiller": ["BPARules-PowerBI.json", "BPARules-measurekiller.json"],
    "all": ["BPARules-PowerBI.json", "BPARules-custom-extended.json", "BPARules-measurekiller.json"],
}


def load_rules(rule_set):
    files = RULE_FILES.get(rule_set, ["BPARules-PowerBI.json"])
    rules = []
    for f in files:
        p = ROOT / "rules" / f
        rules += json.loads(p.read_text(encoding="utf-8-sig"))
    return rules


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    tmschema, model_name = sys.argv[1], sys.argv[2]
    rule_set = sys.argv[3] if len(sys.argv) > 3 else "PowerBI"
    model = load_model(tmschema)
    rules = load_rules(rule_set)
    results = evaluate(model, rules)
    out = render(results, model_name, rule_set)
    npass = sum(1 for r in results if r["status"].startswith("Pass"))
    nfail = sum(1 for r in results if r["status"] == "Fail")
    print(f"Report: {out}")
    print(f"  rules: {len(results)}  passed: {npass}  failed: {nfail}  "
          f"(tables {len(model['tables'])}, columns {len(model['columns'])}, "
          f"measures {len(model['measures'])}, relationships {len(model['relationships'])})")
