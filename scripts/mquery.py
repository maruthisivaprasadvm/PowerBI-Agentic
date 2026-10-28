#!/usr/bin/env python3
"""Parse a Power Query **M** expression (a table partition's `source = …`) and resolve, for
every model column, where it physically comes from — the data source, the source entity
(schema.table / sheet / query) and the original source column it maps to after renames.

This is the Python counterpart of pbi-lineage-lenz's `mquery.js`: M is a full language, so we
don't build a real interpreter — we read the step list heuristically (source function,
navigation step, RenameColumns / AddColumn / RemoveColumns) which covers the overwhelming
majority of real-world queries. Anything we can't resolve is reported honestly as "unknown".

The M text is available on every model-read path (PBIP/TMDL stores it in the partition `source`;
the live/launch DMV extract carries it as `QueryDefinition`), so the resulting source map works
regardless of how the model was read.

Public API:
    parse(m_text)                      -> dict (see _blank() for the shape)
    column_origin(parsed, column_name) -> (origin, source_column)   origin in
                                          {'source','custom','unknown'}
"""
import re
from pathlib import Path

__all__ = ["parse", "column_origin"]


def _blank(kind="Blank"):
    return {"kind": kind, "label": None, "detail": None, "sourceTable": None,
            "renames": {}, "added": set(), "removed": []}


# --------------------------------------------------------------------- data-source detection
def _host(url):
    m = re.match(r"\s*https?://([^/\"?]+)", url or "", re.IGNORECASE)
    return m.group(1) if m else (url or "").strip()


# ordered: first match wins. Each entry -> (kind, label, detail, sourceTable-or-None)
def _detect_source(m):
    def g(pat):
        return re.search(pat, m, re.IGNORECASE | re.DOTALL)

    mm = g(r'Sql\.Databases?\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"')
    if mm:
        return "Sql", f"SQL · {mm.group(1)} / {mm.group(2)}", \
            f"{mm.group(1)} · {mm.group(2)}", None
    mm = g(r'Sql\.Databases?\s*\(\s*"([^"]+)"')
    if mm:
        return "Sql", f"SQL · {mm.group(1)}", mm.group(1), None
    mm = g(r'Excel\.Workbook\s*\(\s*File\.Contents\s*\(\s*"([^"]+)"')
    if mm:
        return "Excel", "Excel · " + Path(mm.group(1)).name, mm.group(1), None
    if g(r'Excel\.CurrentWorkbook\s*\('):
        return "Excel", "Excel · current workbook", "current workbook", None
    mm = g(r'Csv\.Document\s*\(\s*(?:File\.Contents\s*\(\s*)?"([^"]+)"')
    if mm:
        return "Csv", "CSV · " + Path(mm.group(1)).name, mm.group(1), None
    mm = g(r'Json\.Document\s*\(\s*(?:File\.Contents\s*\(\s*)?"([^"]+)"')
    if mm:
        return "Json", "JSON · " + Path(mm.group(1)).name, mm.group(1), None
    mm = g(r'SharePoint\.\w+\s*\(\s*"([^"]+)"')
    if mm:
        return "SharePoint", "SharePoint · " + _host(mm.group(1)), mm.group(1), None
    mm = g(r'OData\.Feed\s*\(\s*"([^"]+)"')
    if mm:
        return "OData", "OData · " + _host(mm.group(1)), mm.group(1), None
    mm = g(r'Web\.(?:Contents|BrowserContents|Page)\s*\(\s*"([^"]+)"')
    if mm:
        return "Web", "Web · " + _host(mm.group(1)), mm.group(1), None
    mm = g(r'Folder\.(?:Files|Contents)\s*\(\s*"([^"]+)"')
    if mm:
        return "Folder", "Folder · " + mm.group(1), mm.group(1), None
    mm = g(r'Odbc\.(?:DataSource|Query)\s*\(\s*"([^"]+)"')
    if mm:
        return "Odbc", "ODBC · " + mm.group(1)[:40], mm.group(1), None
    mm = g(r'Snowflake\.Databases?\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"')
    if mm:
        return "Snowflake", f"Snowflake · {mm.group(1)} / {mm.group(2)}", \
            f"{mm.group(1)} · {mm.group(2)}", None
    # inline / constructed tables
    if g(r'Table\.FromRows\s*\(') or g(r'#table\s*\(') or g(r'Table\.FromList\s*\('):
        return "Inline", "Inline table", "defined in Power Query", None
    # generic: first Namespace.Function( — report the connector by name
    mm = g(r'=\s*([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s*\(\s*"([^"]+)"')
    if mm:
        return mm.group(1), f"{mm.group(1)} · {mm.group(3)[:40]}", mm.group(3), None
    mm = g(r'=\s*([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\s*\(')
    if mm:
        return mm.group(1), mm.group(1), None, None
    return "Unknown", None, None, None


