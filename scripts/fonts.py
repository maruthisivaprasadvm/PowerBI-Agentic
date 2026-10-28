#!/usr/bin/env python3
"""Shared font injection for the self-contained HTML reports.

The report templates ship with a Google-Fonts `@import` for Inter. Reports are
standalone files that may be opened offline (file://) or shared, so we embed the
iA Writer webfonts as base64 data URIs instead of relying on an external CDN —
this keeps every report fully self-contained and private (no network request).

`apply(html)` swaps the Google-Fonts import for the embedded iA Writer faces and
points the font stacks at iA Writer Quattro (UI) / iA Writer Mono (code).
"""
import re
from pathlib import Path

_CSS = (Path(__file__).resolve().parent / "assets" / "ia-fonts.css").read_text(encoding="utf-8")

# the Inter @import line in every template
_IMPORT = re.compile(
    r"@import url\(['\"]https://fonts\.googleapis\.com/[^)]*\);?", re.IGNORECASE)

_UI = "'iA Writer Quattro'"
_MONO = "'iA Writer Mono'"


def apply(html: str) -> str:
    """Return `html` with iA Writer fonts embedded and wired into the font stacks."""
    # 1) replace the remote @import with the embedded @font-face rules
    if _IMPORT.search(html):
        html = _IMPORT.sub(_CSS.strip(), html, count=1)
    else:  # no import present — prepend faces inside the first <style>
        html = html.replace("<style>", "<style>\n" + _CSS.strip() + "\n", 1)
    # 2) UI font: swap Inter for iA Writer Quattro in the --font stack
    html = html.replace("--font:'Inter',", "--font:%s," % _UI)
    html = html.replace("font-family:'Inter'", "font-family:%s" % _UI)
    # 3) code/monospace: prefer iA Writer Mono
    html = html.replace("Consolas,monospace", "%s,Consolas,monospace" % _MONO)
    return html
