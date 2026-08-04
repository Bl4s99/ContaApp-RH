from __future__ import annotations

import sqlite3
import tkinter as tk
import tkinter.messagebox as messagebox
from datetime import date

import pytest

from app.repository import DailyAssignmentRepository, EmployeeInput, Repositories, ShiftInput
from app.schedule_ui import (
    AssignShiftRangeDialog,
    AssignShiftRotationDialog,
    MarkAbsenceRangeDialog,
    MarkClosureRangeDialog,
    RequestAbsenceRangeDialog,
    ShiftManagerDialog,
)

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


class TestShiftManagerDialogDelete:
    def test_deleting_a_shift_in_use_shows_an_error_instead_of_crashing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regresión: _handle_delete() llamaba a shifts.delete() sin
        # try/except -- borrar un turno con días ya asignados en el
        # calendario (el caso normal, no el raro) lanzaba
        # ReferenceInUseError sin capturar, y como Tkinter usa su
        # manejador de excepciones por defecto para errores de callback,
        # el fallo era 100% silencioso (el turno seguía existiendo,
        # on_change nunca se llamaba).
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        shift = repos.shifts.create(
            ShiftInput(
                department_id=dept.id,
                name="Turno mañana",
                start_time="09:00",
                end_time="17:00",
                days_of_week=frozenset({1, 2, 3, 4, 5}),
            )
        )
        assert shift.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana",
                last_name="Lopez",
                email="ana@example.com",
                phone="",
                position="Comercial",
                department_id=dept.id,
                salary=25000,
                hire_date="2024-01-01",
            )
        )
        assert employee.id is not None
        DailyAssignmentRepository(conn).set_day(employee.id, date(2026, 3, 2), shift.id)

        changed = []
        dialog = ShiftManagerDialog(tk_root, repos, dept, on_change=lambda: changed.append(1))
        dialog.listbox.selection_set(0)
        dialog._load_selected()

        dialog._handle_delete()

        assert repos.shifts.get(shift.id) is not None  # sigue existiendo
        assert changed == []  # on_change no se llamó
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()


