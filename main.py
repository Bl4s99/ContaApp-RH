from __future__ import annotations

import smtplib
import sqlite3
from datetime import date, datetime
from tkinter import messagebox

from app.alerts import all_alerts, retention_review_alerts, training_expiry_alerts
from app.backup import BackupRepository, apply_pending_restore
from app.database import DEFAULT_DB_PATH, get_connection, init_db
from app.email_digest import send_digest_email
from app.login import LoginWindow
from app.repository import Repositories
from app.ui import MainWindow

DEFAULT_DAY_TYPES = [
    ("Vacaciones", "#2ecc71", True),
    ("Enfermedad", "#e67e22", False),
    ("Festivo", "#e74c3c", False),
    ("Permiso o licencia", "#9b59b6", False),
    ("Ausencia injustificada", "#c0392b", False),
]

DEFAULT_ONBOARDING_TASKS = [
    "Contrato firmado",
    "Alta en Seguridad Social",
    "Equipo entregado",
    "Accesos creados",
]


def main() -> None:
    # Debe ir antes de abrir ninguna conexión: si hay una restauración de
    # copia de seguridad pendiente (BackupRepository.stage_restore(), desde
    # la sesión anterior), este es el único momento en que sustituir
    # empleados.db es completamente seguro.
    apply_pending_restore(DEFAULT_DB_PATH)

    conn = get_connection(DEFAULT_DB_PATH)
    try:
        init_db(conn)
        repos = Repositories.create(conn)
        backups = BackupRepository(conn, DEFAULT_DB_PATH)

        if not repos.departments.list_all():
            repos.departments.create("General")
        if not repos.day_types.list_all():
            for name, color, is_vacation in DEFAULT_DAY_TYPES:
                repos.day_types.create(name, color, is_vacation)
        if not repos.onboarding_tasks.list_all():
            for name in DEFAULT_ONBOARDING_TASKS:
                repos.onboarding_tasks.create(name)
        if not repos.users.list_all():
            repos.users.create("admin", "admin")

        backup_error: str | None = None
        if not backups.has_backup_today():
            try:
                backups.create_backup()
            except (OSError, sqlite3.Error) as exc:
                # No bloquear el arranque de la app por un fallo de backup
                # (disco lleno, permisos, etc.) -- se avisa una vez la
                # ventana principal ya existe, más abajo.
                backup_error = str(exc)

        login = LoginWindow(repos)
        login.mainloop()
        if login.authenticated_user is None:
            return  # ventana de login cerrada sin iniciar sesión
        repos.audit_log.set_current_user(login.authenticated_user)
        current_user = login.authenticated_user

        digest_error: str | None = None
        assert current_user.id is not None
        if repos.users.needs_weekly_digest(current_user.id, date.today()):
            try:
                connection = repos.users.get_email_connection(current_user.id)
                assert connection is not None  # needs_weekly_digest() ya lo comprobó
                locked_department_id = (
                    current_user.department_id if current_user.role == "encargado" else None
                )
                # Sin active_only: all_alerts() ya se autolimita a activos y
                # retention_review_alerts() a inactivos (ver alerts_ui.py).
                employees = repos.employees.search(department_id=locked_department_id)
                today = date.today()
                retention_years = repos.app_settings.get_data_retention_years()
                trainings = repos.trainings.list_all()
                alerts = sorted(
                    all_alerts(employees, today)
                    + retention_review_alerts(employees, today, retention_years)
                    + training_expiry_alerts(employees, trainings, today),
                    key=lambda a: a.target_date,
                )
                send_digest_email(connection, alerts)
                repos.users.mark_digest_sent(current_user.id, datetime.now())
            except (smtplib.SMTPException, OSError) as exc:
                # Igual que el fallo de backup: no bloquea el arranque, se
                # avisa una vez exista la ventana principal, más abajo.
                digest_error = str(exc)

        window = MainWindow(repos, current_user, backups)
        if backup_error is not None:
            messagebox.showwarning(
                "Copia de seguridad",
                "No se pudo crear la copia de seguridad automática de hoy:\n"
                f"{backup_error}",
                parent=window,
            )
        if digest_error is not None:
            messagebox.showwarning(
                "Resumen semanal",
                "No se pudo enviar el resumen semanal de alertas por correo:\n"
                f"{digest_error}",
                parent=window,
            )
        window.mainloop()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
