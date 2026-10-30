@echo off
REM Preview the online (browser) app locally. Nothing is uploaded; it all runs in the browser.
REM This script lives in tools/ but serves the site from the repo root.
setlocal
cd /d "%~dp0.."
echo Refreshing the app bundle (assets/py-bundle.js)...
python "%~dp0build_web.py"
echo.
echo Open http://127.0.0.1:8777 in your browser  (Ctrl+C to stop)
python -m http.server 8777 --bind 127.0.0.1
