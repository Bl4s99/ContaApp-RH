"""Director del VIDEO 2 -- "Tramos oficiales, no un % inventado".

Protagonista: Laura Jimenez (25.500 EUR, 1 hijo a cargo) -- salario e
hijos a cargo reales ya cargados, para que el desglose de IRPF salga con
un mínimo personal y familiar que se note.
"""
from __future__ import annotations

import sqlite3

from video_common import HERO_EMAIL, VIDEO_DB_PATH, beat, done, force_foreground, wait_for_recording

from app.backup import BackupRepository
from app.database import get_connection
from app.repository import Repositories
from app.ui import MainWindow


def main() -> None:
    conn = get_connection(VIDEO_DB_PATH)
    try:
        repos = Repositories.create(conn)
        admin_user = repos.users.list_all()[0]
        hero = next(e for e in repos.employees.list_all() if e.email == HERO_EMAIL)

        wait_for_recording("VIDEO 2 -- Tramos oficiales, no un % inventado")

        backups = BackupRepository(conn, VIDEO_DB_PATH) if isinstance(conn, sqlite3.Connection) else None
        window = MainWindow(repos, admin_user, backups)
        window.update_idletasks()
        force_foreground(window)
        window.update()

        window._show_page("empleados")
        window._employee_page.ficha.show_employee(hero)
        window.update_idletasks()
        beat(4.0, f"Ficha de {hero.full_name} -- salario {hero.salary:,.0f} EUR, {hero.dependent_children} hijo(s) a cargo, ya rellenado", window)

        window._show_page("nominas")
        window._payroll_page.tree.selection_set(str(hero.id))
        window._payroll_page._handle_selection_changed()
        window.update_idletasks()
        beat(8.0, "Nominas -- desglose real: tramos de IRPF + minimo personal y familiar, retencion final resaltada", window)

        beat(4.0, 'Texto en pantalla: "Tramos oficiales. Sin inventar nada."', window)

        done()
        window.destroy()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
