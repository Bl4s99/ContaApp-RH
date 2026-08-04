from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_KEEP = 30
# Con precisión de segundo, dos create_backup() en la misma ejecución (p. ej.
# stage_restore(): una copia de seguridad del estado actual seguida de leer
# la copia elegida) podían generar el mismo nombre de archivo y la segunda
# sobrescribía en silencio el contenido de la primera -- con microsegundos,
# una colisión exigiría dos llamadas en menos de un microsegundo, algo que
# el propio I/O de sqlite3.Connection.backup() hace imposible en la práctica.
_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S_%f"
_PENDING_RESTORE_SUFFIX = ".pending_restore"


@dataclass(frozen=True, slots=True)
class BackupInfo:
    path: Path
    created_at: datetime
    size_bytes: int


class BackupRepository:
    """Copias de seguridad de la base de datos completa, como archivos .db
    independientes en su propio directorio -- deliberadamente sin ninguna
    tabla ni metadato dentro de la propia base de datos que protegen: si
    algún día empleados.db se corrompe, el listado de copias disponibles
    debe poder leerse igual, solo a partir del sistema de archivos."""

    def __init__(
        self, conn: sqlite3.Connection, db_path: Path, backups_dir: Path | None = None
    ) -> None:
        self._conn = conn
        self._db_path = db_path
        self._backups_dir = backups_dir or (db_path.parent / "backups")
        self._prefix = f"{db_path.stem}_"

    @property
    def backups_dir(self) -> Path:
        return self._backups_dir

    def create_backup(self, *, prune_keep: int | None = DEFAULT_KEEP) -> Path:
        """Copia la base de datos activa a un archivo nuevo con marca de
        tiempo. Usa la API de backup en caliente de sqlite3 (lee de la
        conexión ya abierta) en vez de copiar el archivo a pelo -- es la
        forma oficialmente segura de respaldar una base de datos que puede
        estar en uso, sin arriesgarse a copiar a medio escribir."""
        self._backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
        dest_path = self._backups_dir / f"{self._prefix}{timestamp}.db"
        dest_conn = sqlite3.connect(dest_path)
        try:
            self._conn.backup(dest_conn)
        finally:
            dest_conn.close()
        if prune_keep is not None:
            self.prune_old_backups(keep=prune_keep)
        return dest_path

    def list_backups(self) -> list[BackupInfo]:
        if not self._backups_dir.exists():
            return []
        backups = []
        for path in self._backups_dir.glob(f"{self._prefix}*.db"):
            created_at = self._parse_timestamp(path)
            if created_at is None:
                continue
            backups.append(
                BackupInfo(path=path, created_at=created_at, size_bytes=path.stat().st_size)
            )
        backups.sort(key=lambda b: b.created_at, reverse=True)
        return backups

    def has_backup_today(self) -> bool:
        today = datetime.now().date()
        return any(backup.created_at.date() == today for backup in self.list_backups())

    def prune_old_backups(self, *, keep: int) -> list[Path]:
        to_delete = self.list_backups()[keep:]
        for backup in to_delete:
            backup.path.unlink(missing_ok=True)
        return [backup.path for backup in to_delete]

    def stage_restore(self, backup_path: Path) -> Path:
        """Prepara `backup_path` para sustituir la base de datos activa en
        el PRÓXIMO arranque de la app, en vez de sustituirla ahora mismo: la
        conexión activa sigue abierta sobre el archivo actual durante toda
        esta sesión, así que sustituirlo por debajo ahora sería modificar un
        archivo bajo una conexión sqlite3 ya en uso, con riesgo real de
        bloqueo o corrupción según la plataforma. En su lugar, se copia la
        copia elegida a un archivo "pendiente" junto al real;
        apply_pending_restore() (llamada por main.py antes de abrir ninguna
        conexión) hace el cambio real, en el único momento en que es
        completamente seguro. Devuelve la copia de seguridad del estado
        ACTUAL, tomada antes de preparar nada, por si la copia elegida
        resulta ser la equivocada."""
        safety_backup = self.create_backup(prune_keep=None)
        shutil.copyfile(backup_path, self._pending_restore_path())
        return safety_backup

    def _pending_restore_path(self) -> Path:
        return self._db_path.with_name(self._db_path.name + _PENDING_RESTORE_SUFFIX)

    def _parse_timestamp(self, path: Path) -> datetime | None:
        stem = path.stem
        if not stem.startswith(self._prefix):
            return None
        raw = stem[len(self._prefix) :]
        try:
            return datetime.strptime(raw, _TIMESTAMP_FORMAT)
        except ValueError:
            return None


def apply_pending_restore(db_path: Path) -> bool:
    """Si BackupRepository.stage_restore() dejó una restauración pendiente,
    la aplica ahora sustituyendo db_path. Debe llamarse ANTES de abrir
    ninguna conexión sqlite3 sobre db_path -- es el único momento en que
    sustituir el archivo es completamente seguro. Devuelve True si se
    aplicó algo."""
    pending_path = db_path.with_name(db_path.name + _PENDING_RESTORE_SUFFIX)
    if not pending_path.exists():
        return False
    os.replace(pending_path, db_path)
    return True


def format_backup_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kb = size_bytes / 1024
    if kb < 1024:
        return f"{kb:.0f} KB"
    return f"{kb / 1024:.1f} MB"
