from __future__ import annotations

import os
import sqlite3
import tkinter as tk
from collections.abc import Callable
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import quote, urlsplit

from app import theme, validation
from app.absence_requests_ui import AbsenceRequestsPage
from app.alerts_ui import AlertsPage
from app.backup import BackupInfo, BackupRepository, format_backup_size
from app.calendar_page import CalendarPage
from app.calendar_widget import ScrollableFrame, ToggleSwitch
from app.candidates_ui import CandidatesPage
from app.collective_agreement_ui import CollectiveAgreementManagerDialog
from app.cost_report_ui import CostReportPage
from app.db_engine import check_db_connection, read_configured_db_url, write_configured_db_url
from app.document_template_ui import DocumentTemplateManagerDialog
from app.employee_page import EmployeePage
from app.export import export_employees_csv
from app.models import Department, Employee, User
from app.onboarding_ui import OnboardingTaskManagerDialog
from app.org_chart_ui import OrgChartPage
from app.payroll_ui import PayrollPage
from app.repository import (
    AUDIT_BACKUP_RESTORED,
    AUDIT_DEPARTMENT_CREATED,
    AUDIT_DEPARTMENT_DELETED,
    AUDIT_USER_CREATED,
    AUDIT_USER_DELETED,
    Repositories,
    RepositoryError,
)
from app.paths import app_dir
from app.schedule_ui import DayTypeManagerDialog, HolidayTemplateManagerDialog
from app.theme import apply_theme
from app.time_clock_ui import TimeClockPage
from app.welcome_page import WelcomePage
from app.window_utils import center_window

TkParent = tk.Tk | tk.Toplevel

SIDEBAR_WIDTH = 210


class DepartmentManagerDialog(tk.Toplevel):
    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        on_change: Callable[[], None],
        on_view_calendar: Callable[[Department], None],
    ) -> None:
        super().__init__(parent)
        self.title("Departamentos")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._on_change = on_change
        self._on_view_calendar = on_view_calendar
        self._departments: list[Department] = []

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        palette = theme.current()
        self.listbox = tk.Listbox(
            frame,
            width=36,
            height=10,
            bg=palette.surface,
            fg=palette.text,
            selectbackground=palette.primary,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.primary_light,
        )
        self.listbox.grid(row=0, column=0, columnspan=2, padx=4, pady=4)

        self.new_name_var = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=self.new_name_var, width=28)
        entry.grid(row=1, column=0, padx=4, pady=4)
        entry.bind("<Return>", lambda _event: self._handle_add())
        ttk.Button(
            frame, text="Agregar", command=self._handle_add, style="Accent.TButton"
        ).grid(row=1, column=1, padx=4, pady=4)

        ttk.Button(frame, text="Eliminar seleccionado", command=self._handle_delete).grid(
            row=2, column=0, columnspan=2, pady=(4, 0)
        )
        ttk.Button(frame, text="Calendario laboral...", command=self._open_calendar).grid(
            row=3, column=0, columnspan=2, pady=(4, 0)
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=300)
        self.error_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=5, column=0, columnspan=2, pady=(8, 0)
        )

        self.bind("<Escape>", lambda _event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._refresh()

    def _refresh(self) -> None:
        self._departments = self._repos.departments.list_all()
        self.listbox.delete(0, tk.END)
        for dept in self._departments:
            self.listbox.insert(tk.END, dept.name)

    def _selected_department(self) -> Department | None:
        selection: tuple[int, ...] = self.listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            return None
        return self._departments[selection[0]]

    def _handle_add(self) -> None:
        name = self.new_name_var.get()
        try:
            created = self._repos.departments.create(name)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._repos.audit_log.record(AUDIT_DEPARTMENT_CREATED, f"Departamento: {created.name}")
        self.new_name_var.set("")
        self.error_label.configure(text="")
        self._refresh()
        self._on_change()

    def _handle_delete(self) -> None:
        dept = self._selected_department()
        if dept is None:
            self.error_label.configure(text="Seleccione un departamento para eliminar.")
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", f"¿Eliminar el departamento '{dept.name}'?", parent=self
        ):
            return
        assert dept.id is not None
        try:
            self._repos.departments.delete(dept.id)
        except RepositoryError as exc:
            self.error_label.configure(text=str(exc))
            return
        self._repos.audit_log.record(AUDIT_DEPARTMENT_DELETED, f"Departamento: {dept.name}")
        self.error_label.configure(text="")
        self._refresh()
        self._on_change()

    def _open_calendar(self) -> None:
        dept = self._selected_department()
        if dept is None:
            self.error_label.configure(
                text="Seleccione un departamento para ver su calendario."
            )
            return
        self.destroy()
        self._on_view_calendar(dept)


