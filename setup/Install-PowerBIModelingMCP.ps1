<#
.SYNOPSIS
    One-click setup for the Power BI Modeling MCP server in VS Code.

.DESCRIPTION
    - Checks prerequisites (Node.js, VS Code) and reports clearly if any are missing.
    - Auto-detect install: if the VS Code extension 'analysis-services.powerbi-modeling-mcp'
      is not installed, installs the latest from the marketplace; otherwise leaves it.
    - Ensures the project-scoped .mcp.json npx fallback exists (zero-install, always latest).
    - Verifies the npm package is reachable.
    - Prints the activation steps. No manual editing required.

    Source: https://github.com/microsoft/powerbi-modeling-mcp
    Default mode is READ-ONLY (safe; BPA only inspects the model).

.PARAMETER ReadWrite
    Register the npx fallback in read-write mode (writes still prompt). Default: read-only.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup\Install-PowerBIModelingMCP.ps1
#>
[CmdletBinding()]
param(
    [switch]$ReadWrite
)

$ErrorActionPreference = 'Stop'
$ExtensionId = 'analysis-services.powerbi-modeling-mcp'
$NpmPackage  = '@microsoft/powerbi-modeling-mcp'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$McpJsonPath = Join-Path $ProjectRoot '.mcp.json'

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    [OK]   $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "    [FAIL] $msg" -ForegroundColor Red }

function Test-Cmd($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "============================================================" -ForegroundColor DarkCyan
Write-Host " Power BI Modeling MCP - Automated Setup" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor DarkCyan

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
Write-Step 'Checking prerequisites'
$prereqFail = $false

if (Test-Cmd 'node') {
    Write-Ok "Node.js $(node --version)"
} else {
    Write-Err 'Node.js not found. Install it with:  winget install OpenJS.NodeJS.LTS'
    $prereqFail = $true
}

$hasCode = Test-Cmd 'code'
if ($hasCode) {
    Write-Ok "VS Code CLI present ($((code --version)[0]))"
} else {
    Write-Warn2 "VS Code 'code' CLI not on PATH. Extension auto-install will be skipped; the npx fallback will be used instead."
    Write-Warn2 "To enable it later: VS Code > Ctrl+Shift+P > 'Shell Command: Install code command in PATH'."
}

if ($prereqFail) {
    Write-Err 'Missing required prerequisite(s). Fix the above and re-run this script.'
    exit 1
}

# ---------------------------------------------------------------------------
# 2. VS Code extension - install only if missing (auto-detect)
# ---------------------------------------------------------------------------
Write-Step "Ensuring VS Code extension '$ExtensionId'"
if ($hasCode) {
    $installed = (code --list-extensions) -contains $ExtensionId
    if ($installed) {
        Write-Ok 'Extension already installed - leaving as is.'
    } else {
        Write-Host '    Installing latest extension from the marketplace...' -ForegroundColor Gray
        code --install-extension $ExtensionId --force | Out-Null
        if ((code --list-extensions) -contains $ExtensionId) {
            Write-Ok 'Extension installed.'
        } else {
            Write-Warn2 'Extension install did not confirm; the npx fallback below still works.'
        }
    }
} else {
    Write-Warn2 'Skipped (no code CLI). Relying on npx fallback.'
}

# ---------------------------------------------------------------------------
# 3. Project .mcp.json npx fallback (zero-install, always latest)
# ---------------------------------------------------------------------------
Write-Step 'Ensuring project .mcp.json (npx fallback)'
$mcpArgs = @('/c','npx','-y',"$NpmPackage@latest",'--start','--accepteula')
if (-not $ReadWrite) { $mcpArgs += '--readonly' }

$mcp = @{
    mcpServers = @{
        'powerbi-modeling-mcp' = @{
            type    = 'stdio'
            command = 'cmd'
            args    = $mcpArgs
        }
    }
}
$mcp | ConvertTo-Json -Depth 6 | Set-Content -Path $McpJsonPath -Encoding UTF8
$mode = if ($ReadWrite) { 'read-write' } else { 'read-only' }
Write-Ok ".mcp.json written ($mode): $McpJsonPath"

# ---------------------------------------------------------------------------
# 4. Verify the npm package is reachable
# ---------------------------------------------------------------------------
Write-Step 'Verifying npm package availability'
try {
    $ver = (npm view $NpmPackage version 2>$null | Select-Object -Last 1)
    if ($ver) { Write-Ok "$NpmPackage@$ver reachable on npm." }
    else      { Write-Warn2 "Could not read version (offline?). npx will still fetch on first run if online." }
} catch {
    Write-Warn2 "npm view failed (offline?). npx will fetch on first run when online."
}

# ---------------------------------------------------------------------------
# 5. Done - activation steps
# ---------------------------------------------------------------------------
Write-Host "`n============================================================" -ForegroundColor DarkCyan
Write-Host " Setup complete. To ACTIVATE:" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor DarkCyan
Write-Host @"
  1. Open your model in Power BI Desktop (e.g. powerbi\AI Summaries.pbix) and keep it open.
  2. Reload VS Code:  Ctrl+Shift+P  ->  'Developer: Reload Window'
     (a newly added MCP server is not live in an already-running session).
  3. Ask the agent:   "List the available powerbi-modeling MCP tools."
  4. Connect:         Connect to 'AI Summaries' in Power BI Desktop
  5. Run BPA:         @bpa-agent run the Best Practice Analyzer on "AI Summaries.pbix"

  Mode: $mode   (edit .mcp.json or re-run with -ReadWrite to change)
"@ -ForegroundColor Green
