from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from tkinter import ttk

from app.calendar_widget import MONTH_NAMES, WEEKDAY_FULL_LABELS
from app.repository import Repositories


def _greeting(hour: int) -> str:
    if 6 <= hour < 13:
        return "¡Buenos días!"
    if 13 <= hour < 20:
        return "¡Buenas tardes!"
    return "¡Buenas noches!"


class WelcomePage(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        on_go_employees: Callable[[], None],
        on_go_payroll: Callable[[], None],
        on_go_departments: Callable[[], None],
        on_export: Callable[[], None],
        is_admin: bool = True,
        locked_department_id: int | None = None,
    ) -> None:
        super().__init__(parent, padding=24)
        self._repos = repos
        self._on_go_employees = on_go_employees
        self._on_go_payroll = on_go_payroll
        self._on_go_departments = on_go_departments
        self._on_export = on_export
        self._is_admin = is_admin
        self._locked_department_id = locked_department_id

        self._greeting_label = ttk.Label(self, style="PageHeading.TLabel")
        self._greeting_label.pack(anchor="w")
        self._date_label = ttk.Label(self, style="Muted.TLabel")
        self._date_label.pack(anchor="w", pady=(0, 20))

        self._cards_frame = ttk.Frame(self)
        self._cards_frame.pack(anchor="w", fill="x", pady=(0, 16))

        self._details_frame = ttk.Frame(self)
        self._details_frame.pack(anchor="w", fill="x", pady=(0, 24))

        quick_access = ttk.Labelframe(self, text="Accesos rápidos", padding=12)
        quick_access.pack(anchor="w")
        ttk.Button(
            quick_access,
            text="Lista de empleados",
            width=24,
            command=self._on_go_employees,
            style="Accent.TButton",
        ).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(
            quick_access,
            text="Nóminas",
            width=24,
            command=self._on_go_payroll,
            style="Accent.TButton",
        ).grid(row=0, column=1, padx=4, pady=4)
        # "Departamentos" gestiona alta/baja de cualquier departamento y da
        # acceso a su calendario laboral completo -- solo para admin, igual
        # que en la barra lateral. No basta con ocultar el botón aquí:
        # _open_department_manager() en MainWindow también comprueba
        # is_admin por su cuenta, para que ningún otro camino futuro pueda
        # volver a abrirlo sin pasar por este control.
        export_column = 1
        if self._is_admin:
            ttk.Button(
                quick_access,
                text="Departamentos",
                width=24,
                command=self._on_go_departments,
                style="Accent.TButton",
            ).grid(row=1, column=0, padx=4, pady=4)
        else:
            export_column = 0
        ttk.Button(
            quick_access,
            text="Exportar CSV...",
            width=24,
            command=self._on_export,
            style="Accent.TButton",
        ).grid(row=1, column=export_column, padx=4, pady=4)

        self.refresh()

    def _make_card(self, value: str, caption: str) -> None:
        card = ttk.Frame(self._cards_frame, padding=12, style="Card.TFrame")
        card.pack(side="left", padx=(0, 12))
        ttk.Label(card, text=value, style="CardValue.TLabel").pack()
        ttk.Label(card, text=caption, style="CardCaption.TLabel").pack()

    def refresh(self) -> None:
        now = datetime.now()
        today = now.date()
        self._greeting_label.configure(text=_greeting(now.hour))
        weekday = WEEKDAY_FULL_LABELS[today.isoweekday() - 1]
        month_name = MONTH_NAMES[today.month - 1].lower()
        self._date_label.configure(
            text=f"{weekday}, {today.day} de {month_name} de {today.year}"
        )

        all_employees = self._repos.employees.search()
        active_count = sum(1 for e in all_employees if e.active)
        employees_by_id = {e.id: e for e in all_employees}
        departments = self._repos.departments.list_all()
        departments_by_id = {d.id: d for d in departments}
        day_types_by_id = {dt.id: dt for dt in self._repos.day_types.list_all()}
        absences_today = self._repos.absences.list_for_date(today)
        closures_today = self._repos.closures.list_for_date(today)

        for widget in self._cards_frame.winfo_children():
            widget.destroy()
        self._make_card(str(active_count), "Empleados activos")
        self._make_card(str(len(departments)), "Departamentos")
        self._make_card(str(len(absences_today)), "Ausentes hoy")
        self._make_card(str(len(closures_today)), "Cierres hoy")

        for widget in self._details_frame.winfo_children():
            widget.destroy()

        # Las 4 tarjetas de conteo de arriba son agregadas a propósito,
        # incluso para un encargado (se consideró de baja sensibilidad, ver
        # README) -- pero estas líneas de detalle van más allá de un
        # simple contador: nombran a personas concretas junto a la
        # categoría de su ausencia (que puede ser una baja médica). Eso sí
        # se restringe al propio departamento del encargado, igual que el
        # resto de páginas con locked_department_id.
        if self._locked_department_id is not None:
            absences_today = [
                a
                for a in absences_today
                if employees_by_id.get(a.employee_id) is not None
                and employees_by_id[a.employee_id].department_id == self._locked_department_id
            ]
            closures_today = [
                c for c in closures_today if c.department_id == self._locked_department_id
            ]

        if absences_today:
            absence_names = [
                f"{employees_by_id[a.employee_id].full_name} "
                f"({day_types_by_id[a.day_type_id].name})"
                for a in absences_today
                if a.employee_id in employees_by_id and a.day_type_id in day_types_by_id
            ]
            if absence_names:
                ttk.Label(
                    self._details_frame,
                    text="Ausentes hoy: " + ", ".join(absence_names),
                    wraplength=760,
                    justify="left",
                ).pack(anchor="w", pady=(0, 4))

        if closures_today:
            closure_names = [
                f"{departments_by_id[c.department_id].name} "
                f"({day_types_by_id[c.day_type_id].name})"
                for c in closures_today
                if c.department_id in departments_by_id and c.day_type_id in day_types_by_id
            ]
            if closure_names:
                ttk.Label(
                    self._details_frame,
                    text="Cierres hoy: " + ", ".join(closure_names),
                    wraplength=760,
                    justify="left",
                ).pack(anchor="w")
