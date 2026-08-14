"""Director del VIDEO 5 -- "Sin nube, sin cuota por cabeza".

Este es el único de los 5 con un paso que tienes que hacer tú a mano: yo
no puedo desconectar tu wifi (ni debo -- es justo el tipo de acción de
sistema que se queda fuera de lo que hago por mi cuenta). El script deja
la app abierta y lista; el resto -- desconectar el wifi y enseñar el
precio en la web -- se hace en directo durante la grabación.
"""
from __future__ import annotations

import sqlite3

from video_common import VIDEO_DB_PATH, beat, done, force_foreground, wait_for_recording

from app.backup import BackupRepository
from app.database import get_connection
from app.repository import Repositories
from app.ui import MainWindow


def main() -> None:
    conn = get_connection(VIDEO_DB_PATH)
    try:
        repos = Repositories.create(conn)
        admin_user = repos.users.list_all()[0]

        wait_for_recording("VIDEO 5 -- Sin nube, sin cuota por cabeza")

        backups = BackupRepository(conn, VIDEO_DB_PATH) if isinstance(conn, sqlite3.Connection) else None
        window = MainWindow(repos, admin_user, backups)
        window.update_idletasks()
        force_foreground(window)
        window.update()

        window._show_page("inicio")
        window.update_idletasks()
        beat(4.0, 'Texto en pantalla: "La mayoría de SaaS de RRHH te cobran por cada empleado que añades"', window)

        print()
        print(">>> AHORA A MANO, en directo:")
        print("    1. Desconecta el wifi (icono de la barra de tareas o el interruptor físico)")
        print("    2. Sigue navegando la app con total normalidad -- va a funcionar exactamente igual")
        print('    3. Texto en pantalla: "100% en tu ordenador. Cero nube."')
        print()
        beat(6.0, "Navega un par de páginas más con el wifi ya desconectado", window)

        print()
        print(">>> Para el cierre (ya no hace falta la app):")
        print("    4. Corta a la web -- sección de precio: 15€/mes")
        print('    5. Texto en pantalla: "15€/mes. Da igual que tengas 5 empleados o 50."')
        print('    6. Cierre: "Sin permanencia. Cancela cuando quieras."')

        done()
        window.destroy()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
