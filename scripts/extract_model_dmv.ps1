<#
.SYNOPSIS
    Extract Power BI Desktop model metadata (TMSCHEMA DMVs) from the live local engine to JSON.

.DESCRIPTION
    Connects to the local Analysis Services instance that Power BI Desktop starts when a model
    is open, using ADOMD.NET (loaded from the GAC). Queries the TMSCHEMA_* DMVs and writes a
    single JSON file consumed by scripts/evaluate_bpa.py. No fabrication — a real read of the
    loaded model. Requires Power BI Desktop running with the model open.

.PARAMETER OutFile
    Where to write the JSON. Default: %TEMP%\pbi_model.json

.PARAMETER Port
    Local engine port. If omitted, auto-discovered from the most recent msmdsrv.port.txt.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\extract_model_dmv.ps1 -OutFile model.json
#>
[CmdletBinding()]
param(
    [string]$OutFile = (Join-Path $env:TEMP 'pbi_model.json'),
    [int]$Port = 0
)
$ErrorActionPreference = 'Stop'

# --- locate the running engine port ---
if (-not $Port) {
    $ws = Join-Path $env:LOCALAPPDATA 'Microsoft\Power BI Desktop\AnalysisServicesWorkspaces'
    $pf = Get-ChildItem -Path $ws -Recurse -Filter 'msmdsrv.port.txt' -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $pf) {
        Write-Error "No running Power BI Desktop model found (no msmdsrv.port.txt). Open the .pbix in Power BI Desktop first."
        exit 2
    }
    $Port = [int]((Get-Content $pf.FullName -Encoding Unicode).Trim())
}

# --- locate ADOMD.NET in the GAC (pick the highest version) ---
$adomd = Get-ChildItem -Path "$env:windir\Microsoft.NET\assembly" -Recurse `
            -Filter 'Microsoft.AnalysisServices.AdomdClient.dll' -ErrorAction SilentlyContinue |
         Sort-Object { $_.VersionInfo.FileVersion } -Descending | Select-Object -First 1
if (-not $adomd) {
    Write-Error "ADOMD.NET not found in the GAC. Install the client libraries (ships with Power BI Desktop / SSMS / the powerbi-modeling MCP extension)."
    exit 3
}
[System.Reflection.Assembly]::LoadFrom($adomd.FullName) | Out-Null

# --- connect and query ---
$cn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Port;")
$cn.Open()
function Invoke-Dmv($dmv) {
    try {
        $cmd = $cn.CreateCommand(); $cmd.CommandText = "SELECT * FROM $dmv"
        $rd = $cmd.ExecuteReader(); $rows = @()
        while ($rd.Read()) {
            $o = [ordered]@{}
            for ($i = 0; $i -lt $rd.FieldCount; $i++) { $o[$rd.GetName($i)] = $rd.GetValue($i) }
            $rows += [pscustomobject]$o
        }
        $rd.Close(); ,$rows
    } catch { ,@() }   # some DMVs may be unavailable on a given engine; keep going
}
$model = [ordered]@{
    tables        = Invoke-Dmv '$SYSTEM.TMSCHEMA_TABLES'
    columns       = Invoke-Dmv '$SYSTEM.TMSCHEMA_COLUMNS'
    measures      = Invoke-Dmv '$SYSTEM.TMSCHEMA_MEASURES'
    relationships = Invoke-Dmv '$SYSTEM.TMSCHEMA_RELATIONSHIPS'
    partitions    = Invoke-Dmv '$SYSTEM.TMSCHEMA_PARTITIONS'
    hierarchies   = Invoke-Dmv '$SYSTEM.TMSCHEMA_HIERARCHIES'
    levels        = Invoke-Dmv '$SYSTEM.TMSCHEMA_LEVELS'
    dependencies  = Invoke-Dmv '$SYSTEM.DISCOVER_CALC_DEPENDENCY'
    model         = Invoke-Dmv '$SYSTEM.TMSCHEMA_MODEL'
}
$cn.Close()

$model | ConvertTo-Json -Depth 8 | Out-File -FilePath $OutFile -Encoding UTF8
Write-Output ("OK port={0} out={1} tables={2} columns={3} measures={4} relationships={5}" -f `
    $Port, $OutFile, $model.tables.Count, $model.columns.Count, $model.measures.Count, $model.relationships.Count)