class UserManagerDialog(tk.Toplevel):
    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        departments: list[Department],
        current_user_id: int | None,
    ) -> None:
        super().__init__(parent)
        self.title("Gestionar usuarios")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._departments = departments
        self._current_user_id = current_user_id
        self._users: list[User] = []

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        tree_frame = ttk.Frame(frame)
        tree_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
        columns = ("usuario", "rol", "departamento")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=8, selectmode="browse"
        )
        for col, label, width in [
            ("usuario", "Usuario", 140),
            ("rol", "Rol", 90),
            ("departamento", "Departamento", 150),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        ttk.Button(
            frame, text="Eliminar seleccionado", command=self._handle_delete
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 14))

        ttk.Separator(frame, orient="horizontal").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(0, 10)
        )
        ttk.Label(frame, text="Nuevo usuario", style="PageHeading.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        ttk.Label(frame, text="Usuario").grid(row=4, column=0, sticky="w", pady=3)
        self.username_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.username_var, width=26).grid(
            row=4, column=1, sticky="w", pady=3
        )

        ttk.Label(frame, text="Contraseña").grid(row=5, column=0, sticky="w", pady=3)
        self.password_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.password_var, show="•", width=26).grid(
            row=5, column=1, sticky="w", pady=3
        )

        ttk.Label(frame, text="Rol").grid(row=6, column=0, sticky="w", pady=3)
        self.role_var = tk.StringVar(value="encargado")
        role_combo = ttk.Combobox(
            frame,
            state="readonly",
            width=23,
            textvariable=self.role_var,
            values=list(validation.USER_ROLES),
        )
        role_combo.grid(row=6, column=1, sticky="w", pady=3)
        role_combo.bind("<<ComboboxSelected>>", lambda _e: self._handle_role_changed())

        ttk.Label(frame, text="Departamento").grid(row=7, column=0, sticky="w", pady=3)
        self.department_combo = ttk.Combobox(
            frame, state="readonly", width=23, values=[d.name for d in departments]
        )
        self.department_combo.grid(row=7, column=1, sticky="w", pady=3)

        ttk.Button(
            frame, text="Crear usuario", command=self._handle_create, style="Accent.TButton"
        ).grid(row=8, column=0, columnspan=2, pady=(10, 0))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=10, column=0, columnspan=2, pady=(10, 0)
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._handle_role_changed()
        self._refresh()

    def _refresh(self) -> None:
        self._users = self._repos.users.list_all()
        self.tree.delete(*self.tree.get_children())
        departments_by_id = {d.id: d for d in self._departments if d.id is not None}
        for user in self._users:
            assert user.id is not None
            dept = departments_by_id.get(user.department_id) if user.department_id else None
            self.tree.insert(
                "",
                tk.END,
                iid=str(user.id),
                values=(user.username, user.role, dept.name if dept else ""),
            )

    def _handle_role_changed(self) -> None:
        if self.role_var.get() == "admin":
            self.department_combo.set("")
            self.department_combo.configure(state="disabled")
        else:
            self.department_combo.configure(state="readonly")

    def _selected_new_user_department_id(self) -> int | None:
        idx = self.department_combo.current()
        if idx == -1:
            return None
        return self._departments[idx].id

    def _handle_create(self) -> None:
        try:
            created = self._repos.users.create(
                self.username_var.get(),
                self.password_var.get(),
                role=self.role_var.get(),
                department_id=self._selected_new_user_department_id(),
            )
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._repos.audit_log.record(
            AUDIT_USER_CREATED, f"Usuario: {created.username} (rol: {created.role})"
        )
        self.username_var.set("")
        self.password_var.set("")
        self.error_label.configure(text="")
        self._refresh()

    def _handle_delete(self) -> None:
        selection = self.tree.selection()
        if not selection:
            self.error_label.configure(text="Seleccione un usuario para eliminar.")
            return
        user_id = int(selection[0])
        if user_id == self._current_user_id:
            self.error_label.configure(text="No puede eliminar el usuario con el que ha iniciado sesión.")
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", "¿Eliminar este usuario?", parent=self
        ):
            return
        target = next((u for u in self._users if u.id == user_id), None)
        try:
            self._repos.users.delete(user_id, current_user_id=self._current_user_id)
        except RepositoryError as exc:
            self.error_label.configure(text=str(exc))
            return
        self._repos.audit_log.record(
            AUDIT_USER_DELETED, f"Usuario: {target.username if target else user_id}"
        )
        self.error_label.configure(text="")
        self._refresh()


