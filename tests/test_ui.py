from __future__ import annotations

import sqlite3
import tkinter as tk
from pathlib import Path

import pytest

from app.backup import BackupRepository
from app.repository import Repositories
from app.ui import BackupManagerDialog

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


class TestBackupManagerDialogErrorHandling:
    def test_create_backup_sqlite_error_shown_instead_of_uncaught(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Regresión: sqlite3.Connection.backup() puede lanzar
        # sqlite3.OperationalError (BD bloqueada, error de E/S de SQLite),
        # no solo OSError -- main.py ya capturaba ambos al crear la copia
        # automática de arranque, pero este diálogo solo capturaba OSError,
        # dejando la excepción sin capturar y al usuario sin ningún aviso.
        repos = Repositories.create(conn)
        backups = BackupRepository(conn, tmp_path / "empleados.db")

        def _raise_operational_error(*_a: object, **_k: object) -> Path:
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(backups, "create_backup", _raise_operational_error)

        dialog = BackupManagerDialog(tk_root, repos, backups)
        dialog._handle_create()  # no debe propagar la excepción

        assert "No se pudo crear la copia" in dialog.error_label.cget("text")
        dialog.destroy()

    def test_stage_restore_sqlite_error_shown_instead_of_uncaught(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repos = Repositories.create(conn)
        db_path = tmp_path / "empleados.db"
        backups = BackupRepository(conn, db_path)
        backups.create_backup(prune_keep=None)  # para que _refresh() liste algo

        dialog = BackupManagerDialog(tk_root, repos, backups)
        assert dialog.tree.get_children()  # _refresh() ya listó la copia creada arriba
        dialog.tree.selection_set("0")

        def _raise_operational_error(*_a: object, **_k: object) -> Path:
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(backups, "stage_restore", _raise_operational_error)

        import tkinter.messagebox as messagebox

        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        dialog._handle_restore()  # no debe propagar la excepción

        assert "No se pudo preparar la restauración" in dialog.error_label.cget("text")
        dialog.destroy()
