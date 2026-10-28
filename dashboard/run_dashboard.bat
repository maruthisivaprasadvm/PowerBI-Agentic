@echo off
REM Launch the Power BI Agentic dashboard on a production WSGI server (waitress).
REM Installs dependencies (Flask + waitress) on first run if missing.
setlocal
echo.
echo Starting Power BI Agentic dashboard...
python -c "import flask, waitress" 1>nul 2>nul
if errorlevel 1 (
  echo Installing dependencies ^(first run^)...
  python -m pip install --quiet -r "%~dp0..\requirements.txt"
)
echo Open http://127.0.0.1:8000 in your browser.
python "%~dp0app.py"
pause
