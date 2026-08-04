"""Autoservicio ligero para el empleado (punto 17 de la hoja de ruta):
consultar la propia nómina más reciente, saldo de vacaciones y fichajes de
este mes sin necesitar una cuenta de usuario ni pedírselo a RRHH -- solo un
email + PIN de 4-6 dígitos (ver EmployeeRepository.authenticate_self_service()).
Todo lo que se muestra aquí es de solo lectura: ni fichar (eso sigue
teniendo su propio modo kiosko, TimeClockPage) ni ninguna otra acción de
escritura vive en este módulo."""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk

from app import time_tracking, vacation
from app.calendar_widget import MONTH_NAMES
from app.models import Employee
from app.repository import Repositories
from app.window_utils import center_window

TkParent = tk.Tk | tk.Toplevel

_TYPE_LABELS = {"entrada": "Entrada", "salida": "Salida"}


def _format_currency(value: float) -> str:
    # Formato español (punto de millar, coma decimal) -- duplicado a
    # propósito, igual que en el resto de módulos de UI (ver
    # collective_agreement_ui._format_currency para la explicación completa).
    us_formatted = f"{value:,.2f}"
    integer_part, decimal_part = us_formatted.split(".")
    integer_part = integer_part.replace(",", ".")
    return f"{integer_part},{decimal_part} €"


