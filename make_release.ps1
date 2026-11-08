# make_release.ps1 - package LosslessCutter for release: the portable
# zip and the Inno Setup installer.
#
# Run from the repo root (the folder this script lives in):
#   powershell -ExecutionPolicy Bypass -File .\make_release.ps1
#
# If dist\LosslessCutter does not exist yet, it is built first, the
# same way as the manual builds: the v1.1 release portable zip is the
# binary skeleton (downloaded once into build-cache), the current
# src\ code is swapped into it, and the unused PySide6-Addons modules
# are pruned (same rules as build_portable.py). Delete
# dist\LosslessCutter to force a fresh skeleton build.
#
# Outputs:
#   LosslessCutter-<version>-portable.zip  (repo root)
#   dist-installer\LosslessCutter-<version>-setup.exe

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Fail($msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

# --- version (single source of truth: the package __init__) ---
$init = Get-Content "src\losslesscutter\__init__.py" -Raw
if ($init -notmatch '__version__\s*=\s*"([^"]+)"') {
    Fail "could not read __version__ from src\losslesscutter\__init__.py"
}
$ver = $Matches[1]
Write-Host "Packaging LosslessCutter $ver"

# --- icon (the .iss references it; it is generated, not kept in git) ---
$icon = Join-Path $root "src\losslesscutter\icon.ico"
if (-not (Test-Path $icon)) {
    Write-Host "icon.ico missing - generating it..."
    $candidates = @()
    if ($env:VIRTUAL_ENV) { $candidates += Join-Path $env:VIRTUAL_ENV "Scripts\python.exe" }
    $candidates += Join-Path $root ".venv\Scripts\python.exe"
    $candidates += Join-Path $root "venv\Scripts\python.exe"
    $glob = Get-ChildItem (Join-Path $root "*\Scripts\python.exe") -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($glob) { $candidates += $glob.FullName }
    $cmdPy = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmdPy) { $candidates += $cmdPy.Source }
    $py = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $py) {
        Fail "icon.ico is missing and no Python was found to generate it (looked in VIRTUAL_ENV, .venv, venv, and PATH)."
    }
    Write-Host "Using Python: $py"
    & $py tools\make_icon.py
    if ($LASTEXITCODE -ne 0) { Fail "tools\make_icon.py failed (see its output above)." }
    if (-not (Test-Path $icon)) {
        Fail "tools\make_icon.py ran but src\losslesscutter\icon.ico still does not exist."
    }
}