# --------------------------------------------------------------------- navigation (entity)
def _nav_entity(m):
    """The physical table/sheet/query the query reads from, e.g. 'dbo.FactSales', 'Sheet1'."""
    mm = re.search(r'\{\s*\[[^\]]*Schema\s*=\s*"([^"]+)"[^\]]*Item\s*=\s*"([^"]+)"', m,
                   re.IGNORECASE)
    if mm:
        return f"{mm.group(1)}.{mm.group(2)}"
    mm = re.search(r'\{\s*\[[^\]]*Item\s*=\s*"([^"]+)"', m, re.IGNORECASE)
    if mm:
        return mm.group(1)
    mm = re.search(r'\{\s*\[[^\]]*Name\s*=\s*"([^"]+)"', m, re.IGNORECASE)
    if mm:
        return mm.group(1)
    if re.search(r'Value\.NativeQuery\s*\(', m, re.IGNORECASE) or \
       re.search(r'\[\s*Query\s*=\s*"', m, re.IGNORECASE):
        return "native query"
    return None


# --------------------------------------------------------------------- column transforms
_PAIR = re.compile(r'\{\s*"((?:[^"]|"")*)"\s*,\s*"((?:[^"]|"")*)"\s*\}')
_QUOTED = re.compile(r'"((?:[^"]|"")*)"')
_M_IDENT = re.compile(r'#"(?:[^"]|"")*"')     # an M quoted identifier (#"Step Name")


def _strip_idents(s):
    """Drop #"…" quoted identifiers so string-literal scanning can't latch onto their quotes."""
    return _M_IDENT.sub("#step", s or "")


def _balanced(m, start):
    """Return substring of a (...) call starting at the '(' index `start`."""
    depth, i, n = 0, start, len(m)
    while i < n:
        c = m[i]
        if c == '"':                       # skip string literal
            i += 1
            while i < n and m[i] != '"':
                i += 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return m[start:i + 1]
        i += 1
    return m[start:]


def _iter_calls(m, func):
    """Yield the argument substring of every `func(...)` call, in textual (≈ step) order."""
    for mm in re.finditer(re.escape(func) + r"\s*\(", m):
        yield _balanced(m, mm.end() - 1)


def _apply_transforms(m):
    """Walk the rename / add / remove steps in order and return
    (final-name→source-name map, {custom-added lower}, [removed])."""
    rename = {}        # current column name (lower) -> original source name
    added, removed = set(), []

    # Collect each transform call with its textual position so we can process in order.
    events = []
    for kw, kind in (("Table.RenameColumns", "ren"),
                     ("Table.AddColumn", "add"),
                     ("Table.RemoveColumns", "rem")):
        for mm in re.finditer(re.escape(kw) + r"\s*\(", m):
            events.append((mm.start(), kind, _balanced(m, mm.end() - 1)))
    events.sort(key=lambda e: e[0])

    for _pos, kind, arg in events:
        arg = _strip_idents(arg)
        if kind == "ren":
            for old, new in _PAIR.findall(arg):
                old_l, new_l = old.lower(), new.lower()
                origin = rename.pop(old_l, old)
                rename[new_l] = origin
        elif kind == "add":
            # Table.AddColumn(prevStep, "NewCol", each …): new column = first string literal.
            q = _QUOTED.search(arg)
            if q:
                added.add(q.group(1).lower())
        elif kind == "rem":
            for nm in _QUOTED.findall(arg):
                removed.append(nm)
    return rename, added, removed


# --------------------------------------------------------------------- public
def parse(m_text):
    m = (m_text or "").strip()
    if not m or m.lower() == "none":
        return _blank()
    kind, label, detail, _ = _detect_source(m)
    out = _blank(kind)
    out["label"] = label
    out["detail"] = detail
    out["sourceTable"] = _nav_entity(m)
    out["renames"], out["added"], out["removed"] = _apply_transforms(m)
    return out


def column_origin(parsed, column_name):
    """(origin, source_column) for a model column.
    origin: 'custom' (built in Power Query), 'source' (comes from the data source)."""
    if not parsed:
        return "source", column_name
    cl = (column_name or "").lower()
    if cl in parsed.get("added", ()):
        return "custom", None
    src = parsed.get("renames", {}).get(cl)
    return "source", (src if src is not None else column_name)
