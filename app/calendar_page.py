from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from app.calendar_widget import MONTH_NAMES, WEEKDAY_LABELS, ScrollableFrame2D, shift_month
from app.models import (
    DailyShiftAssignment,
    DayType,
    Department,
    DepartmentClosure,
    Employee,
    EmployeeAbsence,
    Shift,
)
from app import theme
from app.repository import Repositories
from app.schedule_ui import (
    AssignShiftRangeDialog,
    AssignShiftRotationDialog,
    DayCellDialog,
    MarkAbsenceRangeDialog,
    MarkClosureRangeDialog,
    RequestAbsenceRangeDialog,
    ShiftManagerDialog,
)

_GRID_MIN_HEIGHT = 90
_GRID_MAX_HEIGHT = 420
_GRID_HEADER_PX = 44
_GRID_ROW_PX = 24
_GRID_PADDING_PX = 16
_NAME_COL_WIDTH_PX = 150
_DAY_COL_WIDTH_PX = 34
# Los tipos de día usan un color fijo elegido por el usuario (PRESET_COLORS
# en calendar_widget.py), independiente del tema claro/oscuro de la app --
# son colores de saturación media, siempre legibles con texto oscuro, así
# que este texto se queda fijo (a diferencia de shift_cell_color, que sí
# está pensado para adaptarse al tema y por tanto usa palette.text).
_PRESET_TEXT = "#1a1a1a"


def _grid_height(row_count: int) -> int:
    """Alto de la rejilla ajustado al contenido (con scroll para el resto si
    hace falta), en vez de estirarse siempre a ocupar toda la página."""
    natural = _GRID_HEADER_PX + row_count * _GRID_ROW_PX + _GRID_PADDING_PX
    return max(_GRID_MIN_HEIGHT, min(_GRID_MAX_HEIGHT, natural))


def _days_in_month(year: int, month: int) -> list[date]:
    _, last_day = calendar.monthrange(year, month)
    return [date(year, month, day) for day in range(1, last_day + 1)]


def _code_map(ids: list[int | None], prefix: str) -> dict[int | None, str]:
    """Código corto y único por id (T1, T2, ... / D1, D2, ...) para mostrar en
    una celda estrecha. A diferencia de truncar el nombre, nunca colisiona:
    p. ej. "Turno 2" y "Turno único" truncados darían ambos "TURN"."""
    return {item_id: f"{prefix}{index + 1}" for index, item_id in enumerate(ids)}


def _resolve_cell_display(
    *,
    absence: EmployeeAbsence | None,
    assignment: DailyShiftAssignment | None,
    closure: DepartmentClosure | None,
    day_types_by_id: dict[int | None, DayType],
    shifts_by_id: dict[int | None, Shift],
    shift_codes: dict[int | None, str],
    day_type_codes: dict[int | None, str],
) -> tuple[str, str, str]:
    """Resolución de la celda: ausencia individual > turno asignado > cierre >
    vacío. Devuelve (texto, color de fondo, color de texto)."""
    palette = theme.current()
    if absence is not None:
        day_type = day_types_by_id.get(absence.day_type_id)
        if day_type is not None:
            return day_type_codes.get(absence.day_type_id, "?"), day_type.color, _PRESET_TEXT
    if assignment is not None:
        shift = shifts_by_id.get(assignment.shift_id)
        if shift is not None:
            return (
                shift_codes.get(assignment.shift_id, "?"),
                palette.shift_cell_color,
                palette.text,
            )
    if closure is not None:
        day_type = day_types_by_id.get(closure.day_type_id)
        if day_type is not None:
            return day_type_codes.get(closure.day_type_id, "?"), day_type.color, _PRESET_TEXT
    return "", palette.surface, palette.text


