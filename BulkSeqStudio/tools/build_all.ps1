# One-shot build: PyInstaller bundle + portable R assembly.
$ErrorActionPreference = "Continue"
$root = "C:\Users\Heisar\WorkBuddy\2026-10-22-15-45-38"
Set-Location $root
$py = "D:\Users\Heisar\miniconda3\envs\bulkseq\Scripts\python.exe"
$dist = Join-Path $root "dist\BulkSeqStudio"

# 0) stop a running instance so files are not locked
Get-Process BulkSeqStudio -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 800

# 1) move previous build aside (PyInstaller refuses to delete many files at once)
if (Test-Path $dist) {
    $old = Join-Path $root ("build\_old_" + (Get-Date -Format "HHmmss"))
    [System.IO.Directory]::Move($dist, $old)
    Write-Host "previous build -> $old"
}

# 2) bundle (via cmd so native stderr does not abort the script)
Write-Host "running PyInstaller ..."
cmd /c "`"$py`" -m PyInstaller bulkseq.spec --noconfirm --distpath dist --workpath build\pyi > build\pyi.log 2>&1"
if (-not (Test-Path (Join-Path $dist "BulkSeqStudio.exe"))) {
    Get-Content "build\pyi.log" -Tail 30
    throw "PyInstaller failed"
}
Write-Host "PyInstaller OK"

# 3) assemble portable R
Write-Host "copying portable R ..."
robocopy (Join-Path $root "build\BulkSeqStudio\R") (Join-Path $dist "R") /E /NFL /NDL /NJH /NJS /NP | Out-Null
foreach ($dll in @("VCRUNTIME140.dll", "VCRUNTIME140_1.dll", "MSVCP140.dll")) {
    Copy-Item (Join-Path $dist "_internal\$dll") (Join-Path $dist "R\bin\x64") -Force
    Copy-Item (Join-Path $dist "_internal\$dll") $dist -Force
}

$s = (Get-ChildItem $dist -Recurse -File | Measure-Object Length -Sum)
Write-Host ("dist: {0:N0} files, {1:N0} MB" -f $s.Count, ($s.Sum / 1MB))
