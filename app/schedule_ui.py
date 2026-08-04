from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import date
from tkinter import messagebox, ttk

from app import validation
from app.calendar_widget import (
    WEEKDAY_LABELS,
    ColorSwatchPicker,
    DateEntry,
    TimeEntry,
    WeekdaySelector,
)
from app.models import (
    DayType,
    Department,
    Employee,
    HolidayTemplate,
    HolidayTemplateDate,
    Shift,
)
from app.repository import (
    DayTypeRepository,
    Repositories,
    RepositoryError,
    ShiftInput,
)
from app import theme
from app.window_utils import center_window

TkParent = tk.Tk | tk.Toplevel
_UNASSIGNED_LABEL = "— Sin asignar —"
_SHIFT_PREFIX = "Turno: "
_ABSENCE_PREFIX = "Ausencia: "


class ShiftManagerDialog(tk.Toplevel):
    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        department: Department,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Turnos — {department.name}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        assert department.id is not None
        self._repos = repos
        self._department_id = department.id
        self._on_change = on_change
        self._shifts: list[Shift] = []
        self._editing_id: int | None = None

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        palette = theme.current()
        self.listbox = tk.Listbox(
            frame,
            width=48,
            height=8,
            bg=palette.surface,
            fg=palette.text,
            selectbackground=palette.primary,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.primary_light,
        )
        self.listbox.grid(row=0, column=0, columnspan=2, padx=4, pady=4)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._load_selected())

        form = ttk.Frame(frame)
        form.grid(row=1, column=0, columnspan=2, pady=(8, 0))

        ttk.Label(form, text="Nombre").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var, width=24).grid(
            row=0, column=1, padx=4, pady=2
        )

        ttk.Label(form, text="Desde").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.start_entry = TimeEntry(form, initial="08:00")
        self.start_entry.grid(row=1, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(form, text="Hasta").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        self.end_entry = TimeEntry(form, initial="15:00")
        self.end_entry.grid(row=2, column=1, sticky="w", padx=4, pady=2)

        self.split_shift_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            form,
            text="Turno partido (segundo tramo horario)",
            variable=self.split_shift_var,
            command=self._toggle_split_shift_fields,
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=4, pady=(6, 2))

        self.split_label_start = ttk.Label(form, text="Desde (2º tramo)")
        self.split_label_start.grid(row=4, column=0, sticky="w", padx=4, pady=2)
        self.start_entry_2 = TimeEntry(form, initial="15:30")
        self.start_entry_2.grid(row=4, column=1, sticky="w", padx=4, pady=2)

        self.split_label_end = ttk.Label(form, text="Hasta (2º tramo)")
        self.split_label_end.grid(row=5, column=0, sticky="w", padx=4, pady=2)
        self.end_entry_2 = TimeEntry(form, initial="17:00")
        self.end_entry_2.grid(row=5, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(form, text="Días").grid(row=6, column=0, sticky="w", padx=4, pady=2)
        self.weekday_selector = WeekdaySelector(form, initial=frozenset({1, 2, 3, 4, 5}))
        self.weekday_selector.grid(row=6, column=1, sticky="w", padx=4, pady=2)

        self._toggle_split_shift_fields()

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=340)
        self.error_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 0))

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=(8, 0))
        ttk.Button(
            button_frame, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Nuevo turno", command=self._clear_form).pack(
            side="left", padx=4
        )
        ttk.Button(button_frame, text="Eliminar seleccionado", command=self._handle_delete).pack(
            side="left", padx=4
        )
        ttk.Button(button_frame, text="Cerrar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._refresh()

    def _toggle_split_shift_fields(self) -> None:
        enabled = self.split_shift_var.get()
        state = "normal" if enabled else "disabled"
        for widget in (self.split_label_start, self.split_label_end):
            widget.configure(state=state)
        self.start_entry_2.set_enabled(enabled)
        self.end_entry_2.set_enabled(enabled)

    def _refresh(self) -> None:
        self._shifts = self._repos.shifts.list_for_department(self._department_id)
        self.listbox.delete(0, tk.END)
        for shift in self._shifts:
            days = ",".join(WEEKDAY_LABELS[d - 1] for d in sorted(shift.days_of_week))
            self.listbox.insert(tk.END, f"{shift.name} · {shift.schedule_display} · {days}")

    def _load_selected(self) -> None:
        selection: tuple[int, ...] = self.listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            return
        shift = self._shifts[selection[0]]
        self._editing_id = shift.id
        self.name_var.set(shift.name)
        start_hour, start_minute = shift.start_time.split(":")
        end_hour, end_minute = shift.end_time.split(":")
        self.start_entry.hour_var.set(start_hour)
        self.start_entry.minute_var.set(start_minute)
        self.end_entry.hour_var.set(end_hour)
        self.end_entry.minute_var.set(end_minute)
        if shift.start_time_2 is not None and shift.end_time_2 is not None:
            self.split_shift_var.set(True)
            s2_hour, s2_minute = shift.start_time_2.split(":")
            e2_hour, e2_minute = shift.end_time_2.split(":")
            self.start_entry_2.hour_var.set(s2_hour)
            self.start_entry_2.minute_var.set(s2_minute)
            self.end_entry_2.hour_var.set(e2_hour)
            self.end_entry_2.minute_var.set(e2_minute)
        else:
            self.split_shift_var.set(False)
        self._toggle_split_shift_fields()
        self.weekday_selector.set_weekdays(shift.days_of_week)
        self.error_label.configure(text="")

    def _clear_form(self) -> None:
        self._editing_id = None
        self.name_var.set("")
        self.start_entry.hour_var.set("08")
        self.start_entry.minute_var.set("00")
        self.end_entry.hour_var.set("15")
        self.end_entry.minute_var.set("00")
        self.split_shift_var.set(False)
        self.start_entry_2.hour_var.set("15")
        self.start_entry_2.minute_var.set("30")
        self.end_entry_2.hour_var.set("17")
        self.end_entry_2.minute_var.set("00")
        self._toggle_split_shift_fields()
        self.weekday_selector.set_weekdays(frozenset({1, 2, 3, 4, 5}))
        self.listbox.selection_clear(0, tk.END)
        self.error_label.configure(text="")

    def _handle_save(self) -> None:
        has_split = self.split_shift_var.get()
        data = ShiftInput(
            department_id=self._department_id,
            name=self.name_var.get(),
            start_time=self.start_entry.get(),
            end_time=self.end_entry.get(),
            days_of_week=self.weekday_selector.get(),
            start_time_2=self.start_entry_2.get() if has_split else None,
            end_time_2=self.end_entry_2.get() if has_split else None,
        )
        try:
            if self._editing_id is None:
                self._repos.shifts.create(data)
            else:
                self._repos.shifts.update(self._editing_id, data)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._clear_form()
        self._refresh()
        self._on_change()

    def _handle_delete(self) -> None:
        selection: tuple[int, ...] = self.listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            self.error_label.configure(text="Seleccione un turno para eliminar.")
            return
        shift = self._shifts[selection[0]]
        if not messagebox.askyesno(
            "Confirmar eliminación",
            f"¿Eliminar el turno '{shift.name}'? Los empleados que lo tengan como turno por "
            "defecto se quedarán sin turno asignado.",
            parent=self,
        ):
            return
        assert shift.id is not None
        try:
            self._repos.shifts.delete(shift.id)
        except RepositoryError as exc:
            self.error_label.configure(text=str(exc))
            return
        self._clear_form()
        self._refresh()
        self._on_change()


class DayTypeManagerDialog(tk.Toplevel):
    def __init__(
        self, parent: TkParent, day_type_repo: DayTypeRepository, on_change: Callable[[], None]
    ) -> None:
        super().__init__(parent)
        self.title("Tipos de día")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repo = day_type_repo
        self._on_change = on_change
        self._day_types: list[DayType] = []
        self._editing_id: int | None = None

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        palette = theme.current()
        self.listbox = tk.Listbox(
            frame,
            width=40,
            height=8,
            bg=palette.surface,
            fg=palette.text,
            selectbackground=palette.primary,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.primary_light,
        )
        self.listbox.grid(row=0, column=0, columnspan=2, padx=4, pady=4)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._load_selected())

        ttk.Label(frame, text="Nombre").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(
            row=1, column=1, padx=4, pady=2
        )

        ttk.Label(frame, text="Color").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        self.color_picker = ColorSwatchPicker(frame)
        self.color_picker.grid(row=2, column=1, sticky="w", padx=4, pady=2)

        self.is_vacation_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="Cuenta como vacaciones", variable=self.is_vacation_var
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=4, pady=(2, 0))

        button_row = ttk.Frame(frame)
        button_row.grid(row=4, column=0, columnspan=2, pady=(6, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Nuevo tipo", command=self._clear_form).pack(
            side="left", padx=4
        )
        ttk.Button(button_row, text="Eliminar seleccionado", command=self._handle_delete).pack(
            side="left", padx=4
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=6, column=0, columnspan=2, pady=(8, 0)
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._refresh()

    def _refresh(self) -> None:
        self._day_types = self._repo.list_all()
        self.listbox.delete(0, tk.END)
        for idx, day_type in enumerate(self._day_types):
            suffix = "  (vacaciones)" if day_type.is_vacation else ""
            self.listbox.insert(tk.END, f"  {day_type.name}{suffix}")
            self.listbox.itemconfig(idx, foreground=day_type.color)

    def _load_selected(self) -> None:
        selection: tuple[int, ...] = self.listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            return
        day_type = self._day_types[selection[0]]
        self._editing_id = day_type.id
        self.name_var.set(day_type.name)
        self.color_picker.set(day_type.color)
        self.is_vacation_var.set(day_type.is_vacation)
        self.error_label.configure(text="")

    def _clear_form(self) -> None:
        self._editing_id = None
        self.name_var.set("")
        self.is_vacation_var.set(False)
        self.listbox.selection_clear(0, tk.END)
        self.error_label.configure(text="")

    def _handle_save(self) -> None:
        try:
            if self._editing_id is None:
                self._repo.create(
                    self.name_var.get(), self.color_picker.get(), self.is_vacation_var.get()
                )
            else:
                self._repo.update(
                    self._editing_id,
                    self.name_var.get(),
                    self.color_picker.get(),
                    self.is_vacation_var.get(),
                )
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._clear_form()
        self._refresh()
        self._on_change()

    def _handle_delete(self) -> None:
        selection: tuple[int, ...] = self.listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            self.error_label.configure(text="Seleccione un tipo de día para eliminar.")
            return
        day_type = self._day_types[selection[0]]
        if not messagebox.askyesno(
            "Confirmar eliminación", f"¿Eliminar el tipo de día '{day_type.name}'?", parent=self
        ):
            return
        assert day_type.id is not None
        try:
            self._repo.delete(day_type.id)
        except RepositoryError as exc:
            self.error_label.configure(text=str(exc))
            return
        self._clear_form()
        self._refresh()
        self._on_change()


class HolidayTemplateManagerDialog(tk.Toplevel):
    """Punto de entrada de 'Festivos...' en la barra lateral -- lista de
    plantillas reutilizables de festivos (ver HolidayTemplateDetailDialog
    para importar fechas y aplicarlas a departamentos)."""

    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        departments: list[Department],
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Festivos")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._departments = departments
        self._on_change = on_change
        self._templates: list[HolidayTemplate] = []

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text="Plantillas de festivos (nacional / autonómico / local): defina o\n"
            "importe una vez la lista de fechas y aplíquela a uno o varios\n"
            "departamentos, en vez de marcar cada cierre a mano.",
            style="Muted.TLabel",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        palette = theme.current()
        self.listbox = tk.Listbox(
            frame,
            width=50,
            height=8,
            bg=palette.surface,
            fg=palette.text,
            selectbackground=palette.primary,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.primary_light,
        )
        self.listbox.grid(row=1, column=0, columnspan=2, padx=4, pady=4)

        button_row = ttk.Frame(frame)
        button_row.grid(row=2, column=0, columnspan=2, pady=(4, 10))
        ttk.Button(
            button_row,
            text="Ver / gestionar...",
            command=self._handle_view,
            style="Accent.TButton",
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Eliminar", command=self._handle_delete).pack(
            side="left", padx=4
        )

        ttk.Separator(frame, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        ttk.Label(frame, text="Nueva plantilla").grid(
            row=4, column=0, columnspan=2, sticky="w"
        )
        new_row = ttk.Frame(frame)
        new_row.grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.name_var = tk.StringVar()
        ttk.Entry(new_row, textvariable=self.name_var, width=32).pack(side="left")
        ttk.Button(new_row, text="Crear", command=self._handle_create).pack(
            side="left", padx=(6, 0)
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=380)
        self.error_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=7, column=0, columnspan=2, pady=(8, 0)
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._refresh()

    def _refresh(self) -> None:
        self._templates = self._repos.holiday_templates.list_all()
        self.listbox.delete(0, tk.END)
        for template in self._templates:
            assert template.id is not None
            count = len(self._repos.holiday_templates.list_dates(template.id))
            plural = "fecha" if count == 1 else "fechas"
            created = template.created_at.strftime("%d/%m/%Y")
            self.listbox.insert(
                tk.END, f"  {template.name}  —  {count} {plural}  (creada {created})"
            )

    def _selected_template(self) -> HolidayTemplate | None:
        selection: tuple[int, ...] = self.listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            return None
        return self._templates[selection[0]]

    def _handle_create(self) -> None:
        try:
            self._repos.holiday_templates.create(self.name_var.get())
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self.name_var.set("")
        self.error_label.configure(text="")
        self._refresh()

    def _handle_view(self) -> None:
        template = self._selected_template()
        if template is None:
            self.error_label.configure(text="Seleccione una plantilla para ver o gestionar.")
            return
        self.error_label.configure(text="")
        assert template.id is not None
        HolidayTemplateDetailDialog(
            self, self._repos, self._departments, template.id, on_change=self._handle_detail_change
        )

    def _handle_detail_change(self) -> None:
        self._refresh()
        self._on_change()

    def _handle_delete(self) -> None:
        template = self._selected_template()
        if template is None:
            self.error_label.configure(text="Seleccione una plantilla para eliminar.")
            return
        if not messagebox.askyesno(
            "Confirmar eliminación",
            f"¿Eliminar la plantilla '{template.name}' y todas sus fechas?\n"
            "Esto no afecta a los cierres que ya se hayan aplicado a departamentos.",
            parent=self,
        ):
            return
        assert template.id is not None
        try:
            self._repos.holiday_templates.delete(template.id)
        except RepositoryError as exc:
            self.error_label.configure(text=str(exc))
            return
        self.error_label.configure(text="")
        self._refresh()


class HolidayTemplateDetailDialog(tk.Toplevel):
    """Ver/gestionar una plantilla de festivos: importar fechas (pegando
    texto), eliminar fechas sueltas, y aplicarlas en bloque como cierres a
    uno o varios departamentos. Vuelve a dibujar todo su contenido después
    de cada acción (ver _render), igual que ITEpisodeDetailDialog -- más
    simple que llevar dos caminos de actualización parcial divergentes."""

    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        departments: list[Department],
        template_id: int,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._departments = departments
        self._template_id = template_id
        self._on_change = on_change
        self._dates: list[HolidayTemplateDate] = []
        self._department_vars: dict[int, tk.BooleanVar] = {}

        self._frame = ttk.Frame(self, padding=12)
        self._frame.grid(row=0, column=0, sticky="nsew")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._render()
        center_window(self, parent)

    def _render(self) -> None:
        for widget in self._frame.winfo_children():
            widget.destroy()

        template = self._repos.holiday_templates.get(self._template_id)
        self.title(f"Festivos — {template.name}")
        self._dates = self._repos.holiday_templates.list_dates(self._template_id)

        row = 0
        ttk.Label(self._frame, text=template.name, style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1

        tree_frame = ttk.Frame(self._frame)
        tree_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.dates_tree = ttk.Treeview(
            tree_frame,
            columns=("fecha", "etiqueta"),
            show="headings",
            selectmode="browse",
            height=8,
        )
        for col, label, width in [("fecha", "Fecha", 90), ("etiqueta", "Etiqueta", 220)]:
            self.dates_tree.heading(col, text=label)
            self.dates_tree.column(col, width=width, anchor="w")
        dates_vsb = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.dates_tree.yview
        )
        self.dates_tree.configure(yscrollcommand=dates_vsb.set)
        self.dates_tree.pack(side="left", fill="x", expand=True)
        dates_vsb.pack(side="left", fill="y")
        for entry in self._dates:
            assert entry.id is not None
            self.dates_tree.insert(
                "",
                tk.END,
                iid=str(entry.id),
                values=(entry.holiday_date.strftime("%d/%m/%Y"), entry.label),
            )
        row += 1

        ttk.Button(
            self._frame, text="Eliminar fecha seleccionada", command=self._handle_delete_date
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        ttk.Separator(self._frame, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=8
        )
        row += 1

        ttk.Label(self._frame, text="Importar fechas", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        ttk.Label(
            self._frame,
            text="Una fecha por línea: AAAA-MM-DD seguido, opcionalmente, de una\n"
            "etiqueta libre. Ej.: 2026-01-01 Año Nuevo — las líneas que empiezan\n"
            "por # se ignoran (sirven para agrupar, ej. '# Nacional').",
            style="Muted.TLabel",
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        palette = theme.current()
        self.import_text = tk.Text(
            self._frame,
            width=50,
            height=6,
            bg=palette.surface,
            fg=palette.text,
            insertbackground=palette.text,
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.primary_light,
        )
        self.import_text.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        row += 1
        ttk.Button(self._frame, text="Importar", command=self._handle_import).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        row += 1

        self.import_error_label = ttk.Label(
            self._frame, text="", style="Error.TLabel", wraplength=380
        )
        self.import_error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        ttk.Separator(self._frame, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=8
        )
        row += 1

        ttk.Label(
            self._frame, text="Aplicar a departamentos", style="PageHeading.TLabel"
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        if not self._departments:
            ttk.Label(self._frame, text="(sin departamentos)", style="Muted.TLabel").grid(
                row=row, column=0, columnspan=2, sticky="w"
            )
            row += 1
        else:
            dept_frame = ttk.Frame(self._frame)
            dept_frame.grid(row=row, column=0, columnspan=2, sticky="w")
            self._department_vars = {}
            columns = 3
            for index, department in enumerate(self._departments):
                assert department.id is not None
                var = tk.BooleanVar(value=False)
                self._department_vars[department.id] = var
                ttk.Checkbutton(dept_frame, text=department.name, variable=var).grid(
                    row=index // columns, column=index % columns, sticky="w", padx=(0, 12)
                )
            row += 1

        ttk.Label(self._frame, text="Tipo de día a aplicar *").grid(
            row=row, column=0, sticky="w", pady=(6, 0)
        )
        row += 1
        self._day_types = self._repos.day_types.list_all()
        self.day_type_combo = ttk.Combobox(
            self._frame, state="readonly", width=28, values=[dt.name for dt in self._day_types]
        )
        default_index = next(
            (i for i, dt in enumerate(self._day_types) if dt.name.strip().lower() == "festivo"),
            -1,
        )
        if default_index != -1:
            self.day_type_combo.current(default_index)
        self.day_type_combo.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 0))
        row += 1

        ttk.Button(
            self._frame,
            text="Aplicar a departamento(s) seleccionado(s)",
            command=self._handle_apply,
            style="Accent.TButton",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        row += 1

        self.apply_error_label = ttk.Label(
            self._frame, text="", style="Error.TLabel", wraplength=380
        )
        self.apply_error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        ttk.Button(self._frame, text="Cerrar", command=self.destroy).grid(
            row=row, column=0, columnspan=2, pady=(8, 0)
        )

    def _selected_date_id(self) -> int | None:
        selection = self.dates_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_delete_date(self) -> None:
        date_id = self._selected_date_id()
        if date_id is None:
            self.import_error_label.configure(text="Seleccione una fecha para eliminar.")
            return
        try:
            self._repos.holiday_templates.delete_date(date_id)
        except RepositoryError as exc:
            self.import_error_label.configure(text=str(exc))
            return
        self._render()

    def _handle_import(self) -> None:
        text = self.import_text.get("1.0", "end-1c")
        try:
            count = self._repos.holiday_templates.import_dates(self._template_id, text)
        except (validation.ValidationError, RepositoryError) as exc:
            self.import_error_label.configure(text=str(exc))
            return
        self._render()
        messagebox.showinfo(
            "Importar festivos", f"Se han importado {count} fecha(s).", parent=self
        )

    def _handle_apply(self) -> None:
        selected_department_ids = [
            department_id for department_id, var in self._department_vars.items() if var.get()
        ]
        if not selected_department_ids:
            self.apply_error_label.configure(text="Seleccione al menos un departamento.")
            return
        type_index = self.day_type_combo.current()
        if type_index == -1:
            self.apply_error_label.configure(text="Seleccione un tipo de día.")
            return
        day_type = self._day_types[type_index]
        assert day_type.id is not None
        try:
            result = self._repos.holiday_templates.apply_to_departments(
                self._template_id, selected_department_ids, day_type.id
            )
        except RepositoryError as exc:
            self.apply_error_label.configure(text=str(exc))
            return
        self.apply_error_label.configure(text="")
        self._on_change()
        messagebox.showinfo(
            "Festivos aplicados",
            f"Aplicado a {result.departments_applied} departamento(s): "
            f"{result.closures_created} cierre(s) creados, "
            f"{result.closures_skipped} ya existían (sin modificar).",
            parent=self,
        )


class MarkAbsenceRangeDialog(tk.Toplevel):
    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        employees: list[Employee],
        on_change: Callable[[], None],
        initial_employee_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Marcar ausencia")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._employees = employees
        self._day_types = repos.day_types.list_all()
        self._on_change = on_change
        marked_dates = (
            repos.closures.list_dates_for_department(employees[0].department_id)
            if employees
            else frozenset()
        )

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Empleado *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.employee_combo = ttk.Combobox(
            frame, state="readonly", width=28, values=[e.full_name for e in employees]
        )
        self.employee_combo.grid(row=0, column=1, padx=6, pady=4)
        if initial_employee_id is not None:
            for idx, emp in enumerate(employees):
                if emp.id == initial_employee_id:
                    self.employee_combo.current(idx)
                    break

        ttk.Label(frame, text="Tipo *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.day_type_combo = ttk.Combobox(
            frame, state="readonly", width=28, values=[dt.name for dt in self._day_types]
        )
        self.day_type_combo.grid(row=1, column=1, padx=6, pady=4)

        ttk.Label(frame, text="Desde *").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.start_entry = DateEntry(frame, marked_dates=marked_dates)
        self.start_entry.grid(row=2, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Hasta *").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        self.end_entry = DateEntry(frame, marked_dates=marked_dates)
        self.end_entry.grid(row=3, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Nota").grid(row=4, column=0, sticky="w", padx=6, pady=4)
        self.note_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.note_var, width=30).grid(
            row=4, column=1, padx=6, pady=4
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=5, column=0, columnspan=2, sticky="w", padx=6)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=6, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_frame, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        emp_index = self.employee_combo.current()
        type_index = self.day_type_combo.current()
        if emp_index == -1:
            self.error_label.configure(text="Seleccione un empleado.")
            return
        if type_index == -1:
            self.error_label.configure(text="Seleccione un tipo de día.")
            return

        employee = self._employees[emp_index]
        day_type = self._day_types[type_index]
        assert employee.id is not None and day_type.id is not None

        try:
            start = date.fromisoformat(self.start_entry.get())
            end = date.fromisoformat(self.end_entry.get())
            result = self._repos.absences.mark_range(
                employee.id, day_type.id, start, end, note=self.note_var.get()
            )
        except (validation.ValidationError, RepositoryError, ValueError) as exc:
            self.error_label.configure(text=str(exc))
            return

        self._on_change()
        summary = f"Se marcaron {result.marked} día(s) para {employee.full_name}."
        if result.skipped:
            summary += f"\nSe omitieron {result.skipped} día(s) no laborables según su turno."
        messagebox.showinfo("Ausencia marcada", summary, parent=self)
        self.destroy()


class RequestAbsenceRangeDialog(tk.Toplevel):
    """Como MarkAbsenceRangeDialog, pero deja los días en estado 'pendiente'
    (request_range) en vez de confirmarlos al instante (mark_range) -- para
    pedir una ausencia que debe aprobarse antes de contar como real."""

    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        employees: list[Employee],
        on_change: Callable[[], None],
        initial_employee_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Solicitar ausencia")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._employees = employees
        self._day_types = repos.day_types.list_all()
        self._on_change = on_change
        marked_dates = (
            repos.closures.list_dates_for_department(employees[0].department_id)
            if employees
            else frozenset()
        )

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Empleado *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.employee_combo = ttk.Combobox(
            frame, state="readonly", width=28, values=[e.full_name for e in employees]
        )
        self.employee_combo.grid(row=0, column=1, padx=6, pady=4)
        if initial_employee_id is not None:
            for idx, emp in enumerate(employees):
                if emp.id == initial_employee_id:
                    self.employee_combo.current(idx)
                    break

        ttk.Label(frame, text="Tipo *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.day_type_combo = ttk.Combobox(
            frame, state="readonly", width=28, values=[dt.name for dt in self._day_types]
        )
        self.day_type_combo.grid(row=1, column=1, padx=6, pady=4)

        ttk.Label(frame, text="Desde *").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.start_entry = DateEntry(frame, marked_dates=marked_dates)
        self.start_entry.grid(row=2, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Hasta *").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        self.end_entry = DateEntry(frame, marked_dates=marked_dates)
        self.end_entry.grid(row=3, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Nota").grid(row=4, column=0, sticky="w", padx=6, pady=4)
        self.note_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.note_var, width=30).grid(
            row=4, column=1, padx=6, pady=4
        )

        ttk.Label(
            frame,
            text="Quedará pendiente de aprobación: no se verá en el\ncalendario ni contará en el saldo hasta que se apruebe.",
            style="Muted.TLabel",
            justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 4))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=6)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=7, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_frame, text="Solicitar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        emp_index = self.employee_combo.current()
        type_index = self.day_type_combo.current()
        if emp_index == -1:
            self.error_label.configure(text="Seleccione un empleado.")
            return
        if type_index == -1:
            self.error_label.configure(text="Seleccione un tipo de día.")
            return

        employee = self._employees[emp_index]
        day_type = self._day_types[type_index]
        assert employee.id is not None and day_type.id is not None

        try:
            start = date.fromisoformat(self.start_entry.get())
            end = date.fromisoformat(self.end_entry.get())
            result = self._repos.absences.request_range(
                employee.id, day_type.id, start, end, note=self.note_var.get()
            )
        except (validation.ValidationError, RepositoryError, ValueError) as exc:
            self.error_label.configure(text=str(exc))
            return

        self._on_change()
        summary = f"Se solicitaron {result.marked} día(s) para {employee.full_name}, pendientes de aprobación."
        if result.skipped:
            summary += f"\nSe omitieron {result.skipped} día(s) no laborables según su turno."
        messagebox.showinfo("Ausencia solicitada", summary, parent=self)
        self.destroy()


class MarkClosureRangeDialog(tk.Toplevel):
    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        department: Department,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Marcar cierre — {department.name}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        assert department.id is not None
        self._repos = repos
        self._department_id = department.id
        self._day_types = repos.day_types.list_all()
        self._on_change = on_change
        marked_dates = repos.closures.list_dates_for_department(department.id)

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Tipo *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.day_type_combo = ttk.Combobox(
            frame, state="readonly", width=28, values=[dt.name for dt in self._day_types]
        )
        self.day_type_combo.grid(row=0, column=1, padx=6, pady=4)

        ttk.Label(frame, text="Desde *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.start_entry = DateEntry(frame, marked_dates=marked_dates)
        self.start_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Hasta *").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.end_entry = DateEntry(frame, marked_dates=marked_dates)
        self.end_entry.grid(row=2, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Nota").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        self.note_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.note_var, width=30).grid(
            row=3, column=1, padx=6, pady=4
        )

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
        type_index = self.day_type_combo.current()
        if type_index == -1:
            self.error_label.configure(text="Seleccione un tipo de día.")
            return
        day_type = self._day_types[type_index]
        assert day_type.id is not None

        try:
            start = date.fromisoformat(self.start_entry.get())
            end = date.fromisoformat(self.end_entry.get())
            count = self._repos.closures.mark_range(
                self._department_id, day_type.id, start, end, note=self.note_var.get()
            )
        except (validation.ValidationError, RepositoryError, ValueError) as exc:
            self.error_label.configure(text=str(exc))
            return

        self._on_change()
        messagebox.showinfo("Cierre marcado", f"Se marcaron {count} día(s).", parent=self)
        self.destroy()


class DayCellDialog(tk.Toplevel):
    def __init__(
        self,
        parent: TkParent,
        day: date,
        employee: Employee,
        repos: Repositories,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"{employee.full_name} — {day.strftime('%d/%m/%Y')}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        assert employee.id is not None
        self._day = day
        self._employee_id = employee.id
        self._department_id = employee.department_id
        self._repos = repos
        self._on_change = on_change

        self._shifts = repos.shifts.list_for_department(self._department_id)
        self._day_types = repos.day_types.list_all()
        self._options = (
            [_UNASSIGNED_LABEL]
            + [f"{_SHIFT_PREFIX}{s.name}" for s in self._shifts]
            + [f"{_ABSENCE_PREFIX}{dt.name}" for dt in self._day_types]
        )

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        next_row = 0
        closures = repos.closures.get_for_month(self._department_id, day.year, day.month)
        closure = closures.get(day)
        if closure is not None:
            closure_type = next(
                (dt for dt in self._day_types if dt.id == closure.day_type_id), None
            )
            label = closure_type.name if closure_type is not None else "Cierre"
            ttk.Label(
                frame,
                text=f"Cierre de departamento este día: {label}",
                style="Error.TLabel",
                wraplength=280,
            ).grid(row=next_row, column=0, columnspan=2, sticky="w", pady=(0, 8))
            next_row += 1

        ttk.Label(frame, text="Estado de este día:").grid(
            row=next_row, column=0, sticky="w", padx=(0, 6)
        )
        self.status_var = tk.StringVar(value=self._current_selection())
        combo = ttk.Combobox(
            frame, state="readonly", width=28, values=self._options, textvariable=self.status_var
        )
        combo.grid(row=next_row, column=1, sticky="w")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._apply())
        next_row += 1

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=next_row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        next_row += 1

        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=next_row, column=0, columnspan=2, pady=(10, 0)
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _current_selection(self) -> str:
        absences = self._repos.absences.get_for_month(
            self._employee_id, self._day.year, self._day.month
        )
        absence = absences.get(self._day)
        if absence is not None:
            matched_type = next(
                (dt for dt in self._day_types if dt.id == absence.day_type_id), None
            )
            if matched_type is not None:
                return f"{_ABSENCE_PREFIX}{matched_type.name}"

        assignments = self._repos.daily_assignments.get_for_month(
            self._employee_id, self._day.year, self._day.month
        )
        assignment = assignments.get(self._day)
        if assignment is not None:
            matched_shift = next((s for s in self._shifts if s.id == assignment.shift_id), None)
            if matched_shift is not None:
                return f"{_SHIFT_PREFIX}{matched_shift.name}"

        return _UNASSIGNED_LABEL

    def _apply(self) -> None:
        selected = self.status_var.get()
        try:
            if selected == _UNASSIGNED_LABEL:
                self._repos.daily_assignments.set_day(self._employee_id, self._day, None)
                self._repos.absences.set_day(self._employee_id, self._day, None)
            elif selected.startswith(_SHIFT_PREFIX):
                shift_name = selected[len(_SHIFT_PREFIX):]
                matched_shift = next((s for s in self._shifts if s.name == shift_name), None)
                if matched_shift is None or matched_shift.id is None:
                    self.error_label.configure(text="Turno no válido.")
                    return
                self._repos.absences.set_day(self._employee_id, self._day, None)
                self._repos.daily_assignments.set_day(
                    self._employee_id, self._day, matched_shift.id
                )
            elif selected.startswith(_ABSENCE_PREFIX):
                type_name = selected[len(_ABSENCE_PREFIX):]
                matched_type = next((dt for dt in self._day_types if dt.name == type_name), None)
                if matched_type is None or matched_type.id is None:
                    self.error_label.configure(text="Tipo de día no válido.")
                    return
                self._repos.daily_assignments.set_day(self._employee_id, self._day, None)
                self._repos.absences.set_day(self._employee_id, self._day, matched_type.id)
            else:
                self.error_label.configure(text="Selección no válida.")
                return
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class AssignShiftRangeDialog(tk.Toplevel):
    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        employees: list[Employee],
        shifts: list[Shift],
        on_change: Callable[[], None],
        initial_employee_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Asignar turno")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._employees = employees
        self._shifts = shifts
        self._on_change = on_change
        marked_dates = (
            repos.closures.list_dates_for_department(employees[0].department_id)
            if employees
            else frozenset()
        )

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Empleado *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.employee_combo = ttk.Combobox(
            frame, state="readonly", width=28, values=[e.full_name for e in employees]
        )
        self.employee_combo.grid(row=0, column=1, padx=6, pady=4)
        if initial_employee_id is not None:
            for idx, emp in enumerate(employees):
                if emp.id == initial_employee_id:
                    self.employee_combo.current(idx)
                    break

        ttk.Label(frame, text="Turno *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.shift_combo = ttk.Combobox(
            frame,
            state="readonly",
            width=28,
            values=[f"{s.name} ({s.schedule_display})" for s in shifts],
        )
        self.shift_combo.grid(row=1, column=1, padx=6, pady=4)

        ttk.Label(frame, text="Desde *").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.start_entry = DateEntry(frame, marked_dates=marked_dates)
        self.start_entry.grid(row=2, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Hasta *").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        self.end_entry = DateEntry(frame, marked_dates=marked_dates)
        self.end_entry.grid(row=3, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(
            frame,
            text=(
                "Solo se asignarán los días que coincidan con el patrón\n"
                "semanal del turno seleccionado."
            ),
            style="Muted.TLabel",
            justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 4))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=5, column=0, columnspan=2, sticky="w", padx=6)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=6, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_frame, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        emp_index = self.employee_combo.current()
        shift_index = self.shift_combo.current()
        if emp_index == -1:
            self.error_label.configure(text="Seleccione un empleado.")
            return
        if shift_index == -1:
            self.error_label.configure(text="Seleccione un turno.")
            return

        employee = self._employees[emp_index]
        shift = self._shifts[shift_index]
        assert employee.id is not None and shift.id is not None

        try:
            start = date.fromisoformat(self.start_entry.get())
            end = date.fromisoformat(self.end_entry.get())
            result = self._repos.daily_assignments.apply_shift_to_range(
                employee.id, shift.id, start, end
            )
        except (validation.ValidationError, RepositoryError, ValueError) as exc:
            self.error_label.configure(text=str(exc))
            return

        self._on_change()
        summary = f"Se asignaron {result.marked} día(s) para {employee.full_name}."
        if result.skipped:
            summary += f"\nSe omitieron {result.skipped} día(s) fuera del patrón del turno."
        messagebox.showinfo("Turno asignado", summary, parent=self)
        self.destroy()


_ROTATION_REST_LABEL = "— Descanso —"


class AssignShiftRotationDialog(tk.Toplevel):
    """Aplica una secuencia de turnos (p. ej. Mañana-Tarde-Noche-Descanso)
    que se repite cíclicamente día a día a lo largo de un rango -- a
    diferencia de AssignShiftRangeDialog (UN turno respetando su propio
    days_of_week), aquí es el orden en que se añaden al patrón lo que
    decide qué toca cada día. El patrón se construye en memoria con los
    botones "Añadir al patrón"/"Quitar último" y no se guarda en ningún
    sitio -- solo su resultado día a día (ver DailyAssignmentRepository.
    apply_rotation_to_range)."""

    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        employees: list[Employee],
        shifts: list[Shift],
        on_change: Callable[[], None],
        initial_employee_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Aplicar rotación de turnos")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._employees = employees
        self._shifts = shifts
        self._on_change = on_change
        self._pattern: list[int | None] = []
        marked_dates = (
            repos.closures.list_dates_for_department(employees[0].department_id)
            if employees
            else frozenset()
        )

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Empleado *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.employee_combo = ttk.Combobox(
            frame, state="readonly", width=28, values=[e.full_name for e in employees]
        )
        self.employee_combo.grid(row=0, column=1, padx=6, pady=4)
        if initial_employee_id is not None:
            for idx, emp in enumerate(employees):
                if emp.id == initial_employee_id:
                    self.employee_combo.current(idx)
                    break

        ttk.Label(frame, text="Añadir al patrón").grid(
            row=1, column=0, sticky="w", padx=6, pady=4
        )
        add_row = ttk.Frame(frame)
        add_row.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        self.add_combo = ttk.Combobox(
            add_row,
            state="readonly",
            width=20,
            values=[_ROTATION_REST_LABEL] + [f"{s.name} ({s.schedule_display})" for s in shifts],
        )
        self.add_combo.current(0)
        self.add_combo.pack(side="left")
        ttk.Button(add_row, text="Añadir", command=self._handle_add_to_pattern).pack(
            side="left", padx=(6, 0)
        )

        ttk.Label(frame, text="Patrón actual").grid(row=2, column=0, sticky="nw", padx=6, pady=4)
        pattern_frame = ttk.Frame(frame)
        pattern_frame.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        palette = theme.current()
        self.pattern_listbox = tk.Listbox(
            pattern_frame,
            width=30,
            height=5,
            bg=palette.surface,
            fg=palette.text,
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.primary_light,
            selectbackground=palette.primary,
            selectforeground=palette.text_on_dark,
        )
        self.pattern_listbox.pack(side="top", fill="x")
        ttk.Button(
            pattern_frame, text="Quitar último", command=self._handle_remove_last_from_pattern
        ).pack(side="top", anchor="w", pady=(4, 0))

        ttk.Label(frame, text="Desde *").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        self.start_entry = DateEntry(frame, marked_dates=marked_dates)
        self.start_entry.grid(row=3, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Hasta *").grid(row=4, column=0, sticky="w", padx=6, pady=4)
        self.end_entry = DateEntry(frame, marked_dates=marked_dates)
        self.end_entry.grid(row=4, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(
            frame,
            text=(
                "El patrón se repite cíclicamente día a día a lo largo de\n"
                "todo el rango, sin mirar el patrón semanal de cada turno."
            ),
            style="Muted.TLabel",
            justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 4))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=6, column=0, columnspan=2, sticky="w", padx=6)

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=7, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_frame, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_frame, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_add_to_pattern(self) -> None:
        index = self.add_combo.current()
        if index <= 0:
            self._pattern.append(None)
            label = _ROTATION_REST_LABEL
        else:
            shift = self._shifts[index - 1]
            assert shift.id is not None
            self._pattern.append(shift.id)
            label = shift.name
        self.pattern_listbox.insert(tk.END, f"{len(self._pattern)}. {label}")
        self.error_label.configure(text="")

    def _handle_remove_last_from_pattern(self) -> None:
        if not self._pattern:
            return
        self._pattern.pop()
        self.pattern_listbox.delete(tk.END)

    def _handle_save(self) -> None:
        emp_index = self.employee_combo.current()
        if emp_index == -1:
            self.error_label.configure(text="Seleccione un empleado.")
            return
        if not self._pattern:
            self.error_label.configure(text="Añada al menos un elemento al patrón.")
            return

        employee = self._employees[emp_index]
        assert employee.id is not None

        try:
            start = date.fromisoformat(self.start_entry.get())
            end = date.fromisoformat(self.end_entry.get())
            result = self._repos.daily_assignments.apply_rotation_to_range(
                employee.id, self._pattern, start, end
            )
        except (validation.ValidationError, RepositoryError, ValueError) as exc:
            self.error_label.configure(text=str(exc))
            return

        self._on_change()
        summary = f"Se asignaron {result.marked} día(s) para {employee.full_name}."
        if result.skipped:
            summary += f"\nSe marcaron {result.skipped} día(s) de descanso."
        messagebox.showinfo("Rotación aplicada", summary, parent=self)
        self.destroy()