def _draw_roster_grid(
    canvas: tk.Canvas,
    days: list[date],
    employees: list[Employee],
    assignments_by_employee: dict[int, dict[date, DailyShiftAssignment]],
    absences_by_employee: dict[int, dict[date, EmployeeAbsence]],
    closures: dict[date, DepartmentClosure],
    day_types_by_id: dict[int | None, DayType],
    shifts_by_id: dict[int | None, Shift],
    shift_codes: dict[int | None, str],
    day_type_codes: dict[int | None, str],
) -> tuple[int, int]:
    """Dibuja la rejilla completa (cabecera + nombres + celdas) directamente
    sobre un Canvas, en vez de un widget real (tk.Label/Button) por celda.
    Con cientos de celdas (empleados x días del mes) crear un widget real
    por celda resultó ser el cuello de botella real al cambiar de
    departamento -- perfilado aparte: ~400-750ms, casi todo en el propio
    paso de layout/render de Tk, no en las consultas (<2ms) ni en la propia
    creación de los widgets. Dibujar como items de canvas (rectángulo +
    texto) en su lugar es ~15-20 veces más rápido para el mismo número de
    celdas, porque un item de canvas no es una ventana real y no arrastra
    esa maquinaria. Devuelve (ancho_total, alto_total) en píxeles para que
    el llamador fije el scrollregion tras dibujar."""
    canvas.delete("all")
    palette = theme.current()
    today = date.today()

    total_width = _NAME_COL_WIDTH_PX + len(days) * _DAY_COL_WIDTH_PX
    total_height = _GRID_HEADER_PX + max(len(employees), 1) * _GRID_ROW_PX

    canvas.create_rectangle(
        0, 0, _NAME_COL_WIDTH_PX, _GRID_HEADER_PX, fill=palette.bg, outline=palette.border
    )
    canvas.create_text(
        4, _GRID_HEADER_PX / 2, text="Empleado", anchor="w",
        font=("TkDefaultFont", 9, "bold"), fill=palette.text,
    )
    for col, day in enumerate(days):
        x0 = _NAME_COL_WIDTH_PX + col * _DAY_COL_WIDTH_PX
        x1 = x0 + _DAY_COL_WIDTH_PX
        bg = palette.today_highlight if day == today else palette.bg
        canvas.create_rectangle(x0, 0, x1, _GRID_HEADER_PX, fill=bg, outline=palette.border)
        canvas.create_text(
            (x0 + x1) / 2, _GRID_HEADER_PX / 4, text=str(day.day),
            font=("TkDefaultFont", 8, "bold"), fill=palette.text,
        )
        canvas.create_text(
            (x0 + x1) / 2, _GRID_HEADER_PX * 3 / 4,
            text=WEEKDAY_LABELS[day.isoweekday() - 1],
            font=("TkDefaultFont", 7), fill=palette.text,
        )

    if not employees:
        canvas.create_text(
            8, _GRID_HEADER_PX + 16,
            text="Este departamento no tiene empleados activos.",
            anchor="w", fill=palette.text,
        )
        return total_width, total_height

    for row, employee in enumerate(employees):
        y0 = _GRID_HEADER_PX + row * _GRID_ROW_PX
        y1 = y0 + _GRID_ROW_PX
        canvas.create_rectangle(
            0, y0, _NAME_COL_WIDTH_PX, y1, fill=palette.surface, outline=palette.border
        )
        canvas.create_text(
            4, (y0 + y1) / 2, text=employee.full_name, anchor="w", fill=palette.text
        )
        assert employee.id is not None
        employee_assignments = assignments_by_employee.get(employee.id, {})
        employee_absences = absences_by_employee.get(employee.id, {})
        for col, day in enumerate(days):
            x0 = _NAME_COL_WIDTH_PX + col * _DAY_COL_WIDTH_PX
            x1 = x0 + _DAY_COL_WIDTH_PX
            text, bg, fg = _resolve_cell_display(
                absence=employee_absences.get(day),
                assignment=employee_assignments.get(day),
                closure=closures.get(day),
                day_types_by_id=day_types_by_id,
                shifts_by_id=shifts_by_id,
                shift_codes=shift_codes,
                day_type_codes=day_type_codes,
            )
            canvas.create_rectangle(x0, y0, x1, y1, fill=bg, outline=palette.border)
            if text:
                canvas.create_text(
                    (x0 + x1) / 2, (y0 + y1) / 2, text=text,
                    font=("TkDefaultFont", 7), fill=fg,
                )
    return total_width, total_height