class TestDateRangeDialogsMarkedDates:
    """Cada diálogo que registra/consulta días de un departamento debe pasar
    los cierres ya registrados a sus DateEntry (marked_dates), para que el
    selector resalte los festivos ya conocidos -- ver CalendarPopup."""

    def _build_department_with_closure(
        self, conn: sqlite3.Connection
    ) -> tuple[Repositories, int, int, date]:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        day_type = repos.day_types.create("Festivo", "#e74c3c")
        assert day_type.id is not None
        closure_date = date(2026, 12, 25)
        repos.closures.set_day(dept.id, closure_date, day_type.id)
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@example.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2024-01-01",
            )
        )
        assert employee.id is not None
        return repos, dept.id, employee.id, closure_date

    def test_mark_absence_range_dialog_marks_the_departments_closures(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, dept_id, employee_id, closure_date = self._build_department_with_closure(conn)
        day_type = repos.day_types.create("Vacaciones", "#2ecc71")
        assert day_type.id is not None
        dialog = MarkAbsenceRangeDialog(
            tk_root, repos, [repos.employees.get(employee_id)], on_change=lambda: None
        )
        assert dialog.start_entry._marked_dates == frozenset({closure_date})
        assert dialog.end_entry._marked_dates == frozenset({closure_date})
        dialog.destroy()

    def test_request_absence_range_dialog_marks_the_departments_closures(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, dept_id, employee_id, closure_date = self._build_department_with_closure(conn)
        dialog = RequestAbsenceRangeDialog(
            tk_root, repos, [repos.employees.get(employee_id)], on_change=lambda: None
        )
        assert dialog.start_entry._marked_dates == frozenset({closure_date})
        assert dialog.end_entry._marked_dates == frozenset({closure_date})
        dialog.destroy()

    def test_mark_closure_range_dialog_marks_the_departments_closures(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, dept_id, _employee_id, closure_date = self._build_department_with_closure(conn)
        dept = repos.departments.get(dept_id)
        dialog = MarkClosureRangeDialog(tk_root, repos, dept, on_change=lambda: None)
        assert dialog.start_entry._marked_dates == frozenset({closure_date})
        assert dialog.end_entry._marked_dates == frozenset({closure_date})
        dialog.destroy()

    def test_assign_shift_range_dialog_marks_the_departments_closures(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, dept_id, employee_id, closure_date = self._build_department_with_closure(conn)
        shift = repos.shifts.create(
            ShiftInput(
                department_id=dept_id, name="Turno mañana", start_time="09:00", end_time="17:00",
                days_of_week=frozenset({1, 2, 3, 4, 5}),
            )
        )
        dialog = AssignShiftRangeDialog(
            tk_root,
            repos,
            [repos.employees.get(employee_id)],
            [shift],
            on_change=lambda: None,
        )
        assert dialog.start_entry._marked_dates == frozenset({closure_date})
        assert dialog.end_entry._marked_dates == frozenset({closure_date})
        dialog.destroy()

    def test_assign_shift_rotation_dialog_marks_the_departments_closures(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, dept_id, employee_id, closure_date = self._build_department_with_closure(conn)
        shift = repos.shifts.create(
            ShiftInput(
                department_id=dept_id, name="Turno mañana", start_time="09:00", end_time="17:00",
                days_of_week=frozenset({1, 2, 3, 4, 5}),
            )
        )
        dialog = AssignShiftRotationDialog(
            tk_root,
            repos,
            [repos.employees.get(employee_id)],
            [shift],
            on_change=lambda: None,
        )
        assert dialog.start_entry._marked_dates == frozenset({closure_date})
        assert dialog.end_entry._marked_dates == frozenset({closure_date})
        dialog.destroy()

    def test_dialogs_show_no_marks_for_a_department_with_no_closures(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Sin cierres")
        assert dept.id is not None
        dialog = MarkClosureRangeDialog(tk_root, repos, dept, on_change=lambda: None)
        assert dialog.start_entry._marked_dates == frozenset()
        dialog.destroy()


class TestAssignShiftRotationDialog:
    def _build_employee_with_shifts(
        self, conn: sqlite3.Connection
    ) -> tuple[Repositories, int, int, int]:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Hospital")
        assert dept.id is not None
        all_days = frozenset({1, 2, 3, 4, 5, 6, 7})
        morning = repos.shifts.create(
            ShiftInput(
                department_id=dept.id, name="Mañana", start_time="08:00", end_time="16:00",
                days_of_week=all_days,
            )
        )
        afternoon = repos.shifts.create(
            ShiftInput(
                department_id=dept.id, name="Tarde", start_time="16:00", end_time="00:00",
                days_of_week=all_days,
            )
        )
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Ruiz", email="ana@example.com", phone="",
                position="Enfermera", department_id=dept.id, salary=25000,
                hire_date="2020-01-01",
            )
        )
        assert employee.id is not None and morning.id is not None and afternoon.id is not None
        return repos, employee.id, morning.id, afternoon.id

    def test_adding_to_the_pattern_updates_the_list_and_the_listbox(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id, morning_id, afternoon_id = self._build_employee_with_shifts(conn)
        dialog = AssignShiftRotationDialog(
            tk_root,
            repos,
            [repos.employees.get(employee_id)],
            [repos.shifts.get(morning_id), repos.shifts.get(afternoon_id)],
            on_change=lambda: None,
        )
        dialog.add_combo.current(1)  # Mañana
        dialog._handle_add_to_pattern()
        dialog.add_combo.current(0)  # Descanso
        dialog._handle_add_to_pattern()

        assert dialog._pattern == [morning_id, None]
        assert dialog.pattern_listbox.size() == 2
        assert dialog.pattern_listbox.get(0) == "1. Mañana"
        dialog.destroy()

    def test_removing_the_last_element_shrinks_the_pattern_and_the_listbox(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id, morning_id, afternoon_id = self._build_employee_with_shifts(conn)
        dialog = AssignShiftRotationDialog(
            tk_root,
            repos,
            [repos.employees.get(employee_id)],
            [repos.shifts.get(morning_id), repos.shifts.get(afternoon_id)],
            on_change=lambda: None,
        )
        dialog.add_combo.current(1)
        dialog._handle_add_to_pattern()
        dialog.add_combo.current(2)
        dialog._handle_add_to_pattern()

        dialog._handle_remove_last_from_pattern()

        assert dialog._pattern == [morning_id]
        assert dialog.pattern_listbox.size() == 1
        dialog.destroy()

    def test_removing_from_an_empty_pattern_is_a_no_op(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id, morning_id, afternoon_id = self._build_employee_with_shifts(conn)
        dialog = AssignShiftRotationDialog(
            tk_root,
            repos,
            [repos.employees.get(employee_id)],
            [repos.shifts.get(morning_id), repos.shifts.get(afternoon_id)],
            on_change=lambda: None,
        )
        dialog._handle_remove_last_from_pattern()
        assert dialog._pattern == []
        dialog.destroy()

    def test_saving_with_an_empty_pattern_shows_an_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id, morning_id, afternoon_id = self._build_employee_with_shifts(conn)
        dialog = AssignShiftRotationDialog(
            tk_root,
            repos,
            [repos.employees.get(employee_id)],
            [repos.shifts.get(morning_id), repos.shifts.get(afternoon_id)],
            on_change=lambda: None,
            initial_employee_id=employee_id,
        )
        dialog.start_entry.value_var.set("2026-08-01")
        dialog.end_entry.value_var.set("2026-08-05")
        dialog._handle_save()
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()

    def test_saving_with_no_employee_selected_shows_an_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id, morning_id, afternoon_id = self._build_employee_with_shifts(conn)
        dialog = AssignShiftRotationDialog(
            tk_root,
            repos,
            [repos.employees.get(employee_id)],
            [repos.shifts.get(morning_id), repos.shifts.get(afternoon_id)],
            on_change=lambda: None,
        )
        dialog.add_combo.current(1)
        dialog._handle_add_to_pattern()
        dialog.start_entry.value_var.set("2026-08-01")
        dialog.end_entry.value_var.set("2026-08-05")
        dialog._handle_save()
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()

    def test_saving_applies_the_rotation_and_notifies_on_change(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
        repos, employee_id, morning_id, afternoon_id = self._build_employee_with_shifts(conn)
        dialog = AssignShiftRotationDialog(
            tk_root,
            repos,
            [repos.employees.get(employee_id)],
            [repos.shifts.get(morning_id), repos.shifts.get(afternoon_id)],
            on_change=lambda: None,
            initial_employee_id=employee_id,
        )
        dialog.add_combo.current(1)  # Mañana
        dialog._handle_add_to_pattern()
        dialog.add_combo.current(0)  # Descanso
        dialog._handle_add_to_pattern()
        dialog.start_entry.value_var.set("2026-08-01")
        dialog.end_entry.value_var.set("2026-08-04")

        changed = []
        dialog._on_change = lambda: changed.append(True)
        dialog._handle_save()

        assert changed == [True]
        assignments = repos.daily_assignments.get_for_month(employee_id, 2026, 8)
        assert assignments[date(2026, 8, 1)].shift_id == morning_id
        assert date(2026, 8, 2) not in assignments
        assert assignments[date(2026, 8, 3)].shift_id == morning_id
        assert date(2026, 8, 4) not in assignments
