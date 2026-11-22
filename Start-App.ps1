$ErrorActionPreference = 'Stop'
$studioPython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $studioPython)) {
    $studioPython = (Get-Command pythonw.exe -ErrorAction Stop).Source
}
$studioEntry = Join-Path $PSScriptRoot 'app.py'
Start-Process -FilePath $studioPython -ArgumentList @('"' + $studioEntry + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
