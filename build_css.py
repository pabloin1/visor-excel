"""Compile Tailwind CSS from Python without a Node.js toolchain.

The pinned standalone Tailwind executable is downloaded only when needed.
The generated CSS is checked into the project, so running Django stays offline.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
VERSION = "4.3.3"
ASSET = "tailwindcss-windows-x64.exe"
SHA256 = "e0e260ce048014e9268f6237ff18f8ccf02cef521cbd0ae04e82c2cdf7aa3955"
DOWNLOAD_URL = (
    f"https://github.com/tailwindlabs/tailwindcss/releases/download/v{VERSION}/{ASSET}"
)
CACHE_DIR = ROOT / ".cache"
EXECUTABLE = CACHE_DIR / f"tailwindcss-v{VERSION}-windows-x64.exe"
SOURCE = ROOT / "assets" / "tailwind.css"
OUTPUT = ROOT / "documents" / "static" / "documents" / "app.generated.css"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_executable() -> None:
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Este script de compilación admite Windows de 64 bits.")

    if EXECUTABLE.is_file() and sha256(EXECUTABLE) == SHA256:
        return

    CACHE_DIR.mkdir(exist_ok=True)
    request = Request(DOWNLOAD_URL, headers={"User-Agent": "visor-excel-css-build"})
    print(f"Descargando Tailwind CSS v{VERSION} (solo la primera vez)...")
    with tempfile.NamedTemporaryFile(dir=CACHE_DIR, delete=False) as stream:
        temporary_path = Path(stream.name)
    try:
        with temporary_path.open("wb") as stream:
            with urlopen(request, timeout=60) as response:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    stream.write(chunk)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    if sha256(temporary_path) != SHA256:
        temporary_path.unlink(missing_ok=True)
        raise SystemExit("El ejecutable descargado no coincide con el SHA-256 oficial.")
    os.replace(temporary_path, EXECUTABLE)


def main() -> None:
    ensure_executable()
    subprocess.run(
        [str(EXECUTABLE), "-i", str(SOURCE), "-o", str(OUTPUT), "--minify"],
        cwd=ROOT,
        check=True,
    )
    print(f"CSS actualizado: {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