class AccountSettingsDialog(tk.Toplevel):
    """Autoservicio sobre la PROPIA cuenta de quien ha iniciado sesión:
    cambiar su contraseña y conectar/desconectar su correo para el resumen
    semanal de alertas -- distinto de UserManagerDialog (solo admin,
    gestiona altas/bajas de OTRAS cuentas, sin acceso a la contraseña
    actual de nadie ni a estos campos)."""

    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        current_user: User,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Mi cuenta")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._user = current_user
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text=f"Usuario: {current_user.username}", style="PageHeading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )

        ttk.Label(frame, text="Cambiar contraseña", style="PageHeading.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        ttk.Label(frame, text="Contraseña actual").grid(row=2, column=0, sticky="w", pady=3)
        self.current_password_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.current_password_var, show="•", width=26).grid(
            row=2, column=1, sticky="w", pady=3
        )
        ttk.Label(frame, text="Contraseña nueva").grid(row=3, column=0, sticky="w", pady=3)
        self.new_password_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.new_password_var, show="•", width=26).grid(
            row=3, column=1, sticky="w", pady=3
        )
        ttk.Label(frame, text="Confirmar contraseña").grid(row=4, column=0, sticky="w", pady=3)
        self.confirm_password_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.confirm_password_var, show="•", width=26).grid(
            row=4, column=1, sticky="w", pady=3
        )
        ttk.Button(
            frame, text="Guardar contraseña", command=self._handle_change_password
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.password_error_label = ttk.Label(
            frame, text="", style="Error.TLabel", wraplength=320
        )
        self.password_error_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Separator(frame, orient="horizontal").grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=12
        )

        ttk.Label(
            frame, text="Correo para el resumen semanal", style="PageHeading.TLabel"
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.email_status_label = ttk.Label(frame, text="", style="Muted.TLabel", wraplength=320)
        self.email_status_label.grid(row=9, column=0, columnspan=2, sticky="w", pady=(0, 6))

        ttk.Label(frame, text="Proveedor").grid(row=10, column=0, sticky="w", pady=3)
        self.provider_combo = ttk.Combobox(
            frame, state="readonly", width=23, values=list(validation.EMAIL_PROVIDERS)
        )
        self.provider_combo.current(0)
        self.provider_combo.grid(row=10, column=1, sticky="w", pady=3)

        ttk.Label(frame, text="Correo").grid(row=11, column=0, sticky="w", pady=3)
        self.email_address_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.email_address_var, width=26).grid(
            row=11, column=1, sticky="w", pady=3
        )

        ttk.Label(frame, text="Contraseña de aplicación").grid(row=12, column=0, sticky="w", pady=3)
        self.app_password_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.app_password_var, show="•", width=26).grid(
            row=12, column=1, sticky="w", pady=3
        )

        ttk.Label(
            frame,
            text=(
                "Gmail: genera una \"contraseña de aplicación\" en la configuración de "
                "seguridad de tu cuenta de Google (necesita verificación en dos pasos "
                "activada) — no uses tu contraseña normal. Outlook: puede usarse la "
                "contraseña normal de la cuenta. Se guarda en la base de datos local de "
                "la aplicación, con el mismo nivel de protección que el resto de datos "
                "sensibles ya guardados ahí (IBAN, DNI/NIE) — no es una integración "
                "OAuth, y no sale de este equipo salvo para enviar el propio resumen."
            ),
            style="Muted.TLabel",
            wraplength=340,
        ).grid(row=13, column=0, columnspan=2, sticky="w", pady=(4, 6))

        button_row = ttk.Frame(frame)
        button_row.grid(row=14, column=0, columnspan=2, sticky="w")
        ttk.Button(
            button_row, text="Conectar", command=self._handle_connect_email
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            button_row, text="Desconectar", command=self._handle_disconnect_email
        ).pack(side="left")
        self.email_error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.email_error_label.grid(row=15, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Separator(frame, orient="horizontal").grid(
            row=16, column=0, columnspan=2, sticky="ew", pady=12
        )

        ttk.Label(
            frame, text="Avisos si la aplicación falla", style="PageHeading.TLabel"
        ).grid(row=17, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self.crash_reports_var = tk.BooleanVar(value=self._user.receive_crash_reports)
        self.crash_reports_check = ttk.Checkbutton(
            frame,
            text="Avisarme por correo si la aplicación falla en este ordenador",
            variable=self.crash_reports_var,
            command=self._handle_toggle_crash_reports,
        )
        self.crash_reports_check.grid(row=18, column=0, columnspan=2, sticky="w")
        self.crash_reports_error_label = ttk.Label(
            frame, text="", style="Error.TLabel", wraplength=320
        )
        self.crash_reports_error_label.grid(row=19, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(
            frame,
            text=(
                "Usa el correo conectado arriba, así que hace falta conectarlo primero. "
                "El aviso solo dice que hubo un fallo y de qué tipo — el detalle completo "
                "se queda en el registro local de este ordenador (carpeta \"logs\"), "
                "nunca en el correo."
            ),
            style="Muted.TLabel",
            wraplength=340,
        ).grid(row=20, column=0, columnspan=2, sticky="w", pady=(4, 6))

        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=21, column=0, columnspan=2, pady=(12, 0)
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._refresh_email_status()

    def _refresh_email_status(self) -> None:
        assert self._user.id is not None
        self._user = self._repos.users.get(self._user.id)
        if self._user.email_address is not None:
            self.email_status_label.configure(
                text=f"Conectado: {self._user.email_address} ({self._user.email_provider})"
            )
        else:
            self.email_status_label.configure(text="No conectado — no se envía resumen semanal.")
        self.crash_reports_var.set(self._user.receive_crash_reports)
        self.crash_reports_check.configure(
            state="normal" if self._user.email_address is not None else "disabled"
        )

    def _handle_toggle_crash_reports(self) -> None:
        assert self._user.id is not None
        try:
            self._repos.users.set_receive_crash_reports(
                self._user.id, self.crash_reports_var.get()
            )
        except RepositoryError as exc:
            self.crash_reports_error_label.configure(text=str(exc))
            self.crash_reports_var.set(not self.crash_reports_var.get())
            return
        self.crash_reports_error_label.configure(text="")
        self._refresh_email_status()

    def _handle_change_password(self) -> None:
        assert self._user.id is not None
        if self.new_password_var.get() != self.confirm_password_var.get():
            self.password_error_label.configure(text="Las contraseñas nuevas no coinciden.")
            return
        try:
            self._repos.users.change_own_password(
                self._user.id, self.current_password_var.get(), self.new_password_var.get()
            )
        except (validation.ValidationError, RepositoryError) as exc:
            self.password_error_label.configure(text=str(exc))
            return
        self.current_password_var.set("")
        self.new_password_var.set("")
        self.confirm_password_var.set("")
        self.password_error_label.configure(text="")
        messagebox.showinfo("Mi cuenta", "Contraseña actualizada correctamente.", parent=self)

    def _handle_connect_email(self) -> None:
        assert self._user.id is not None
        try:
            self._repos.users.set_email_connection(
                self._user.id,
                self.provider_combo.get(),
                self.email_address_var.get(),
                self.app_password_var.get(),
            )
        except (validation.ValidationError, RepositoryError) as exc:
            self.email_error_label.configure(text=str(exc))
            return
        self.app_password_var.set("")
        self.email_error_label.configure(text="")
        self._refresh_email_status()
        self._on_change()

    def _handle_disconnect_email(self) -> None:
        assert self._user.id is not None
        self._repos.users.clear_email_connection(self._user.id)
        self.email_error_label.configure(text="")
        self._refresh_email_status()
        self._on_change()


class BackupManagerDialog(tk.Toplevel):
    def __init__(self, parent: TkParent, repos: Repositories, backups: BackupRepository) -> None:
        super().__init__(parent)
        self.title("Copias de seguridad")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._backups = backups
        self._rows: list[BackupInfo] = []

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text=(
                "Se crea una copia automática al abrir la aplicación, una vez al día.\n"
                "Se conservan las últimas 30 copias."
            ),
            style="Muted.TLabel",
            wraplength=420,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        tree_frame = ttk.Frame(frame)
        tree_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
        columns = ("fecha", "tamano")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=10, selectmode="browse"
        )
        self.tree.heading("fecha", text="Fecha")
        self.tree.column("fecha", width=170, anchor="w")
        self.tree.heading("tamano", text="Tamaño")
        self.tree.column("tamano", width=90, anchor="e")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        button_row = ttk.Frame(frame)
        button_row.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(
            button_row,
            text="Crear copia ahora",
            command=self._handle_create,
            style="Accent.TButton",
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            button_row, text="Restaurar seleccionada...", command=self._handle_restore
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Abrir carpeta", command=self._handle_open_folder).pack(
            side="left", padx=4
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=420)
        self.error_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=4, column=0, columnspan=2, pady=(10, 0)
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._refresh()

    def _refresh(self) -> None:
        self._rows = self._backups.list_backups()
        self.tree.delete(*self.tree.get_children())
        for index, backup in enumerate(self._rows):
            self.tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    backup.created_at.strftime("%d/%m/%Y %H:%M:%S"),
                    format_backup_size(backup.size_bytes),
                ),
            )

    def _selected_backup(self) -> BackupInfo | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self._rows[int(selection[0])]

    def _handle_create(self) -> None:
        try:
            self._backups.create_backup()
        except (OSError, sqlite3.Error) as exc:
            # Igual que main.py al crear la copia automática al arrancar:
            # Connection.backup() puede lanzar sqlite3.OperationalError
            # (BD bloqueada, error de E/S de SQLite), no solo OSError --
            # antes se dejaba sin capturar aquí, y el usuario se quedaba
            # sin ningún mensaje pensando que "no pasó nada".
            self.error_label.configure(text=f"No se pudo crear la copia: {exc}")
            return
        self.error_label.configure(text="")
        self._refresh()

    def _handle_restore(self) -> None:
        backup = self._selected_backup()
        if backup is None:
            self.error_label.configure(text="Seleccione una copia de seguridad para restaurar.")
            return
        fecha = backup.created_at.strftime("%d/%m/%Y %H:%M:%S")
        if not messagebox.askyesno(
            "Restaurar copia de seguridad",
            f"Se reemplazarán TODOS los datos actuales (empleados, nóminas, calendario...) "
            f"por los de la copia del {fecha}.\n\n"
            "Se guardará antes una copia del estado actual, por si esta no era la copia "
            "correcta.\n\n"
            "La aplicación se cerrará para completar la restauración -- vuelve a abrirla "
            "después. ¿Continuar?",
            icon="warning",
            parent=self,
        ):
            return
        try:
            self._backups.stage_restore(backup.path)
        except (OSError, sqlite3.Error) as exc:
            self.error_label.configure(text=f"No se pudo preparar la restauración: {exc}")
            return
        # Se registra ANTES de cerrar la app (la propia restauración solo se
        # aplicará en el siguiente arranque) -- así queda constancia de que
        # se pidió, no de que ya se completó, que es lo que de verdad pasó
        # en este momento.
        self._repos.audit_log.record(AUDIT_BACKUP_RESTORED, f"Copia del {fecha}")
        messagebox.showinfo(
            "Restaurar copia de seguridad",
            "Restauración preparada. La aplicación se va a cerrar -- ábrela de nuevo para "
            "completarla.",
            parent=self,
        )
        self.master.destroy()

    def _handle_open_folder(self) -> None:
        self._backups.backups_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(self._backups.backups_dir)


