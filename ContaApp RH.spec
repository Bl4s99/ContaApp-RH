# -*- mode: python ; coding: utf-8 -*-

# Metadatos de versión del .exe (FileVersion/ProductVersion, visibles en
# Propiedades > Detalles en Windows) -- generados aquí, en vez de mantener
# un version_info.txt a mano, para que app/version.py siga siendo la única
# fuente de verdad del número de versión (usado también por
# app/update_check.py para comparar contra contaapp.es/version-rh.json).
import sys
from pathlib import Path

try:
    from app.version import VERSION
except ImportError:
    # SPECPATH lo inyecta PyInstaller con la carpeta donde vive este .spec
    # -- fallback por si el cwd no queda ya en sys.path al ejecutar esto.
    sys.path.insert(0, SPECPATH)
    from app.version import VERSION

_version_tuple = tuple(int(p) for p in VERSION.split(".")) + (0,)
Path("version_info.txt").write_text(
    "VSVersionInfo(\n"
    f"  ffi=FixedFileInfo(filevers={_version_tuple}, prodvers={_version_tuple}, "
    "mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
    "  kids=[StringFileInfo([StringTable('040904B0', [\n"
    "      StringStruct('CompanyName', 'ContaApp'),\n"
    "      StringStruct('FileDescription', 'ContaApp RH'),\n"
    f"      StringStruct('FileVersion', '{VERSION}'),\n"
    "      StringStruct('ProductName', 'ContaApp RH'),\n"
    f"      StringStruct('ProductVersion', '{VERSION}'),\n"
    "  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])],\n"
    ")\n",
    encoding="utf-8",
)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ContaApp RH',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version="version_info.txt",
)
