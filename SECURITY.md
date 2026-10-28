# Security Policy

## Privacy model

The **online app** (`web/`) runs entirely in the browser via Pyodide. Your Power BI files are read in
the page and parsed in WebAssembly — **nothing is uploaded, transmitted, or stored on any server**.
The only network request is for the Pyodide runtime and the app's own static assets.

The **local app** (`dashboard/`) runs on `127.0.0.1` and reads files from your machine only. Generated
reports (in `output/`) and uploads (in `dashboard/uploads/`) stay on disk and are git-ignored because
they embed a full copy of the source model — treat them as sensitive and do not commit or share them
without reviewing their contents.

## Reporting a vulnerability

Please open a private security advisory on the repository (GitHub → Security → Report a vulnerability),
or email the maintainer. Do not file a public issue for security problems. We aim to acknowledge within
a few business days.

## Supported

The latest `main` is supported. Fixes are released on `main`.
