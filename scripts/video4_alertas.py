"""Director del VIDEO 4 -- "El aviso que llega antes del susto".

El cierre usa una alerta REAL de la base de datos (no un dato inventado
para el video): "Rocío Hernández, certificado PRL, caduca en unos 10 días"
-- se elige por ser la más urgente entre las que aún no han vencido (el
guion original decía "5 días" a modo de ejemplo, pero es mejor un dato
real que uno inventado).
"""
from __future__ import annotations

import sqlite3
from datetime import date

from video_common import VIDEO_DB_PATH, beat, done, force_foreground, wait_for_recording

from app.backup import BackupRepository
from app.database import get_connection
from app.repository import Repositories, gather_alerts
from app.ui import MainWindow


def main() -> None:
    conn = get_connection(VIDEO_DB_PATH)
    try:
        repos = Repositories.create(conn)
        admin_user = repos.users.list_all()[0]

        alerts = gather_alerts(repos, None, date.today())
        upcoming = sorted((a for a in alerts if a.days_remaining >= 0), key=lambda a: a.days_remaining)
        featured = upcoming[0]
        print(f"Alerta destacada para el cierre: {featured.employee_name} -- {featured.detail}")

        wait_for_recording("VIDEO 4 -- El aviso que llega antes del susto")

        backups = BackupRepository(conn, VIDEO_DB_PATH) if isinstance(conn, sqlite3.Connection) else None
        window = MainWindow(repos, admin_user, backups)
        window.update_idletasks()
        force_foreground(window)
        window.update()

        window._show_page("alertas")
        window.update_idletasks()
        beat(5.0, "Bandeja de Alertas completa -- varias vencidas en rojo, el resto próximas", window)

        beat(4.0, f'Zoom / cursor sobre: "{featured.employee_name} -- {featured.detail}"', window)

        beat(4.0, 'Texto en pantalla: "Contratos, revisiones médicas, formación PRL, certificaciones -- 7 tipos, en una sola pantalla"', window)

        done()
        window.destroy()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
