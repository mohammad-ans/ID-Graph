from __future__ import annotations
from pathlib import Path

__all__ = ["preset_path", "available_presets"]
_HERE = Path(__file__).parent

def preset_path(name: str) -> Path:
    path = _HERE / name
    if not path.is_file():
        raise FileNotFoundError(f"No preset named {name!r} here")
    return path

def available_presets() -> list[str]:
    return sorted(p.name for p in _HERE.iterdir() if p.suffix in {".yaml", ".ngql"})