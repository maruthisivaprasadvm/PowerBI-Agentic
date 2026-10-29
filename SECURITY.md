# Security Policy

## Privacy model

This is a **browser-only** app: it runs entirely client-side via Pyodide. Your Power BI files are read
in the page and parsed in WebAssembly — **nothing is uploaded, transmitted, or stored on any server**.
The only network request is for the Pyodide runtime and the app's own static assets.

Reports you generate embed a **full copy of the source model** (table/column names, M source servers,
DAX). They are produced in-browser and only saved if you download them — treat downloaded reports as
sensitive and review them before sharing. If you run the parsers locally, the generated `output/` is
git-ignored for the same reason.

## Reporting a vulnerability

Please open a private security advisory on the repository (GitHub → Security → Report a vulnerability),
or email the maintainer. Do not file a public issue for security problems. We aim to acknowledge within
a few business days.

## Supported

The latest `main` is supported. Fixes are released on `main`.