class EmployeeAccessDialog(tk.Toplevel):
    """Punto de entrada de autoservicio, abierto desde la ventana de inicio
    de sesión: email + PIN, sin ninguna cuenta de usuario. Al autenticar
    correctamente abre EmployeeSelfServiceWindow y se cierra a sí mismo; la
    propia LoginWindow sigue funcionando debajo, sin verse afectada -- son
    dos flujos de acceso completamente independientes."""

    def __init__(self, parent: TkParent, repos: Repositories) -> None:
        super().__init__(parent)
        self.title("Consultar mis datos")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._parent = parent

        frame = ttk.Frame(self, padding=20)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Consultar mis datos", style="PageHeading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        ttk.Label(
            frame,
            text="Introduce tu email y tu PIN de acceso para ver tu nómina,\n"
            "saldo de vacaciones y fichajes recientes.",
            style="Muted.TLabel",
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 16))

        ttk.Label(frame, text="Email").grid(row=2, column=0, sticky="w", pady=4)
        self.email_var = tk.StringVar()
        email_entry = ttk.Entry(frame, textvariable=self.email_var, width=28)
        email_entry.grid(row=2, column=1, sticky="w", pady=4, padx=(8, 0))

        ttk.Label(frame, text="PIN").grid(row=3, column=0, sticky="w", pady=4)
        self.pin_var = tk.StringVar()
        pin_entry = ttk.Entry(frame, textvariable=self.pin_var, show="•", width=28)
        pin_entry.grid(row=3, column=1, sticky="w", pady=4, padx=(8, 0))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        button_row = ttk.Frame(frame)
        button_row.grid(row=5, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(
            button_row, text="Entrar", command=self._handle_access, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        email_entry.bind("<Return>", lambda _e: self._handle_access())
        pin_entry.bind("<Return>", lambda _e: self._handle_access())
        email_entry.focus_set()

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_access(self) -> None:
        email = self.email_var.get().strip()
        pin = self.pin_var.get()
        if not email or not pin:
            self.error_label.configure(text="Introduce tu email y tu PIN.")
            return
        employee = self._repos.employees.authenticate_self_service(email, pin)
        if employee is None:
            self.error_label.configure(text="Email o PIN incorrectos.")
            self.pin_var.set("")
            return
        parent = self._parent
        self.destroy()
        EmployeeSelfServiceWindow(parent, self._repos, employee)


class EmployeeSelfServiceWindow(tk.Toplevel):
    """Vista de solo lectura para el propio empleado: nómina más reciente,
    saldo de vacaciones del año en curso, y fichajes de este mes. Ninguna
    acción de escritura vive aquí -- ni fichar, ni editar ningún dato;
    cualquier corrección real la sigue haciendo RRHH desde la ficha."""

    def __init__(self, parent: TkParent, repos: Repositories, employee: Employee) -> None:
        # `employee` always comes from authenticate_self_service(), a real
        # row already fetched from the database -- its id is never None in
        # practice, only Optional in the type because Employee models both
        # a saved row and (elsewhere) a not-yet-created one.
        assert employee.id is not None
        employee_id = employee.id
        super().__init__(parent)
        self.title(f"Mis datos — {employee.full_name}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=20)
        frame.grid(row=0, column=0, sticky="nsew")

        row = 0
        ttk.Label(frame, text=employee.full_name, style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        ttk.Label(frame, text=employee.position, style="Muted.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 16)
        )
        row += 1

        today = date.today()

        # --- Saldo de vacaciones ---
        ttk.Label(frame, text="Saldo de vacaciones", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        annual_days = repos.app_settings.get_annual_vacation_days()
        used_days = repos.absences.count_vacation_days_for_year(employee_id, today.year)
        balance = vacation.calculate_balance(employee.hire_date, today.year, annual_days, used_days)
        ttk.Label(
            frame,
            text=(
                f"{balance.remaining_days:g} días disponibles de {balance.entitled_days:g} "
                f"({balance.used_days:g} ya disfrutados este año)"
            ),
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 16))
        row += 1

        # --- Nómina más reciente ---
        ttk.Label(frame, text="Última nómina generada", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        records = repos.payroll_records.list_for_employee(employee_id)
        if records:
            latest = records[-1]
            payroll = latest.payroll
            ttk.Label(
                frame,
                text=f"{MONTH_NAMES[payroll.month - 1]} {payroll.year} "
                f"(generada el {latest.generated_at.strftime('%d/%m/%Y')})",
                style="Muted.TLabel",
            ).grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
            for label, value in [
                ("Bruto del mes", _format_currency(payroll.bruto_mes)),
                (
                    f"Retención IRPF ({payroll.irpf_pct:.2f}%)",
                    f"-{_format_currency(payroll.irpf_importe)}",
                ),
                (
                    f"Seguridad Social ({payroll.ss_employee_pct:.2f}%)",
                    f"-{_format_currency(payroll.ss_employee_importe)}",
                ),
            ]:
                ttk.Label(frame, text=label).grid(
                    row=row, column=0, sticky="w", padx=(16, 0)
                )
                ttk.Label(frame, text=value).grid(row=row, column=1, sticky="e")
                row += 1
            ttk.Label(frame, text="NETO A PERCIBIR", font=("", 10, "bold")).grid(
                row=row, column=0, sticky="w", padx=(16, 0), pady=(2, 16)
            )
            ttk.Label(frame, text=_format_currency(payroll.neto), font=("", 10, "bold")).grid(
                row=row, column=1, sticky="e", pady=(2, 16)
            )
            row += 1
        else:
            ttk.Label(
                frame, text="Todavía no hay ninguna nómina generada.", style="Muted.TLabel"
            ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 16))
            row += 1

        # --- Fichajes de este mes ---
        ttk.Label(
            frame, text=f"Fichajes de {MONTH_NAMES[today.month - 1]}", style="PageHeading.TLabel"
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        entries = repos.time_entries.list_for_month(employee_id, today.year, today.month)
        total_hours = time_tracking.total_worked_hours(entries)
        hours = int(total_hours)
        minutes = round((total_hours - hours) * 60)
        ttk.Label(
            frame, text=f"Total trabajado este mes: {hours} h {minutes} min", style="Muted.TLabel"
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1

        tree_frame = ttk.Frame(frame)
        tree_frame.grid(row=row, column=0, columnspan=2, sticky="ew")
        tree = ttk.Treeview(
            tree_frame, columns=("fecha", "hora", "tipo"), show="headings",
            selectmode="none", height=6,
        )
        for col, label, width in [
            ("fecha", "Fecha", 90), ("hora", "Hora", 60), ("tipo", "Tipo", 80),
        ]:
            tree.heading(col, text=label)
            tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="x", expand=True)
        vsb.pack(side="left", fill="y")
        for entry in entries:
            assert entry.id is not None
            tree.insert(
                "",
                tk.END,
                iid=str(entry.id),
                values=(
                    entry.entry_timestamp.strftime("%d/%m/%Y"),
                    entry.entry_timestamp.strftime("%H:%M"),
                    _TYPE_LABELS[entry.entry_type],
                ),
            )
        row += 1

        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=row, column=0, columnspan=2, pady=(16, 0)
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)
