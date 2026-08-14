"""Director del VIDEO 1 -- "El Excel que edita todo el mundo".

Este script solo cubre la parte de la app (los beats 8-24s del guion). Los
primeros 8s (captura de un Excel de turnos con celdas de colores y algo
sobrescrito) se graban aparte, ver excel_caotico.png -- abrelo a pantalla
completa y graba esos primeros segundos ANTES de lanzar este script.
"""
from __future__ import annotations

import sqlite3

from video_common import VIDEO_DB_PATH, beat, done, force_foreground, wait_for_recording

from app.backup import BackupRepository
from app.database import get_connection
from app.repository import Repositories
from app.ui import MainWindow

DEPARTMENTS_IN_ORDER = ["Ventas", "Recursos Humanos"]


def main() -> None:
    conn = get_connection(VIDEO_DB_PATH)
    try:
        repos = Repositories.create(conn)
        admin_user = repos.users.list_all()[0]
        departments_by_name = {d.name: d for d in repos.departments.list_all()}

        wait_for_recording("VIDEO 1 -- El Excel que edita todo el mundo (parte de app, 8-24s)")

        backups = BackupRepository(conn, VIDEO_DB_PATH) if isinstance(conn, sqlite3.Connection) else None
        window = MainWindow(repos, admin_user, backups)
        window.update_idletasks()
        force_foreground(window)
        window.update()

        window._show_page("calendario")
        window._calendar_page.show_department(departments_by_name["Ventas"])
        window.update_idletasks()
        beat(5.0, "Calendario de Ventas en pantalla -- deja que se vea la rejilla completa", window)

        window._calendar_page.show_department(departments_by_name["Recursos Humanos"])
        window.update_idletasks()
        beat(5.0, "Cambia a Recursos Humanos -- turnos y colores distintos", window)

        beat(3.0, 'Texto en pantalla: "Cada turno, ausencia y cierre, en su sitio -- sin que nadie lo pise"', window)

        done()
        window.destroy()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