def _render_legend(
    parent: ttk.Frame,
    shifts: list[Shift],
    day_types: list[DayType],
    shift_codes: dict[int | None, str],
    day_type_codes: dict[int | None, str],
) -> None:
    for widget in parent.winfo_children():
        widget.destroy()
    palette = theme.current()

    shift_row = ttk.Frame(parent)
    shift_row.pack(side="top", fill="x", anchor="w")
    ttk.Label(shift_row, text="Turnos:", font=("TkDefaultFont", 8, "bold")).pack(side="left")
    if not shifts:
        ttk.Label(shift_row, text=" (ninguno)", style="Muted.TLabel").pack(side="left")
    for shift in shifts:
        tk.Label(
            shift_row, text=shift_codes.get(shift.id, "?"), bg=palette.shift_cell_color,
            fg=palette.text, width=4, font=("TkDefaultFont", 7),
        ).pack(side="left", padx=(8, 2))
        ttk.Label(shift_row, text=f"{shift.name} ({shift.schedule_display})").pack(side="left")

    type_row = ttk.Frame(parent)
    type_row.pack(side="top", fill="x", anchor="w", pady=(2, 0))
    ttk.Label(type_row, text="Tipos de día:", font=("TkDefaultFont", 8, "bold")).pack(side="left")
    if not day_types:
        ttk.Label(type_row, text=" (ninguno)", style="Muted.TLabel").pack(side="left")
    for day_type in day_types:
        tk.Label(
            type_row, text=day_type_codes.get(day_type.id, "?"), bg=day_type.color,
            fg=_PRESET_TEXT, width=4, font=("TkDefaultFont", 7),
        ).pack(side="left", padx=(8, 2))
        ttk.Label(type_row, text=day_type.name).pack(side="left")


