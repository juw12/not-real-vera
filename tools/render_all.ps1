param([string]$Episodes)
# Render several episodes one after another, each with its own log.
#   powershell -File tools\render_all.ps1 -Episodes ep01,ep02
# Set NRV_PYTHON to a specific python.exe if "python" on PATH is not the one with the packages.
$env:PYTHONIOENCODING = 'utf-8'
$python = if ($env:NRV_PYTHON) { $env:NRV_PYTHON } else { 'python' }
Set-Location $PSScriptRoot\..
foreach ($episode in $Episodes.Split(',')) {
    & $python pipeline\make_episode.py $episode *> "output\render_$episode.log"
    "$episode exit $LASTEXITCODE $(Get-Date -Format HH:mm:ss)" | Add-Content output\render_all.log
}
