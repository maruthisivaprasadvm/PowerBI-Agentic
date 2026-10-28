@echo off
REM One-click launcher for the Power BI Modeling MCP setup.
REM Double-click this file, or run it from a terminal.
setlocal
echo.
echo Running Power BI Modeling MCP automated setup...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-PowerBIModelingMCP.ps1" %*
echo.
echo (Add  -ReadWrite  after the command to enable write mode.)
pause