class DatabaseSettingsDialog(tk.Toplevel):
    """Elegir SQLite local (por defecto) o un PostgreSQL propio sin tocar
    ninguna variable de entorno de Windows a mano -- ver
    app/db_engine.py:read_configured_db_url/write_configured_db_url. Solo
    escribe el fichero de configuración; get_connection() se llama una
    única vez al arrancar main.py y los repositorios guardan una referencia
    directa a esa conexión, así que el cambio no tiene efecto hasta
    reiniciar la aplicación -- este diálogo no intenta reconectar en
    caliente ni reiniciar el proceso él mismo."""

    def __init__(self, parent: TkParent, repos: Repositories) -> None:
        super().__init__(parent)
        self.title("Base de datos")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._tested_ok = False

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Base de datos", style="PageHeading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        ttk.Label(
            frame, text=self._describe_current_source(), style="Muted.TLabel", wraplength=380
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        configured = read_configured_db_url(app_dir())
        self.mode_var = tk.StringVar(value="postgres" if configured else "local")
        ttk.Radiobutton(
            frame,
            text="Local (SQLite), en este equipo",
            variable=self.mode_var,
            value="local",
            command=self._handle_mode_change,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Radiobutton(
            frame,
            text="Servidor PostgreSQL propio",
            variable=self.mode_var,
            value="postgres",
            command=self._handle_mode_change,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=2)

        self.postgres_frame = ttk.Frame(frame)
        self.postgres_frame.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0), padx=(20, 0))
        ttk.Label(self.postgres_frame, text="Host").grid(row=0, column=0, sticky="w", pady=2)
        self.host_var = tk.StringVar()
        ttk.Entry(self.postgres_frame, textvariable=self.host_var, width=28).grid(
            row=0, column=1, sticky="w", pady=2, padx=(8, 0)
        )
        ttk.Label(self.postgres_frame, text="Puerto").grid(row=1, column=0, sticky="w", pady=2)
        self.port_var = tk.StringVar(value="5432")
        ttk.Entry(self.postgres_frame, textvariable=self.port_var, width=28).grid(
            row=1, column=1, sticky="w", pady=2, padx=(8, 0)
        )
        ttk.Label(self.postgres_frame, text="Nombre de la base de datos").grid(
            row=2, column=0, sticky="w", pady=2
        )
        self.dbname_var = tk.StringVar()
        ttk.Entry(self.postgres_frame, textvariable=self.dbname_var, width=28).grid(
            row=2, column=1, sticky="w", pady=2, padx=(8, 0)
        )
        ttk.Label(self.postgres_frame, text="Usuario").grid(row=3, column=0, sticky="w", pady=2)
        self.pg_username_var = tk.StringVar()
        ttk.Entry(self.postgres_frame, textvariable=self.pg_username_var, width=28).grid(
            row=3, column=1, sticky="w", pady=2, padx=(8, 0)
        )
        ttk.Label(self.postgres_frame, text="Contraseña").grid(row=4, column=0, sticky="w", pady=2)
        self.pg_password_var = tk.StringVar()
        ttk.Entry(
            self.postgres_frame, textvariable=self.pg_password_var, show="•", width=28
        ).grid(row=4, column=1, sticky="w", pady=2, padx=(8, 0))
        ttk.Button(
            self.postgres_frame, text="Probar conexión", command=self._handle_test_connection
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.test_result_label = ttk.Label(frame, text="", style="Muted.TLabel", wraplength=380)
        self.test_result_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=380)
        self.error_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # Un test exitoso solo es válido para la URL exacta que se probó --
        # si se edita cualquier campo después (p. ej. se corrige la
        # contraseña), _tested_ok debe volver a False para no guardar como
        # "probada" una URL que en realidad nunca se llegó a probar.
        for pg_var in (
            self.host_var,
            self.port_var,
            self.dbname_var,
            self.pg_username_var,
            self.pg_password_var,
        ):
            pg_var.trace_add("write", lambda *_a: self._reset_test_state())

        button_row = ttk.Frame(frame)
        button_row.grid(row=7, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=(0, 6))
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left")

        self._handle_mode_change()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _describe_current_source(self) -> str:
        configured = read_configured_db_url(app_dir())
        if not configured:
            return "Origen actual: local (SQLite), en este equipo."
        try:
            parts = urlsplit(configured)
            return f"Origen actual: servidor PostgreSQL en {parts.hostname} / {parts.path.lstrip('/')}."
        except ValueError:
            return "Origen actual: servidor PostgreSQL configurado."

    def _reset_test_state(self) -> None:
        self.test_result_label.configure(text="")
        self.error_label.configure(text="")
        self._tested_ok = False

    def _handle_mode_change(self) -> None:
        self._reset_test_state()
        if self.mode_var.get() == "postgres":
            self.postgres_frame.grid()
        else:
            self.postgres_frame.grid_remove()

    def _build_postgres_url(self) -> str:
        host = self.host_var.get().strip()
        port = self.port_var.get().strip()
        dbname = self.dbname_var.get().strip()
        username = self.pg_username_var.get().strip()
        password = self.pg_password_var.get()
        if not host or not port or not dbname or not username or not password:
            raise ValueError("Rellena todos los campos del servidor PostgreSQL.")
        if not port.isdigit():
            raise ValueError("El puerto debe ser un número.")
        return (
            f"postgresql://{quote(username, safe='')}:{quote(password, safe='')}"
            f"@{host}:{port}/{dbname}"
        )

    def _handle_test_connection(self) -> None:
        self._reset_test_state()
        try:
            url = self._build_postgres_url()
            check_db_connection(url)
        except ValueError as exc:
            self.error_label.configure(text=str(exc))
            return
        except Exception as exc:
            self.error_label.configure(text=f"No se pudo conectar: {exc}")
            return
        self._tested_ok = True
        self.test_result_label.configure(text="Conexión correcta.")

    def _handle_save(self) -> None:
        self.error_label.configure(text="")
        if self.mode_var.get() == "local":
            write_configured_db_url(app_dir(), "")
        else:
            try:
                url = self._build_postgres_url()
            except ValueError as exc:
                self.error_label.configure(text=str(exc))
                return
            if not self._tested_ok:
                if not messagebox.askyesno(
                    "Base de datos",
                    "No se ha probado la conexión con éxito. ¿Guardar de todas formas? "
                    "Si los datos son incorrectos, la aplicación no podrá arrancar la "
                    "próxima vez.",
                    parent=self,
                ):
                    return
            write_configured_db_url(app_dir(), url)
        messagebox.showinfo(
            "Base de datos",
            "Ajuste guardado. Reinicia la aplicación para que el cambio tenga efecto.",
            parent=self,
        )
        self.destroy()


