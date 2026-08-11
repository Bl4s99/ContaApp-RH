from __future__ import annotations

import inspect
import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace

import pytest

from app import ui
from app.backup import BackupRepository
from app.models import Department
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


class TestMainWindowStartupOrder:
    def test_center_window_is_called_after_build_layout_in_source_order(self) -> None:
        # Regresión: center_window() llama a update_idletasks(), que mapea
        # la ventana en pantalla -- si eso ocurre ANTES de _build_layout()
        # (que construye la barra lateral y las 10 páginas, varias con sus
        # propias consultas a BD en su __init__), el usuario ve una ventana
        # vacía durante toda esa construcción, como un parpadeo negro al
        # arrancar. LoginWindow ya centra al final por el mismo motivo.
        #
        # No se instancia una MainWindow real aquí: un segundo tk.Tk() real
        # dentro del mismo proceso que el tk_root de sesión rompe la carga
        # de imágenes de EmployeePage (PhotoImage se crea contra el
        # intérprete Tcl equivocado -- error "image ... doesn't exist", un
        # artefacto de tener dos intérpretes Tcl a la vez en tests, no un
        # bug real de la app, que en uso normal solo tiene una MainWindow).
        # Se comprueba el orden real de las dos llamadas en el código fuente
        # en su lugar.
        source = inspect.getsource(ui.MainWindow.__init__)
        build_layout_pos = source.index("self._build_layout()")
        center_window_pos = source.index("center_window(self)")
        assert build_layout_pos < center_window_pos


class TestShowPageGridManagement:
    def test_switching_pages_removes_the_previous_one_from_grid(
        self, tk_root: tk.Tk
    ) -> None:
        # Regresión: tkraise() por sí solo cambia el orden de apilado pero
        # no saca a las páginas no visibles de la gestión de geometría --
        # las 10 páginas seguían todas grid()-eadas a la vez, así que cada
        # resize de la ventana recalculaba la geometría de las 10 en vez de
        # solo la visible. Se llama a _show_page() (método real, sin
        # mockear) sobre un objeto mínimo con solo el atributo _pages que
        # necesita, en vez de una MainWindow completa -- ver el comentario
        # en TestMainWindowStartupOrder sobre por qué evitar eso aquí.
        pages = {"a": ttk.Frame(tk_root), "b": ttk.Frame(tk_root)}
        fake_window = SimpleNamespace(_pages=pages)

        # SimpleNamespace no es una MainWindow real -- basta con que tenga
        # el atributo _pages que _show_page() de verdad usa.
        ui.MainWindow._show_page(fake_window, "a")  # type: ignore[arg-type]
        assert pages["a"].grid_info()
        assert not pages["b"].grid_info()

        ui.MainWindow._show_page(fake_window, "b")
        assert pages["b"].grid_info()
        assert not pages["a"].grid_info()


class TestGoCalendar:
    # No hay un botón "Calendario" genérico en la barra lateral -- solo uno
    # por departamento -- así que _go_calendar() elige el primero de
    # _visible_departments() (el propio departamento para un encargado, o
    # la lista completa para un admin). Mismo patrón de SimpleNamespace +
    # método real sin vincular que TestShowPageGridManagement, por el mismo
    # motivo (ver el comentario de esa clase): una MainWindow real rompe la
    # carga de PhotoImage en los tests.
    def _fake_window(
        self, departments: list[Department], locked_department_id: int | None
    ) -> tuple[SimpleNamespace, list[Department]]:
        calls: list[Department] = []
        fake = SimpleNamespace(
            _departments=departments,
            _locked_department_id=locked_department_id,
            _show_department_calendar=lambda d: calls.append(d),
        )
        fake._visible_departments = lambda: ui.MainWindow._visible_departments(
            fake  # type: ignore[arg-type]
        )
        return fake, calls

    def test_admin_picks_the_first_visible_department(self) -> None:
        dept_a = Department(id=1, name="Ventas")
        dept_b = Department(id=2, name="Producción")
        fake, calls = self._fake_window([dept_a, dept_b], locked_department_id=None)

        ui.MainWindow._go_calendar(fake)  # type: ignore[arg-type]

        assert calls == [dept_a]

    def test_encargado_picks_their_own_locked_department(self) -> None:
        dept_a = Department(id=1, name="Ventas")
        dept_b = Department(id=2, name="Producción")
        fake, calls = self._fake_window([dept_a, dept_b], locked_department_id=2)

        ui.MainWindow._go_calendar(fake)  # type: ignore[arg-type]

        assert calls == [dept_b]

    def test_admin_with_no_departments_is_a_noop(self) -> None:
        fake, calls = self._fake_window([], locked_department_id=None)

        ui.MainWindow._go_calendar(fake)  # type: ignore[arg-type]

        assert calls == []
