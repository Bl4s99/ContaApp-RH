from __future__ import annotations

import calendar
import tkinter as tk
from collections.abc import Callable
from datetime import date, datetime
from tkinter import messagebox, ttk

from app import time_tracking, validation
from app.calendar_widget import MONTH_NAMES, DateEntry, TimeEntry, shift_month
from app.models import Employee
from app.models import TimeClockEntry as TimeClockEntryRecord
from app.repository import Repositories, RepositoryError
from app.window_utils import center_window

_TYPE_LABELS = {"entrada": "Entrada", "salida": "Salida"}
_TYPE_BY_LABEL = {label: key for key, label in _TYPE_LABELS.items()}


def _format_elapsed(total_seconds: float) -> str:
    total_minutes = int(total_seconds // 60)
    hours, minutes = divmod(max(total_minutes, 0), 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class TimeClockPage(ttk.Frame):
    def __init__(
        self, parent: tk.Misc, repos: Repositories, locked_department_id: int | None = None
    ) -> None:
        super().__init__(parent, padding=12)
        self._repos = repos
        self._locked_department_id = locked_department_id
        self._employees: list[Employee] = []
        self._current_employee: Employee | None = None
        self._view_year = date.today().year
        self._view_month = date.today().month

        self._build_widgets()
        self.reload_employees()
        self._tick()

    def _build_widgets(self) -> None:
        ttk.Label(self, text="Fichajes", style="PageHeading.TLabel").pack(
            anchor="w", pady=(0, 10)
        )

        selector_row = ttk.Frame(self)
        selector_row.pack(fill="x")
        ttk.Label(selector_row, text="Empleado:").pack(side="left")
        self.employee_combo = ttk.Combobox(selector_row, state="readonly", width=32)
        self.employee_combo.pack(side="left", padx=(6, 0))
        self.employee_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._handle_employee_changed()
        )

        kiosk = ttk.LabelFrame(self, text="Fichar ahora", padding=12)
        kiosk.pack(fill="x", pady=(12, 12))
        self.status_label = ttk.Label(kiosk, text="", font=("TkDefaultFont", 12, "bold"))
        self.status_label.pack(anchor="w")
        button_row = ttk.Frame(kiosk)
        button_row.pack(anchor="w", pady=(8, 0))
        self.clock_in_button = ttk.Button(
            button_row,
            text="Fichar entrada",
            command=self._handle_clock_in,
            style="Accent.TButton",
        )
        self.clock_in_button.pack(side="left", padx=(0, 6))
        self.clock_out_button = ttk.Button(
            button_row, text="Fichar salida", command=self._handle_clock_out
        )
        self.clock_out_button.pack(side="left")
        self.kiosk_error_label = ttk.Label(kiosk, text="", style="Error.TLabel")
        self.kiosk_error_label.pack(anchor="w", pady=(6, 0))

        nav_row = ttk.Frame(self)
        nav_row.pack(fill="x")
        ttk.Button(nav_row, text="<", width=3, command=self._go_previous_month).pack(side="left")
        self.month_label = ttk.Label(nav_row, text="", width=20, anchor="center")
        self.month_label.pack(side="left", padx=6)
        ttk.Button(nav_row, text=">", width=3, command=self._go_next_month).pack(side="left")

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, pady=(10, 0))
        columns = ("fecha", "hora", "tipo", "nota")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        for col, label, width in [
            ("fecha", "Fecha", 100),
            ("hora", "Hora", 70),
            ("tipo", "Tipo", 90),
            ("nota", "Nota", 240),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.total_label = ttk.Label(self, text="", style="Muted.TLabel")
        self.total_label.pack(anchor="w", pady=(6, 0))

        actions_row = ttk.Frame(self)
        actions_row.pack(fill="x", pady=(8, 0))
        ttk.Button(
            actions_row, text="Añadir fichaje manual...", command=self._handle_add_manual
        ).pack(side="left", padx=(0, 6))
        ttk.Button(actions_row, text="Editar...", command=self._handle_edit).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(actions_row, text="Eliminar", command=self._handle_delete).pack(side="left")

    def reload_employees(self) -> None:
        self._employees = self._repos.employees.search(
            department_id=self._locked_department_id, active_only=True
        )
        self.employee_combo.configure(values=[e.full_name for e in self._employees])
        if self._employees and self.employee_combo.current() == -1:
            self.employee_combo.current(0)
        self._handle_employee_changed()

    def _selected_employee(self) -> Employee | None:
        idx = self.employee_combo.current()
        if idx == -1:
            return None
        return self._employees[idx]

    def _handle_employee_changed(self) -> None:
        self._current_employee = self._selected_employee()
        self.kiosk_error_label.configure(text="")
        self._refresh_kiosk_status()
        self._refresh_month_table()

    def _refresh_kiosk_status(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            self.status_label.configure(text="Seleccione un empleado.")
            self.clock_in_button.state(["disabled"])
            self.clock_out_button.state(["disabled"])
            return
        last = self._repos.time_entries.last_entry_for_employee(employee.id)
        if last is not None and last.entry_type == "entrada":
            elapsed = (datetime.now() - last.entry_timestamp).total_seconds()
            self.status_label.configure(
                text=(
                    f"{employee.full_name} está fichado/a desde las "
                    f"{last.entry_timestamp.strftime('%H:%M')} "
                    f"({_format_elapsed(elapsed)})"
                )
            )
            self.clock_in_button.state(["disabled"])
            self.clock_out_button.state(["!disabled"])
        else:
            self.status_label.configure(text=f"{employee.full_name} no está fichado/a.")
            self.clock_in_button.state(["!disabled"])
            self.clock_out_button.state(["disabled"])

    def _tick(self) -> None:
        self._refresh_kiosk_status()
        self.after(30_000, self._tick)

    def _handle_clock_in(self) -> None:
        self._handle_clock("entrada")

    def _handle_clock_out(self) -> None:
        self._handle_clock("salida")

    def _handle_clock(self, entry_type: str) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        try:
            self._repos.time_entries.clock(employee.id, entry_type)
        except (validation.ValidationError, RepositoryError) as exc:
            self.kiosk_error_label.configure(text=str(exc))
            return
        self.kiosk_error_label.configure(text="")
        self._refresh_kiosk_status()
        self._refresh_month_table()

    def _go_previous_month(self) -> None:
        self._view_year, self._view_month = shift_month(self._view_year, self._view_month, -1)
        self._refresh_month_table()

    def _go_next_month(self) -> None:
        self._view_year, self._view_month = shift_month(self._view_year, self._view_month, 1)
        self._refresh_month_table()

    def _refresh_month_table(self) -> None:
        self.month_label.configure(text=f"{MONTH_NAMES[self._view_month - 1]} {self._view_year}")
        self.tree.delete(*self.tree.get_children())
        employee = self._current_employee
        if employee is None or employee.id is None:
            self.total_label.configure(text="")
            return
        entries = self._repos.time_entries.list_for_month(
            employee.id, self._view_year, self._view_month
        )
        for entry in entries:
            assert entry.id is not None
            self.tree.insert(
                "",
                tk.END,
                iid=str(entry.id),
                values=(
                    entry.entry_timestamp.strftime("%d/%m/%Y"),
                    entry.entry_timestamp.strftime("%H:%M"),
                    _TYPE_LABELS[entry.entry_type],
                    entry.note,
                ),
            )
        # El total NO se calcula solo sobre `entries` (acotados a este mes):
        # un turno que cruza el límite de mes necesita también el fichaje
        # del mes vecino para emparejarse bien -- se usa el historial
        # completo del empleado y se descartan los días fuera de este mes
        # después de emparejar, no antes (ver time_tracking.
        # total_worked_hours_in_range()).
        last_day = calendar.monthrange(self._view_year, self._view_month)[1]
        month_start = date(self._view_year, self._view_month, 1)
        month_end = date(self._view_year, self._view_month, last_day)
        all_entries = self._repos.time_entries.list_all_for_employee(employee.id)
        total = time_tracking.total_worked_hours_in_range(all_entries, month_start, month_end)
        self.total_label.configure(text=f"Horas trabajadas este mes: {total:.2f} h")

    def _selected_entry_id(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_add_manual(self) -> None:
        if self._current_employee is None:
            messagebox.showinfo("Fichajes", "Seleccione un empleado primero.", parent=self)
            return
        TimeEntryDialog(
            self, self._repos, self._current_employee, on_change=self._handle_dialog_change
        )

    def _handle_edit(self) -> None:
        entry_id = self._selected_entry_id()
        if entry_id is None or self._current_employee is None:
            messagebox.showinfo("Fichajes", "Seleccione un fichaje de la lista.", parent=self)
            return
        entry = self._repos.time_entries.get(entry_id)
        TimeEntryDialog(
            self,
            self._repos,
            self._current_employee,
            on_change=self._handle_dialog_change,
            entry=entry,
        )

    def _handle_delete(self) -> None:
        entry_id = self._selected_entry_id()
        if entry_id is None:
            messagebox.showinfo("Fichajes", "Seleccione un fichaje de la lista.", parent=self)
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", "¿Eliminar este fichaje?", parent=self
        ):
            return
        try:
            self._repos.time_entries.delete(entry_id)
        except RepositoryError as exc:
            messagebox.showerror("Fichajes", str(exc), parent=self)
            return
        self._handle_dialog_change()

    def _handle_dialog_change(self) -> None:
        self._refresh_kiosk_status()
        self._refresh_month_table()


class TimeEntryDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        on_change: Callable[[], None],
        entry: TimeClockEntryRecord | None = None,
    ) -> None:
        super().__init__(parent)
        self.title(f"Fichaje — {employee.full_name}")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        assert employee.id is not None
        self._repos = repos
        self._employee_id = employee.id
        self._on_change = on_change
        self._editing_id = entry.id if entry is not None else None

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Tipo *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.type_combo = ttk.Combobox(
            frame, state="readonly", width=20, values=["Entrada", "Salida"]
        )
        self.type_combo.grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Fecha *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        marked_dates = repos.closures.list_dates_for_department(employee.department_id)
        self.date_entry = DateEntry(frame, max_date=date.today(), marked_dates=marked_dates)
        self.date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Hora *").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.time_entry = TimeEntry(frame, minute_step=1)
        self.time_entry.grid(row=2, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Nota").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        self.note_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.note_var, width=30).grid(
            row=3, column=1, sticky="w", padx=6, pady=4
        )

        if entry is not None:
            self.type_combo.set(_TYPE_LABELS[entry.entry_type])
            self.date_entry.value_var.set(entry.entry_timestamp.date().isoformat())
            self.time_entry.hour_var.set(f"{entry.entry_timestamp.hour:02d}")
            self.time_entry.minute_var.set(f"{entry.entry_timestamp.minute:02d}")
            self.note_var.set(entry.note)
        else:
            self.type_combo.current(0)

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=4, column=0, columnspan=2, sticky="w", padx=6)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=5, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_frame, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        type_label = self.type_combo.get()
        if type_label not in _TYPE_BY_LABEL:
            self.error_label.configure(text="Seleccione un tipo de fichaje.")
            return
        entry_type = _TYPE_BY_LABEL[type_label]
        try:
            day = date.fromisoformat(self.date_entry.get())
            hour_str, minute_str = self.time_entry.get().split(":")
            timestamp = datetime(day.year, day.month, day.day, int(hour_str), int(minute_str))
            if self._editing_id is None:
                self._repos.time_entries.create_manual(
                    self._employee_id, entry_type, timestamp, self.note_var.get()
                )
            else:
                self._repos.time_entries.update(
                    self._editing_id, entry_type, timestamp, self.note_var.get()
                )
        except (validation.ValidationError, RepositoryError, ValueError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()