class CalendarPage(ttk.Frame):
    """Página única embebida en la ventana principal para el calendario
    laboral -- sustituye a las antiguas ventanas emergentes por departamento
    y por empleado. `show_department`/`show_employee` cambian qué se ve;
    solo los formularios puntuales (asignar turno, marcar ausencia/cierre,
    editar una celda, gestionar turnos) siguen abriéndose como ventanas."""

    def __init__(self, parent: tk.Misc, repos: Repositories) -> None:
        super().__init__(parent)
        self._repos = repos
        self._mode = "department"
        self._department: Department | None = None
        self._employee: Employee | None = None

        today = date.today()
        self._view_year = today.year
        self._view_month = today.month
        # Estado de la última rejilla dibujada, para que el único manejador
        # de clic del canvas pueda traducir una coordenada de píxel de
        # vuelta a (día, empleado) -- ver _handle_grid_click.
        self._current_days: list[date] = []
        self._current_employees: list[Employee] = []

        self._title_label = ttk.Label(
            self, style="PageHeading.TLabel", padding=(12, 12, 12, 4)
        )
        self._title_label.pack(side="top", fill="x", anchor="w")

        toolbar = ttk.Frame(self, padding=(12, 0, 12, 8))
        toolbar.pack(side="top", fill="x")
        ttk.Button(toolbar, text="<", width=3, command=self._go_previous_month).pack(side="left")
        self._month_label = ttk.Label(toolbar, width=18, anchor="center")
        self._month_label.pack(side="left", padx=4)
        ttk.Button(toolbar, text=">", width=3, command=self._go_next_month).pack(side="left")
        self._actions_frame = ttk.Frame(toolbar)
        self._actions_frame.pack(side="left")

        self._scroll = ScrollableFrame2D(self, height=_GRID_MIN_HEIGHT, bg=theme.current().surface)
        self._scroll.pack(side="top", fill="both", expand=True, padx=12, pady=(4, 0))
        self._scroll.canvas.bind("<Button-1>", self._handle_grid_click)

        self._legend_frame = ttk.Frame(self, padding=(12, 8, 12, 8))
        self._legend_frame.pack(side="top", fill="x")

    def show_department(self, department: Department) -> None:
        self._mode = "department"
        self._department = department
        self._employee = None
        today = date.today()
        self._view_year, self._view_month = today.year, today.month
        self._rebuild_actions()
        self._refresh()

    def show_employee(self, employee: Employee) -> None:
        self._mode = "employee"
        self._employee = employee
        self._department = None
        today = date.today()
        self._view_year, self._view_month = today.year, today.month
        self._rebuild_actions()
        self._refresh()

    def _rebuild_actions(self) -> None:
        for widget in self._actions_frame.winfo_children():
            widget.destroy()
        if self._mode == "department":
            ttk.Button(
                self._actions_frame, text="Gestionar turnos...", command=self._open_shift_manager
            ).pack(side="left", padx=(16, 4))
            ttk.Button(
                self._actions_frame, text="Asignar turno...", command=self._open_assign_shift
            ).pack(side="left", padx=4)
            ttk.Button(
                self._actions_frame,
                text="Aplicar rotación...",
                command=self._open_assign_shift_rotation,
            ).pack(side="left", padx=4)
            ttk.Button(
                self._actions_frame, text="Marcar ausencia...", command=self._open_mark_absence
            ).pack(side="left", padx=4)
            ttk.Button(
                self._actions_frame,
                text="Solicitar ausencia...",
                command=self._open_request_absence,
            ).pack(side="left", padx=4)
            ttk.Button(
                self._actions_frame, text="Marcar cierre...", command=self._open_mark_closure
            ).pack(side="left", padx=4)
        else:
            ttk.Button(
                self._actions_frame, text="Asignar turno...", command=self._open_assign_shift
            ).pack(side="left", padx=(16, 4))
            ttk.Button(
                self._actions_frame,
                text="Aplicar rotación...",
                command=self._open_assign_shift_rotation,
            ).pack(side="left", padx=4)
            ttk.Button(
                self._actions_frame, text="Marcar ausencia...", command=self._open_mark_absence
            ).pack(side="left", padx=4)
            ttk.Button(
                self._actions_frame,
                text="Solicitar ausencia...",
                command=self._open_request_absence,
            ).pack(side="left", padx=4)

    def _go_previous_month(self) -> None:
        self._view_year, self._view_month = shift_month(self._view_year, self._view_month, -1)
        self._refresh()

    def _go_next_month(self) -> None:
        self._view_year, self._view_month = shift_month(self._view_year, self._view_month, 1)
        self._refresh()

    def _refresh(self) -> None:
        if self._mode == "department" and self._department is not None:
            self._refresh_department()
        elif self._mode == "employee" and self._employee is not None:
            self._refresh_employee()

    def apply_theme_change(self) -> None:
        """Se llama tras un cambio de tema en caliente: el color de fondo
        del canvas se fija directamente, no vía ttk.Style, así que no se
        actualiza solo -- y _refresh() vuelve a dibujar toda la rejilla
        (rectángulos y texto de canvas) con los colores del tema ya activo."""
        self._scroll.set_bg(theme.current().surface)
        self._refresh()

    def _refresh_department(self) -> None:
        department = self._department
        assert department is not None and department.id is not None
        self._title_label.configure(text=f"Calendario laboral — {department.name}")
        self._month_label.configure(
            text=f"{MONTH_NAMES[self._view_month - 1]} {self._view_year}"
        )

        shifts = self._repos.shifts.list_for_department(department.id)
        day_types = self._repos.day_types.list_all()
        shift_codes = _code_map([s.id for s in shifts], "T")
        day_type_codes = _code_map([dt.id for dt in day_types], "D")
        shifts_by_id = {s.id: s for s in shifts}
        day_types_by_id = {dt.id: dt for dt in day_types}

        _render_legend(self._legend_frame, shifts, day_types, shift_codes, day_type_codes)

        employees = sorted(
            self._repos.employees.search(department_id=department.id, active_only=True),
            key=lambda e: e.full_name,
        )
        self._scroll.set_height(_grid_height(len(employees)))

        days = _days_in_month(self._view_year, self._view_month)

        closures = self._repos.closures.get_for_month(
            department.id, self._view_year, self._view_month
        )

        assignments_by_employee: dict[int, dict[date, DailyShiftAssignment]] = {}
        for assignment in self._repos.daily_assignments.get_for_department_month(
            department.id, self._view_year, self._view_month
        ):
            assignments_by_employee.setdefault(assignment.employee_id, {})[
                assignment.assignment_date
            ] = assignment

        absences_by_employee: dict[int, dict[date, EmployeeAbsence]] = {}
        for absence in self._repos.absences.list_for_department_month(
            department.id, self._view_year, self._view_month
        ):
            absences_by_employee.setdefault(absence.employee_id, {})[
                absence.absence_date
            ] = absence

        self._current_days = days
        self._current_employees = employees
        width, height = _draw_roster_grid(
            self._scroll.canvas,
            days,
            employees,
            assignments_by_employee,
            absences_by_employee,
            closures,
            day_types_by_id,
            shifts_by_id,
            shift_codes,
            day_type_codes,
        )
        self._scroll.canvas.configure(scrollregion=(0, 0, width, height))

    def _refresh_employee(self) -> None:
        assert self._employee is not None and self._employee.id is not None
        employee = self._repos.employees.get(self._employee.id)
        self._title_label.configure(text=f"Calendario — {employee.full_name}")
        self._month_label.configure(
            text=f"{MONTH_NAMES[self._view_month - 1]} {self._view_year}"
        )

        shifts = self._repos.shifts.list_for_department(employee.department_id)
        day_types = self._repos.day_types.list_all()
        shift_codes = _code_map([s.id for s in shifts], "T")
        day_type_codes = _code_map([dt.id for dt in day_types], "D")
        shifts_by_id = {s.id: s for s in shifts}
        day_types_by_id = {dt.id: dt for dt in day_types}

        _render_legend(self._legend_frame, shifts, day_types, shift_codes, day_type_codes)
        self._scroll.set_height(_grid_height(1))

        days = _days_in_month(self._view_year, self._view_month)
        closures = self._repos.closures.get_for_month(
            employee.department_id, self._view_year, self._view_month
        )
        assert employee.id is not None
        assignments = self._repos.daily_assignments.get_for_month(
            employee.id, self._view_year, self._view_month
        )
        absences = self._repos.absences.get_for_month(
            employee.id, self._view_year, self._view_month
        )

        self._current_days = days
        self._current_employees = [employee]
        width, height = _draw_roster_grid(
            self._scroll.canvas,
            days,
            [employee],
            {employee.id: assignments},
            {employee.id: absences},
            closures,
            day_types_by_id,
            shifts_by_id,
            shift_codes,
            day_type_codes,
        )
        self._scroll.canvas.configure(scrollregion=(0, 0, width, height))

    def _open_cell(self, day: date, employee: Employee) -> None:
        DayCellDialog(self.winfo_toplevel(), day, employee, self._repos, on_change=self._refresh)

    def _handle_grid_click(self, event: tk.Event) -> None:
        # Un único manejador en el canvas (no un bind por celda): hay que
        # traducir la coordenada del clic, relativa al widget visible, a
        # coordenada de contenido del canvas -- canvasx/canvasy tienen en
        # cuenta el desplazamiento actual del scroll, que event.x/event.y
        # por sí solos ignoran.
        canvas = self._scroll.canvas
        x = canvas.canvasx(event.x)
        y = canvas.canvasy(event.y)
        if x < _NAME_COL_WIDTH_PX or y < _GRID_HEADER_PX:
            return
        col = int((x - _NAME_COL_WIDTH_PX) // _DAY_COL_WIDTH_PX)
        row = int((y - _GRID_HEADER_PX) // _GRID_ROW_PX)
        if 0 <= row < len(self._current_employees) and 0 <= col < len(self._current_days):
            self._open_cell(self._current_days[col], self._current_employees[row])

    def _open_shift_manager(self) -> None:
        assert self._department is not None
        ShiftManagerDialog(
            self.winfo_toplevel(), self._repos, self._department, on_change=self._refresh
        )

    def _open_mark_closure(self) -> None:
        assert self._department is not None
        if not self._repos.day_types.list_all():
            messagebox.showinfo(
                "Sin tipos de día",
                "Cree al menos un tipo de día (ej. Festivo) antes de marcar un cierre.",
                parent=self.winfo_toplevel(),
            )
            return
        MarkClosureRangeDialog(
            self.winfo_toplevel(), self._repos, self._department, on_change=self._refresh
        )

    def _action_targets(self) -> tuple[list[Employee], list[Shift], int | None]:
        if self._department is not None:
            assert self._department.id is not None
            employees = self._repos.employees.search(
                department_id=self._department.id, active_only=True
            )
            shifts = self._repos.shifts.list_for_department(self._department.id)
            return employees, shifts, None
        assert self._employee is not None and self._employee.id is not None
        employee = self._repos.employees.get(self._employee.id)
        shifts = self._repos.shifts.list_for_department(employee.department_id)
        # Igual que el modo departamento (active_only=True arriba): no se
        # puede asignar turno ni marcar ausencia a un empleado ya de baja
        # desde su propio calendario individual -- antes era la única
        # forma de seguir escribiendo en el calendario de alguien inactivo,
        # inconsistente con el modo departamento, que ya lo impedía.
        if not employee.active:
            return [], shifts, None
        return [employee], shifts, employee.id

    def _open_assign_shift(self) -> None:
        employees, shifts, initial_id = self._action_targets()
        if not employees:
            messagebox.showinfo(
                "Sin empleados",
                "Este departamento no tiene empleados activos.",
                parent=self.winfo_toplevel(),
            )
            return
        if not shifts:
            messagebox.showinfo(
                "Sin turnos",
                "Cree al menos un turno antes de asignar días.",
                parent=self.winfo_toplevel(),
            )
            return
        AssignShiftRangeDialog(
            self.winfo_toplevel(),
            self._repos,
            employees,
            shifts,
            on_change=self._refresh,
            initial_employee_id=initial_id,
        )

    def _open_assign_shift_rotation(self) -> None:
        employees, shifts, initial_id = self._action_targets()
        if not employees:
            messagebox.showinfo(
                "Sin empleados",
                "Este departamento no tiene empleados activos.",
                parent=self.winfo_toplevel(),
            )
            return
        if not shifts:
            messagebox.showinfo(
                "Sin turnos",
                "Cree al menos un turno antes de aplicar una rotación.",
                parent=self.winfo_toplevel(),
            )
            return
        AssignShiftRotationDialog(
            self.winfo_toplevel(),
            self._repos,
            employees,
            shifts,
            on_change=self._refresh,
            initial_employee_id=initial_id,
        )

    def _open_mark_absence(self) -> None:
        employees, _shifts, initial_id = self._action_targets()
        if not employees:
            messagebox.showinfo(
                "Sin empleados",
                "Este departamento no tiene empleados activos.",
                parent=self.winfo_toplevel(),
            )
            return
        if not self._repos.day_types.list_all():
            messagebox.showinfo(
                "Sin tipos de día",
                "Cree al menos un tipo de día (ej. Vacaciones) antes de marcar ausencias.",
                parent=self.winfo_toplevel(),
            )
            return
        MarkAbsenceRangeDialog(
            self.winfo_toplevel(),
            self._repos,
            employees,
            on_change=self._refresh,
            initial_employee_id=initial_id,
        )

    def _open_request_absence(self) -> None:
        employees, _shifts, initial_id = self._action_targets()
        if not employees:
            messagebox.showinfo(
                "Sin empleados",
                "Este departamento no tiene empleados activos.",
                parent=self.winfo_toplevel(),
            )
            return
        if not self._repos.day_types.list_all():
            messagebox.showinfo(
                "Sin tipos de día",
                "Cree al menos un tipo de día (ej. Vacaciones) antes de solicitar ausencias.",
                parent=self.winfo_toplevel(),
            )
            return
        RequestAbsenceRangeDialog(
            self.winfo_toplevel(),
            self._repos,
            employees,
            on_change=self._refresh,
            initial_employee_id=initial_id,
        )
