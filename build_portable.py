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

    # 3. Wheels -> Lib/site-packages
    site_packages = DIST / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    wheels = sorted((CACHE / "wheels").glob("*.whl"))
    assert wheels, "no wheels in build-cache/wheels"
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as z:
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
