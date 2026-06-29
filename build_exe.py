from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXE_NAME = "CPUProcessLimiter"


def main() -> int:
    if sys.platform != "win32":
        print("Windows exe must be built on Windows.")
        print("Run this in Windows PowerShell or cmd:")
        print("  uv run --extra build python build_exe.py")
        return 1

    for path in (ROOT / "build", ROOT / "dist"):
        if path.exists():
            shutil.rmtree(path)

    spec_file = ROOT / f"{EXE_NAME}.spec"
    if spec_file.exists():
        spec_file.unlink()

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        EXE_NAME,
        "--hidden-import",
        "pystray._win32",
        "--hidden-import",
        "PIL._tkinter_finder",
        "--collect-submodules",
        "pystray",
        "--collect-submodules",
        "PIL",
        str(ROOT / "main.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)

    exe_path = ROOT / "dist" / f"{EXE_NAME}.exe"
    print(f"Built: {exe_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
