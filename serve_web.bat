@echo off
REM Preview the online (browser) app locally. Nothing is uploaded; it all runs in the browser.
setlocal
cd /d "%~dp0"
echo Refreshing vendored parsers/templates/rules...
python build_web.py
echo.
echo Open http://127.0.0.1:8777 in your browser  (Ctrl+C to stop)
python -m http.server 8777 --bind 127.0.0.1