# --- build dist\LosslessCutter from the v1.1 skeleton if needed ---
$dist = Join-Path $root "dist\LosslessCutter"
if (-not (Test-Path (Join-Path $dist "LosslessCutter.exe"))) {
    Write-Host "dist\LosslessCutter not found - building it from the v1.1 skeleton..."

    $cacheDir = Join-Path $root "build-cache"
    if (-not (Test-Path $cacheDir)) { New-Item -ItemType Directory $cacheDir | Out-Null }
    $skel = Join-Path $cacheDir "LosslessCutter-1.1-portable.zip"
    if (-not (Test-Path $skel)) {
        Write-Host "Downloading the v1.1 portable skeleton (174 MB, one time)..."
        & curl.exe -L -o $skel "https://github.com/dieroboter/losslesscutter/releases/download/v1.1/LosslessCutter-1.1-portable.zip"
        if ($LASTEXITCODE -ne 0) { Fail "skeleton download failed." }
    }

    $distParent = Join-Path $root "dist"
    if (-not (Test-Path $distParent)) { New-Item -ItemType Directory $distParent | Out-Null }
    if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
    & tar.exe -xf $skel -C $distParent
    if ($LASTEXITCODE -ne 0) { Fail "skeleton extraction failed." }
    if (-not (Test-Path (Join-Path $dist "LosslessCutter.exe"))) {
        Fail "skeleton extracted but dist\LosslessCutter\LosslessCutter.exe is missing."
    }

    # Swap in the current code (both packages).
    foreach ($pkg in @("losslesscutter", "smartcut")) {
        $target = Join-Path $dist "app\$pkg"
        if (Test-Path $target) { Remove-Item $target -Recurse -Force }
        Copy-Item (Join-Path $root "src\$pkg") $target -Recurse
        Get-ChildItem $target -Recurse -Directory -Filter "__pycache__" |
            Remove-Item -Recurse -Force
    }
    Write-Host "Current src code swapped into the skeleton."

    # Prune the unused PySide6-Addons modules (same rules as
    # build_portable.py: only QtMultimedia and friends are kept).
    $sp = Join-Path $dist "Lib\site-packages"
    $pruneDirs = @(
        "PySide6\plugins\assetimporters", "PySide6\plugins\canbus",
        "PySide6\plugins\geometryloaders", "PySide6\plugins\geoservices",
        "PySide6\plugins\position", "PySide6\plugins\renderers",
        "PySide6\plugins\renderplugins", "PySide6\plugins\sceneparsers",
        "PySide6\plugins\scxmldatamodel", "PySide6\plugins\sensors",
        "PySide6\plugins\texttospeech", "PySide6\plugins\webview",
        "PySide6\qml\Qt5Compat", "PySide6\QtAsyncio"
    )
    foreach ($d in $pruneDirs) {
        $p = Join-Path $sp $d
        if (Test-Path $p) { Remove-Item $p -Recurse -Force }
    }
    $tokens = @(
        "3d", "axcontainer", "axbase", "axserver", "bluetooth",
        "canvaspainter", "charts", "connectivity", "datavisualization",
        "graphs", "httpserver", "location", "networkauth", "nfc",
        "positioning", "remoteobjects", "scxml", "sensors", "serialbus",
        "serialport", "shadertools", "statemachine", "texttospeech",
        "virtualkeyboard", "webchannel", "websockets", "webview"
    )
    $keep = @("multimedia", "spatialaudio")
    $dropped = 0
    Get-ChildItem (Join-Path $sp "PySide6") -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($sp.Length + 1)
        $low = $rel.ToLower()
        foreach ($k in $keep) { if ($low.Contains($k)) { return } }
        foreach ($part in ($rel -split '[\\/]')) {
            $pl = $part.ToLower()
            foreach ($t in $tokens) {
                if ($pl.Contains($t)) {
                    Remove-Item $_.FullName -Force
                    $script:dropped++
                    return
                }
            }
        }
    }
    # Drop folders the prune left empty.
    Get-ChildItem (Join-Path $sp "PySide6") -Recurse -Directory |
        Sort-Object { $_.FullName.Length } -Descending |
        Where-Object { -not (Get-ChildItem $_.FullName -Force) } |
        Remove-Item -Force
    Write-Host "Addons pruned: $dropped files dropped."
    Write-Host "dist\LosslessCutter built."
}

# --- portable zip (the LosslessCutter folder at the zip root) ---
$zip = Join-Path $root "LosslessCutter-$ver-portable.zip"
Write-Host "Zipping $zip ..."
Compress-Archive -Path $dist -DestinationPath $zip -Force

# --- installer ---
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }
}
if (-not $iscc) {
    Fail "ISCC.exe (Inno Setup 6) not found - install Inno Setup or add it to PATH."
}
Write-Host "Building installer with $iscc ..."
& $iscc (Join-Path $root "losslesscutter.iss")
if ($LASTEXITCODE -ne 0) { Fail "Inno Setup compile failed." }

$setup = Join-Path $root "dist-installer\LosslessCutter-$ver-setup.exe"
if (-not (Test-Path $setup)) {
    Fail "installer output not found at $setup"
}

# --- summary ---
foreach ($f in @($zip, $setup)) {
    $item = Get-Item $f
    Write-Host ("{0}  ({1:N1} MB)" -f $item.FullName, ($item.Length / 1MB))
}
Write-Host "Done."
