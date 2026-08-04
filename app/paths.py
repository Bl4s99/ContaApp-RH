from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Carpeta de la instalación: junto al `.exe` cuando la app corre
    compilada (PyInstaller `--onefile`; `__file__` ahí apunta a una
    carpeta temporal de autoextracción distinta en cada arranque, no
    sirve), junto al código fuente cuando corre como script. Es la
    ubicación estable donde deben vivir `empleados.db`, `backups/` y
    `logs/` -- compartida por `database.py` y `logging_config.py` para
    que ambos calculen siempre la misma carpeta."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
