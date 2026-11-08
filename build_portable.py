"""Assemble the LosslessCutter Windows portable folder.

Layout:
  LosslessCutter/
    LosslessCutter.exe     (compiled launcher, see launcher.c)
    pythonw.exe, python312.dll, python312.zip, ... (CPython 3.12.7 embeddable)
    python312._pth         (paths: Lib/site-packages, app)
    Lib/site-packages/     (PyAV 16.0.1, PySide6-Essentials, PySide6-Addons, shiboken6, numpy - win_amd64 wheels)
    app/smartcut/          (engine fork, MIT)
    app/losslesscutter/    (GUI)
    README.md, LICENSE files
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "build-cache"
DIST = ROOT / "dist" / "LosslessCutter"


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    # 1. CPython embeddable
    with zipfile.ZipFile(CACHE / "python-embed.zip") as z:
        z.extractall(DIST)

    # 2. Path configuration for the embedded interpreter
    (DIST / "python312._pth").write_text(
        "python312.zip\n.\nLib\\site-packages\napp\n", encoding="utf-8"
    )

    # 3. Wheels -> Lib/site-packages. The PySide6-Addons wheel is pruned
    # while extracting: the app uses only QtMultimedia from it, and the
    # rest (Qt 3D, Charts, Location, WebView, the QtQuick3D QML tree -
    # ~100 MB) would ship dead weight. Pruning is a denylist over the
    # Addons wheel only, derived from the 6.12.0 Essentials/Addons wheel
    # diff; Essentials files are never touched. Kept: everything with
    # "multimedia" or "spatialaudio" in its path, the FFmpeg runtime
    # libraries the multimedia backend loads (avcodec-*.dll etc., which
    # match no prune token), and all shared files.
    prune_tokens = (
        "3d", "axcontainer", "axbase", "axserver", "bluetooth",
        "canvaspainter", "charts", "connectivity", "datavisualization",
        "graphs", "httpserver", "location", "networkauth", "nfc",
        "positioning", "remoteobjects", "scxml", "sensors", "serialbus",
        "serialport", "shadertools", "statemachine", "texttospeech",
        "virtualkeyboard", "webchannel", "websockets", "webview",
    )
    prune_dirs = (
        "PySide6/plugins/assetimporters", "PySide6/plugins/canbus",
        "PySide6/plugins/geometryloaders", "PySide6/plugins/geoservices",
        "PySide6/plugins/position", "PySide6/plugins/renderers",
        "PySide6/plugins/renderplugins", "PySide6/plugins/sceneparsers",
        "PySide6/plugins/scxmldatamodel", "PySide6/plugins/sensors",
        "PySide6/plugins/texttospeech", "PySide6/plugins/webview",
        "PySide6/qml/Qt5Compat", "PySide6/QtAsyncio",
    )
    keep_tokens = ("multimedia", "spatialaudio")

    def addons_pruned(name: str) -> bool:
        if any(name == d or name.startswith(d + "/") for d in prune_dirs):
            return True
        low = name.lower()
        if any(k in low for k in keep_tokens):
            return False
        return any(tok in part.lower()
                   for part in name.split("/") for tok in prune_tokens)

    site_packages = DIST / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    wheels = sorted((CACHE / "wheels").glob("*.whl"))
    assert wheels, "no wheels in build-cache/wheels"
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as z:
            if "addons" in wheel.name.lower():
                kept = dropped = dropped_bytes = 0
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    if addons_pruned(info.filename):
                        dropped += 1
                        dropped_bytes += info.file_size
                    else:
                        z.extract(info, site_packages)
                        kept += 1
                print(f"installed {wheel.name} (pruned: {dropped} files, "
                      f"{dropped_bytes / 1e6:.1f} MB dropped, {kept} kept)")
            else:
                z.extractall(site_packages)
                print("installed", wheel.name)

    # 4. App code
    app_dir = DIST / "app"
    for pkg in ("smartcut", "losslesscutter"):
        shutil.copytree(
            ROOT / "src" / pkg, app_dir / pkg,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    # 5. Launcher exe (cross-compiled with mingw), with the app icon embedded
    icon_obj = CACHE / "icon.o"
    subprocess.run(
        ["x86_64-w64-mingw32-windres", "-i", str(ROOT / "icon.rc"),
         "-o", str(icon_obj), "-O", "coff"],
        check=True, cwd=ROOT,
    )
    subprocess.run(
        ["x86_64-w64-mingw32-gcc", "-mwindows", "-municode", "-O2", "-s",
         "-o", str(DIST / "LosslessCutter.exe"), str(ROOT / "launcher.c"),
         str(icon_obj), "-lshell32"],
        check=True,
    )

    # 6. Docs
    shutil.copy(ROOT / "README.md", DIST / "README.md")
    print("assembled:", DIST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