_AUDIT_ACTION_LABELS = {
    "login_success": "Inicio de sesión correcto",
    "login_failure": "Inicio de sesión fallido",
    "user_created": "Usuario creado",
    "user_deleted": "Usuario eliminado",
    "department_created": "Departamento creado",
    "department_deleted": "Departamento eliminado",
    "employee_created": "Empleado creado",
    "employee_deleted": "Empleado eliminado",
    "employee_terminated": "Empleado dado de baja",
    "employee_reactivated": "Empleado reactivado",
    "document_deleted": "Documento eliminado",
    "absence_approved": "Ausencia aprobada",
    "absence_rejected": "Ausencia rechazada",
    "backup_restored": "Copia de seguridad restaurada",
    "employee_anonymized": "Datos de empleado anonimizados (RGPD)",
    "data_exported": "Datos de empleado exportados (RGPD)",
}


class AuditLogDialog(tk.Toplevel):
    """Solo lectura -- a propósito no hay forma de editar ni borrar entradas
    desde aquí, sería contradictorio con el propio sentido de un registro
    de auditoría (que nadie, ni siquiera un admin, pueda borrar el rastro
    de lo que hizo)."""

    def __init__(self, parent: TkParent, repos: Repositories) -> None:
        super().__init__(parent)
        self.title("Registro de auditoría")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text="Últimas 500 acciones administrativas o sensibles, más recientes primero.",
            style="Muted.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        tree_frame = ttk.Frame(frame)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        columns = ("fecha", "usuario", "accion", "detalles")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=16, selectmode="browse"
        )
        for col, label, width in [
            ("fecha", "Fecha", 130),
            ("usuario", "Usuario", 110),
            ("accion", "Acción", 170),
            ("detalles", "Detalles", 260),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

        ttk.Button(frame, text="Actualizar", command=self._refresh).grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=3, column=0, pady=(10, 0)
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._refresh()

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for entry in self._repos.audit_log.list_all():
            self.tree.insert(
                "",
                tk.END,
                values=(
                    entry.occurred_at.strftime("%d/%m/%Y %H:%M:%S"),
                    entry.username,
                    _AUDIT_ACTION_LABELS.get(entry.action, entry.action),
                    entry.details,
                ),
            )


class MainWindow(tk.Tk):
    def __init__(
        self, repos: Repositories, current_user: User, backups: BackupRepository | None
    ) -> None:
        # backups es None cuando la conexión activa es PostgreSQL: la API de
        # copia en caliente que usa BackupRepository es propia de sqlite3,
        # sin equivalente directo aquí -- una empresa con su propio
        # PostgreSQL ya tiene su propia estrategia de copias (la de su
        # proveedor cloud, pg_dump, etc.), así que en vez de fingir que
        # funciona, "Copias de seguridad..." se deshabilita en la barra
        # lateral (ver _build_sidebar) en ese caso.
        super().__init__()
        self._repos = repos
        self._current_user = current_user
        self._backups = backups
        self._is_admin = current_user.role == "admin"
        self._locked_department_id = (
            current_user.department_id if current_user.role == "encargado" else None
        )
        apply_theme(self, repos.app_settings.get_theme_mode())
        self.title("ContaApp RH")
        self.geometry("1200x680")
        self.minsize(1000, 580)

        self._departments: list[Department] = []

        self._build_layout()
        self._reload_departments()
        self._show_page("inicio")
        # Centrar AL FINAL, no antes de _build_layout(): center_window()
        # llama a update_idletasks(), que mapea la ventana en pantalla --
        # hacerlo antes de construir la barra lateral y las 10 páginas
        # (varias con sus propias consultas a BD en su __init__) dejaba una
        # ventana vacía visible durante toda esa construcción, como un
        # parpadeo negro al arrancar. LoginWindow ya centra al final por el
        # mismo motivo.
        center_window(self)

    def _build_layout(self) -> None:
        # Panedwindow (no pack de ancho fijo) para que el usuario pueda
        # arrastrar el separador entre la barra lateral y el contenido.
        self._main_paned = ttk.Panedwindow(self, orient="horizontal")
        self._main_paned.pack(fill="both", expand=True)

        self._sidebar = ttk.Frame(
            self._main_paned, padding=(0, 16), width=SIDEBAR_WIDTH, style="Sidebar.TFrame"
        )
        self._main_paned.add(self._sidebar, weight=0)
        self._sidebar.pack_propagate(False)

        # Scroll vertical: en una ventana no maximizada la barra lateral
        # puede tener más botones de los que caben en alto -- sin esto,
        # los últimos (Modo oscuro, Exportar CSV, Salir) quedarían fuera de
        # la vista y sin forma de alcanzarlos.
        self._sidebar_scroll = ScrollableFrame(self._sidebar, bg=theme.current().primary_dark)
        self._sidebar_scroll.pack(fill="both", expand=True)

        container = ttk.Frame(self._main_paned)
        self._main_paned.add(container, weight=1)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self._employee_page = EmployeePage(
            container,
            self._repos,
            on_view_calendar=self._show_employee_calendar,
            locked_department_id=self._locked_department_id,
            is_admin=self._is_admin,
        )
        self._payroll_page = PayrollPage(
            container,
            self._repos,
            locked_department_id=self._locked_department_id,
            is_admin=self._is_admin,
        )
        self._cost_report_page = CostReportPage(
            container, self._repos, locked_department_id=self._locked_department_id
        )
        self._candidates_page = CandidatesPage(
            container, self._repos, locked_department_id=self._locked_department_id
        )
        self._org_chart_page = OrgChartPage(
            container, self._repos, locked_department_id=self._locked_department_id
        )
        self._calendar_page = CalendarPage(container, self._repos)
        self._time_clock_page = TimeClockPage(
            container, self._repos, locked_department_id=self._locked_department_id
        )
        self._absence_requests_page = AbsenceRequestsPage(
            container, self._repos, locked_department_id=self._locked_department_id
        )
        self._alerts_page = AlertsPage(
            container, self._repos, locked_department_id=self._locked_department_id
        )
        self._welcome_page = WelcomePage(
            container,
            self._repos,
            on_go_employees=lambda: self._show_page("empleados"),
            on_go_payroll=lambda: self._show_page("nominas"),
            on_go_departments=self._open_department_manager,
            on_export=self._handle_export,
            is_admin=self._is_admin,
            locked_department_id=self._locked_department_id,
        )
        self._pages: dict[str, ttk.Frame] = {
            "inicio": self._welcome_page,
            "empleados": self._employee_page,
            "nominas": self._payroll_page,
            "coste": self._cost_report_page,
            "candidatos": self._candidates_page,
            "organigrama": self._org_chart_page,
            "calendario": self._calendar_page,
            "fichajes": self._time_clock_page,
            "solicitudes": self._absence_requests_page,
            "alertas": self._alerts_page,
        }
        # No se grid()-ean aquí todas a la vez: _show_page() se encarga de
        # gestionar con grid()/grid_remove() solo la página activa (ver el
        # comentario allí sobre por qué).

        self._build_sidebar()

    def _build_sidebar(self) -> None:
        sidebar = self._sidebar_scroll.inner
        ttk.Label(
            sidebar,
            text="ContaApp\nRH",
            style="SidebarTitle.TLabel",
            justify="center",
        ).pack(pady=(0, 16))

        ttk.Button(
            sidebar, text="Inicio", command=self._go_inicio, style="Sidebar.TButton"
        ).pack(fill="x", padx=10, pady=(0, 2))
        ttk.Button(
            sidebar, text="Alertas", command=self._go_alerts, style="Sidebar.TButton"
        ).pack(fill="x", padx=10, pady=2)
        ttk.Button(
            sidebar,
            text="Mi cuenta...",
            command=self._open_account_settings,
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=2)

        ttk.Separator(sidebar, orient="horizontal", style="Sidebar.TSeparator").pack(
            fill="x", padx=10, pady=16
        )

        ttk.Label(sidebar, text="EMPLEADOS", style="SidebarSection.TLabel").pack(
            anchor="w", padx=10
        )
        ttk.Button(
            sidebar,
            text="Lista de empleados",
            command=lambda: self._show_page("empleados"),
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=(4, 2))
        ttk.Button(
            sidebar,
            text="Nóminas",
            command=lambda: self._show_page("nominas"),
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=2)
        ttk.Button(
            sidebar,
            text="Coste de personal",
            command=self._go_cost_report,
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=2)
        ttk.Button(
            sidebar,
            text="Organigrama",
            command=self._go_org_chart,
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=2)

        ttk.Separator(sidebar, orient="horizontal", style="Sidebar.TSeparator").pack(
            fill="x", padx=10, pady=16
        )

        ttk.Label(sidebar, text="SELECCIÓN Y ALTA", style="SidebarSection.TLabel").pack(
            anchor="w", padx=10
        )
        ttk.Button(
            sidebar,
            text="Candidatos",
            command=self._go_candidates,
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=(4, 2))
        ttk.Button(
            sidebar,
            text="Plantillas de documentos...",
            command=self._open_document_template_manager,
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=2)
        ttk.Button(
            sidebar,
            text="Tareas de incorporación...",
            command=self._open_onboarding_task_manager,
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=2)

        if self._is_admin:
            ttk.Separator(sidebar, orient="horizontal", style="Sidebar.TSeparator").pack(
                fill="x", padx=10, pady=16
            )
            ttk.Label(sidebar, text="ADMINISTRACIÓN", style="SidebarSection.TLabel").pack(
                anchor="w", padx=10
            )
            ttk.Button(
                sidebar,
                text="Departamentos",
                command=self._open_department_manager,
                style="Sidebar.TButton",
            ).pack(fill="x", padx=10, pady=(4, 2))
            ttk.Button(
                sidebar,
                text="Gestionar usuarios...",
                command=self._open_user_manager,
                style="Sidebar.TButton",
            ).pack(fill="x", padx=10, pady=2)
            ttk.Button(
                sidebar,
                text="Convenios...",
                command=self._open_collective_agreement_manager,
                style="Sidebar.TButton",
            ).pack(fill="x", padx=10, pady=2)
            backup_button = ttk.Button(
                sidebar,
                text="Copias de seguridad...",
                command=self._open_backup_manager,
                style="Sidebar.TButton",
            )
            backup_button.pack(fill="x", padx=10, pady=2)
            if self._backups is None:
                backup_button.state(["disabled"])
            ttk.Button(
                sidebar,
                text="Base de datos...",
                command=self._open_database_settings,
                style="Sidebar.TButton",
            ).pack(fill="x", padx=10, pady=2)
            ttk.Button(
                sidebar,
                text="Registro de auditoría...",
                command=self._open_audit_log,
                style="Sidebar.TButton",
            ).pack(fill="x", padx=10, pady=2)

        ttk.Separator(sidebar, orient="horizontal", style="Sidebar.TSeparator").pack(
            fill="x", padx=10, pady=16
        )

        ttk.Label(sidebar, text="CALENDARIO", style="SidebarSection.TLabel").pack(
            anchor="w", padx=10
        )
        ttk.Label(
            sidebar,
            text="Calendario laboral",
            style="SidebarMuted.TLabel",
            padding=(0, 6, 0, 2),
        ).pack(anchor="w", padx=10)
        self._calendar_buttons_frame = ttk.Frame(sidebar, style="Sidebar.TFrame")
        self._calendar_buttons_frame.pack(fill="x")
        ttk.Button(
            sidebar,
            text="Fichajes",
            command=lambda: self._show_page("fichajes"),
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=(6, 2))
        ttk.Button(
            sidebar,
            text="Solicitudes de ausencia",
            command=self._go_absence_requests,
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=2)
        ttk.Button(
            sidebar,
            text="Tipos de día",
            command=self._open_day_type_manager,
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=2)
        ttk.Button(
            sidebar,
            text="Festivos...",
            command=self._open_holiday_template_manager,
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=2)

        ttk.Separator(sidebar, orient="horizontal", style="Sidebar.TSeparator").pack(
            fill="x", padx=10, pady=16
        )

        theme_row = ttk.Frame(sidebar, style="Sidebar.TFrame")
        theme_row.pack(fill="x", padx=10, pady=(2, 8))
        ttk.Label(theme_row, text="Modo oscuro", style="SidebarMuted.TLabel").pack(side="left")
        palette = theme.current()
        self._theme_toggle = ToggleSwitch(
            theme_row,
            initial=(theme.current_mode() == "dark"),
            on_toggle=self._handle_theme_toggle,
            bg=palette.primary_dark,
            on_color=palette.primary_light,
            off_color=palette.text_on_dark_muted,
        )
        self._theme_toggle.pack(side="right")
        ttk.Button(
            sidebar,
            text="Exportar CSV...",
            command=self._handle_export,
            style="Sidebar.TButton",
        ).pack(fill="x", padx=10, pady=2)
        ttk.Button(sidebar, text="Salir", command=self.destroy, style="Sidebar.TButton").pack(
            fill="x", padx=10, pady=2
        )

    def _show_page(self, name: str) -> None:
        # grid()/grid_remove() en vez de solo tkraise(): tkraise() cambia el
        # orden de apilado pero deja las 10 páginas gestionadas por grid a
        # la vez, así que cada resize de la ventana recalculaba la geometría
        # de las 10 (Treeviews, canvases, formularios) en vez de solo la
        # visible -- causa de parte del parpadeo/lentitud al redimensionar.
        # grid_remove() saca a una página de la gestión de geometría por
        # completo (conserva sus opciones para volver a grid() sin
        # reconfigurar nada) y es un no-op seguro sobre una página que
        # todavía no se había mostrado nunca.
        for key, page in self._pages.items():
            if key == name:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_remove()

    def _go_inicio(self) -> None:
        self._welcome_page.refresh()
        self._show_page("inicio")

    def _go_absence_requests(self) -> None:
        self._absence_requests_page.refresh()
        self._show_page("solicitudes")

    def _go_alerts(self) -> None:
        self._alerts_page.refresh()
        self._show_page("alertas")

    def _go_cost_report(self) -> None:
        self._cost_report_page.refresh()
        self._show_page("coste")

    def _go_candidates(self) -> None:
        self._candidates_page.refresh()
        self._show_page("candidatos")

    def _go_org_chart(self) -> None:
        self._org_chart_page.refresh()
        self._show_page("organigrama")

    def _handle_theme_toggle(self, is_dark: bool) -> None:
        new_mode = "dark" if is_dark else "light"
        self._repos.app_settings.set_theme_mode(new_mode)
        apply_theme(self, new_mode)
        # apply_theme() reconfigura los estilos ttk con nombre, y eso repinta
        # solo cualquier widget que los use -- pero unos pocos widgets fijan
        # su color directamente (el lienzo de la rejilla del calendario, el
        # aviso de Nóminas, el propio interruptor), así que hay que
        # avisarles explícitamente.
        self._calendar_page.apply_theme_change()
        self._payroll_page.apply_theme_change()
        self._alerts_page.apply_theme_change()
        self._employee_page.apply_theme_change()
        palette = theme.current()
        self._theme_toggle.set_colors(
            bg=palette.primary_dark,
            on_color=palette.primary_light,
            off_color=palette.text_on_dark_muted,
        )
        self._sidebar_scroll.set_bg(palette.primary_dark)

    def _visible_departments(self) -> list[Department]:
        if self._locked_department_id is None:
            return self._departments
        return [d for d in self._departments if d.id == self._locked_department_id]

    def _rebuild_calendar_sidebar(self) -> None:
        for widget in self._calendar_buttons_frame.winfo_children():
            widget.destroy()
        visible = self._visible_departments()
        if not visible:
            ttk.Label(
                self._calendar_buttons_frame,
                text="(sin departamentos)",
                style="SidebarMuted.TLabel",
                padding=(10, 0),
            ).pack(fill="x")
            return
        for dept in visible:
            ttk.Button(
                self._calendar_buttons_frame,
                text=dept.name,
                command=partial(self._show_department_calendar, dept),
                style="Sidebar.TButton",
            ).pack(fill="x", padx=10, pady=1)

    def _show_department_calendar(self, department: Department) -> None:
        self._calendar_page.show_department(department)
        self._show_page("calendario")

    def _show_employee_calendar(self, employee: Employee) -> None:
        self._calendar_page.show_employee(employee)
        self._show_page("calendario")

    def _open_day_type_manager(self) -> None:
        DayTypeManagerDialog(
            self, self._repos.day_types, on_change=self._employee_page.refresh_employees
        )

    def _open_holiday_template_manager(self) -> None:
        HolidayTemplateManagerDialog(
            self,
            self._repos,
            self._visible_departments(),
            on_change=self._welcome_page.refresh,
        )

    def _open_document_template_manager(self) -> None:
        DocumentTemplateManagerDialog(self, self._repos)

    def _open_onboarding_task_manager(self) -> None:
        OnboardingTaskManagerDialog(self, self._repos)

    def _reload_departments(self) -> None:
        self._departments = self._repos.departments.list_all()
        self._rebuild_calendar_sidebar()

    def _handle_export(self) -> None:
        results = self._employee_page.export_current_results()
        if not results:
            messagebox.showinfo("Exportar", "No hay empleados para exportar.", parent=self)
            return
        path_str = filedialog.asksaveasfilename(
            title="Exportar empleados a CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="empleados.csv",
            parent=self,
        )
        if not path_str:
            return
        try:
            export_employees_csv(
                results, self._employee_page.departments_by_id(), Path(path_str)
            )
        except OSError as exc:
            messagebox.showerror(
                "Error al exportar",
                f"No se pudo escribir el archivo:\n{exc}",
                parent=self,
            )
            return
        messagebox.showinfo(
            "Exportar", f"Se exportaron {len(results)} empleado(s).", parent=self
        )

    def _open_department_manager(self) -> None:
        # Comprobado también aquí, no solo ocultando el botón que lo llama
        # (barra lateral y Accesos rápidos de Inicio): este diálogo permite
        # crear/eliminar cualquier departamento y, desde "Calendario
        # laboral...", escribir en el de cualquier departamento -- un
        # encargado nunca debe poder alcanzarlo por ningún camino, ni
        # siquiera uno que se añada en el futuro y se olvide de comprobar
        # el rol por su cuenta.
        if not self._is_admin:
            return
        dialog = DepartmentManagerDialog(
            self,
            self._repos,
            on_change=self._handle_departments_changed,
            on_view_calendar=self._show_department_calendar,
        )
        self.wait_window(dialog)

    def _open_user_manager(self) -> None:
        dialog = UserManagerDialog(
            self, self._repos, self._departments, current_user_id=self._current_user.id
        )
        self.wait_window(dialog)

    def _open_collective_agreement_manager(self) -> None:
        dialog = CollectiveAgreementManagerDialog(self, self._repos)
        self.wait_window(dialog)
        self._employee_page.reload_professional_categories()

    def _open_backup_manager(self) -> None:
        # El botón que llama a esto está deshabilitado cuando self._backups
        # es None (ver _build_sidebar) -- no debería ser alcanzable, pero el
        # assert deja además que mypy reduzca el tipo para BackupManagerDialog.
        assert self._backups is not None
        dialog = BackupManagerDialog(self, self._repos, self._backups)
        self.wait_window(dialog)

    def _open_database_settings(self) -> None:
        # Mismo motivo que _open_department_manager: el botón que llama a
        # esto ya está oculto para quien no sea administrador, pero un
        # ajuste que decide dónde vive TODA la base de datos de la empresa
        # no debe depender solo de que la barra lateral lo oculte bien.
        if not self._is_admin:
            return
        dialog = DatabaseSettingsDialog(self, self._repos)
        self.wait_window(dialog)

    def _open_audit_log(self) -> None:
        dialog = AuditLogDialog(self, self._repos)
        self.wait_window(dialog)

    def _open_account_settings(self) -> None:
        dialog = AccountSettingsDialog(
            self, self._repos, self._current_user, on_change=self._handle_account_changed
        )
        self.wait_window(dialog)

    def _handle_account_changed(self) -> None:
        assert self._current_user.id is not None
        self._current_user = self._repos.users.get(self._current_user.id)

    def _handle_departments_changed(self) -> None:
        self._reload_departments()
        self._employee_page.reload_departments()
        self._employee_page.refresh_employees()
        self._payroll_page.reload_departments()
        self._time_clock_page.reload_employees()
        self._welcome_page.refresh()
