# Build a portable R runtime containing DESeq2 / edgeR / limma and their dependencies.
# Pure ASCII source; package keep-list is read from .tools/r_keep.txt
$ErrorActionPreference = "Stop"

$src = "D:\Program_Files\R\R-4.5.2"
$root = "C:\Users\Heisar\WorkBuddy\2026-10-22-15-45-38"
$dst = Join-Path $root "build\BulkSeqStudio\R"
$keepFile = Join-Path $root ".tools\r_keep.txt"

if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
New-Item -ItemType Directory -Path $dst -Force | Out-Null

# 1) core runtime directories
foreach ($d in @("bin", "etc", "modules", "share")) {
    Write-Host "copy $d ..."
    robocopy (Join-Path $src $d) (Join-Path $dst $d) /E /NFL /NDL /NJH /NJS /NP | Out-Null
}
# 2) top-level license files
foreach ($f in @("COPYING", "README", "README.R-4.5.2")) {
    Copy-Item (Join-Path $src $f) $dst -Force
}

# 3) drop unneeded parts of the runtime
foreach ($p in @("doc", "tests", "include", "src", "Tcl", "bin\i386")) {
    $t = Join-Path $dst $p
    if (Test-Path $t) { Remove-Item $t -Recurse -Force }
}
# share: keep only what R needs at runtime
foreach ($p in @("share\doc", "share\dvi", "share\info", "share\man", "share\texmf", "share\zoneinfo")) {
    $t = Join-Path $dst $p
    if (Test-Path $t) { Remove-Item $t -Recurse -Force }
}

# 4) library: only keep packages in the dependency closure
$lib = Join-Path $dst "library"
New-Item -ItemType Directory -Path $lib -Force | Out-Null
$keep = Get-Content $keepFile | Where-Object { $_.Trim() -ne "" } | ForEach-Object { $_.Trim() }
Write-Host ("keep packages: " + $keep.Count)
foreach ($pkg in $keep) {
    $s = Join-Path $src ("library\" + $pkg)
    if (Test-Path $s) {
        robocopy $s (Join-Path $lib $pkg) /E /NFL /NDL /NJH /NJS /NP | Out-Null
    } else {
        Write-Host ("MISSING: " + $pkg)
    }
}

# 5) strip heavy optional content inside kept packages (docs/tests)
Get-ChildItem $lib -Directory | ForEach-Object {
    foreach ($sub in @("doc", "tests", "src", "demo", "include")) {
        $t = Join-Path $_.FullName $sub
        if (Test-Path $t) { Remove-Item $t -Recurse -Force -ErrorAction SilentlyContinue }
    }
    # help/ and html/ inside a package make up most of its size
    foreach ($sub in @("help", "html")) {
        $t = Join-Path $_.FullName $sub
        if (Test-Path $t) { Remove-Item $t -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

$sz = (Get-ChildItem $dst -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum)
Write-Host ("portable R: {0:N0} files, {1:N0} MB" -f $sz.Count, ($sz.Sum / 1MB))
