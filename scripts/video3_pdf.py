"""Director del VIDEO 3 -- "El speedrun del contrato en PDF".

El script deja el dialogo abierto con la plantilla ya seleccionada y el
texto ya rellenado (eso es instantaneo en la app real, no hay nada que
esperar ahi). El remate -- clicar "Descargar PDF...", elegir carpeta y
nombre, y abrir el PDF resultante -- se hace a mano durante la propia
grabacion: es la parte mas satisfactoria del video y clicar 2-3 veces en
menos de 10s es perfectamente viable en directo. No tiene sentido
automatizar el dialogo nativo de "Guardar como" de Windows.
"""
from __future__ import annotations

import sqlite3

from video_common import HERO_EMAIL, VIDEO_DB_PATH, beat, done, force_foreground, wait_for_recording

from app.backup import BackupRepository
from app.database import get_connection
from app.employee_page import GenerateDocumentDialog
from app.repository import Repositories
from app.ui import MainWindow

TEMPLATE_NAME = "Oferta de trabajo"


def main() -> None:
    conn = get_connection(VIDEO_DB_PATH)
    try:
        repos = Repositories.create(conn)
        admin_user = repos.users.list_all()[0]
        hero = next(e for e in repos.employees.list_all() if e.email == HERO_EMAIL)
        templates = repos.document_templates.list_all()
        template_index = next(i for i, t in enumerate(templates) if t.name == TEMPLATE_NAME)

        wait_for_recording("VIDEO 3 -- El speedrun del contrato en PDF")

        backups = BackupRepository(conn, VIDEO_DB_PATH) if isinstance(conn, sqlite3.Connection) else None
        window = MainWindow(repos, admin_user, backups)
        window.update_idletasks()
        force_foreground(window)
        window.update()

        window._show_page("empleados")
        window._employee_page.ficha.show_employee(hero)
        window.update_idletasks()
        beat(1.5, "Ficha del empleado en pantalla", window)

        dialog = GenerateDocumentDialog(
            window, repos, hero, templates, on_change=lambda: None
        )
        dialog.template_combo.current(template_index)
        dialog._handle_render()
        force_foreground(dialog)
        dialog.update_idletasks()
        beat(4.0, f'Plantilla "{TEMPLATE_NAME}" seleccionada -- el texto se rellena solo con los datos de {hero.full_name}')

        print()
        print(">>> AHORA A MANO, en directo, sin cortar la grabacion:")
        print('    1. Clic en "Descargar PDF..."')
        print("    2. Elige una carpeta y pulsa Guardar")
        print("    3. Abre el PDF que se acaba de generar y enseñalo 2-3s")
        print("    4. Cierra el dialogo (boton Cerrar) cuando termines")
        print("    (todo esto encaja sobradamente en los ~10s que le quedan al video)")
        print()
        # wait_window() -- NO un input() de consola -- mantiene vivo el bucle
        # de eventos de Tkinter mientras esperamos, así que el diálogo sigue
        # respondiendo a clics reales. Un input() aquí bloquearía el único
        # hilo del proceso y la ventana se quedaría congelada en pantalla.
        dialog.wait_window()

        done()
        window.destroy()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
