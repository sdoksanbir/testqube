from __future__ import annotations
from pathlib import Path
import sys

def project_root() -> Path:
    # PyInstaller (frozen) modunda dosyalar sys._MEIPASS altına çıkar
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    # Normal geliştirme ortamı (repo kökü)
    return Path(__file__).resolve().parents[3]

def resources_dir() -> Path:
    return project_root() / "resources"

def asset_path(filename: str) -> str:
    return str(resources_dir() / "assets" / filename)

def fonts_dir() -> Path:
    return resources_dir() / "fonts"
