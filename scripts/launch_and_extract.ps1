<#
.SYNOPSIS
    Open a .pbix in Power BI Desktop (minimized), wait for its model to load, extract the model
    metadata via the existing DMV extractor, then close the instance this script launched.

.DESCRIPTION
    A modern .pbix model is a binary VertiPaq image that only Power BI Desktop's own loader can
    open (a standalone engine cannot Restore it). This is the "Launch it for me" fallback: the
    dashboard uses it when no model is already open and no PBIP/TMDL is available. The user still
    just uploads a file and clicks Execute — Desktop opens and closes in the background.

.PARAMETER PbixPath   The .pbix to open.
.PARAMETER OutFile    Where to write the model JSON (same shape as extract_model_dmv.ps1).
.PARAMETER TimeoutSec Max seconds to wait for the engine + model to load (default 180).
.PARAMETER NoClose    Leave Power BI Desktop open afterwards (default: close what we launched).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PbixPath,
    [string]$OutFile = (Join-Path $env:TEMP 'pbi_model.json'),
    [int]$TimeoutSec = 180,
    [switch]$NoClose
)
$ErrorActionPreference = 'Stop'
function Fail($code, $msg) { Write-Error $msg; exit $code }

if (-not (Test-Path $PbixPath)) { Fail 2 "pbix not found: $PbixPath" }
$PbixPath = (Resolve-Path $PbixPath).Path

$pbi = 'C:\Program Files\Microsoft Power BI Desktop\bin\PBIDesktop.exe'
if (-not (Test-Path $pbi)) {
    $pbi = Get-ChildItem 'C:\Program Files\Microsoft Power BI Desktop' -Recurse -Filter PBIDesktop.exe `
               -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $pbi) { Fail 3 "PBIDesktop.exe not found. Install Power BI Desktop." }

$ws = Join-Path $env:LOCALAPPDATA 'Microsoft\Power BI Desktop\AnalysisServicesWorkspaces'

# snapshot existing workspace port files so we can spot the one THIS launch creates
$before = @{}
if (Test-Path $ws) {
    Get-ChildItem $ws -Recurse -Filter 'msmdsrv.port.txt' -ErrorAction SilentlyContinue |
        ForEach-Object { $before[$_.FullName] = $true }
}

$proc = Start-Process -FilePath $pbi -ArgumentList "`"$PbixPath`"" -WindowStyle Minimized -PassThru
$launchedPid = $proc.Id

# load ADOMD once, for the model-loaded probe
$adomd = Get-ChildItem "$env:windir\Microsoft.NET\assembly" -Recurse `
            -Filter 'Microsoft.AnalysisServices.AdomdClient.dll' -ErrorAction SilentlyContinue |
         Sort-Object { $_.VersionInfo.FileVersion } -Descending | Select-Object -First 1
if ($adomd) { [System.Reflection.Assembly]::LoadFrom($adomd.FullName) | Out-Null }

$deadline = (Get-Date).AddSeconds($TimeoutSec)
$port = 0
try {
    # 1) wait for a NEW workspace engine port
    while ((Get-Date) -lt $deadline -and $port -le 0) {
        Start-Sleep -Milliseconds 700
        if (Test-Path $ws) {
            $pf = Get-ChildItem $ws -Recurse -Filter 'msmdsrv.port.txt' -ErrorAction SilentlyContinue |
                  Where-Object { -not $before.ContainsKey($_.FullName) } |
                  Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($pf) {
                $raw = (Get-Content $pf.FullName -Encoding Unicode -ErrorAction SilentlyContinue)
                if ($raw) { $p = 0; if ([int]::TryParse(($raw.ToString().Trim()), [ref]$p)) { $port = $p } }
            }
        }
    }
    if ($port -le 0) { Fail 6 "Power BI Desktop did not start a model engine within $TimeoutSec s." }

    # 2) wait for the model (database/catalog) to appear, then for its tables to populate.
    #    NOTE: ADOMD ExecuteScalar is unsupported on DMV rowsets — use ExecuteReader only.
    $loaded = $false
    while ((Get-Date) -lt $deadline -and -not $loaded) {
        try {
            $cn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$port;")
            $cn.Open()
            $cmd = $cn.CreateCommand()
            $cmd.CommandText = 'SELECT [CATALOG_NAME] FROM $SYSTEM.DBSCHEMA_CATALOGS'
            $rd = $cmd.ExecuteReader(); $cat = $null
            while ($rd.Read()) { if ($rd.GetValue(0)) { $cat = $rd.GetValue(0) } }
            $rd.Close()
            if ($cat) {
                $c2 = $cn.CreateCommand()
                $c2.CommandText = 'SELECT [ID] FROM $SYSTEM.TMSCHEMA_TABLES'
                $r2 = $c2.ExecuteReader(); $cnt = 0
                while ($r2.Read()) { $cnt++ }
                $r2.Close()
                if ($cnt -gt 0) { $loaded = $true }
            }
            $cn.Close()
        } catch { }
        if (-not $loaded) { Start-Sleep -Milliseconds 800 }
    }
    if (-not $loaded) { Fail 7 "Model did not finish loading within $TimeoutSec s." }

    # 3) reuse the existing extractor against the discovered port
    $extract = Join-Path $PSScriptRoot 'extract_model_dmv.ps1'
    $res = & powershell -NoProfile -ExecutionPolicy Bypass -File $extract -OutFile $OutFile -Port $port
    Write-Output $res
}
finally {
    if (-not $NoClose) {
        # close the Desktop instance we launched; its engine child exits with it
        try {
            $p = Get-Process -Id $launchedPid -ErrorAction SilentlyContinue
            if ($p) {
                $null = $p.CloseMainWindow()
                Start-Sleep -Milliseconds 1500
                if (-not $p.HasExited) { Stop-Process -Id $launchedPid -Force -ErrorAction SilentlyContinue }
            }
        } catch { }
    }
}
