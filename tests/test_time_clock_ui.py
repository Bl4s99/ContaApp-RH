from __future__ import annotations

import sqlite3
import tkinter as tk
from datetime import date, datetime

from app.repository import EmployeeInput, Repositories
from app.time_clock_ui import TimeClockPage, TimeEntryDialog, _format_elapsed

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


class TestFormatElapsed:
    def test_under_an_hour(self) -> None:
        assert _format_elapsed(15 * 60) == "15m"

    def test_over_an_hour(self) -> None:
        assert _format_elapsed(3 * 3600 + 12 * 60) == "3h 12m"

    def test_zero(self) -> None:
        assert _format_elapsed(0) == "0m"


class TestTimeClockPage:
    def _build_repos(self, conn: sqlite3.Connection) -> Repositories:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        repos.employees.create(
            EmployeeInput(
                first_name="Ana",
                last_name="García",
                email="ana@example.com",
                phone="",
                position="Comercial",
                department_id=dept.id,
                salary=25000,
                hire_date="2024-01-01",
            )
        )
        return repos

    def test_starts_not_clocked_in(self, tk_root: tk.Tk, conn: sqlite3.Connection) -> None:
        repos = self._build_repos(conn)
        page = TimeClockPage(tk_root, repos)
        assert "no está fichado" in page.status_label.cget("text")
        assert "disabled" not in page.clock_in_button.state()
        assert "disabled" in page.clock_out_button.state()
        page.destroy()

    def test_clock_in_updates_status_and_button_states(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = self._build_repos(conn)
        page = TimeClockPage(tk_root, repos)
        page._handle_clock_in()
        assert "está fichado" in page.status_label.cget("text")
        assert "disabled" in page.clock_in_button.state()
        assert "disabled" not in page.clock_out_button.state()
        page.destroy()

    def test_clock_in_twice_shows_error(self, tk_root: tk.Tk, conn: sqlite3.Connection) -> None:
        repos = self._build_repos(conn)
        page = TimeClockPage(tk_root, repos)
        page._handle_clock_in()
        page._handle_clock_in()
        assert page.kiosk_error_label.cget("text") != ""
        page.destroy()

    def test_clock_out_after_in_clears_status(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = self._build_repos(conn)
        page = TimeClockPage(tk_root, repos)
        page._handle_clock_in()
        page._handle_clock_out()
        assert "no está fichado" in page.status_label.cget("text")
        page.destroy()

    def test_clock_in_populates_month_table(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = self._build_repos(conn)
        page = TimeClockPage(tk_root, repos)
        page._handle_clock_in()
        assert len(page.tree.get_children()) == 1
        page.destroy()

    def test_no_employees_disables_kiosk(self, tk_root: tk.Tk, conn: sqlite3.Connection) -> None:
        repos = Repositories.create(conn)
        page = TimeClockPage(tk_root, repos)
        assert page.status_label.cget("text") == "Seleccione un empleado."
        assert "disabled" in page.clock_in_button.state()
        assert "disabled" in page.clock_out_button.state()
        page.destroy()

    def test_overnight_shift_across_month_boundary_counts_in_both_month_views(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        # Regresión: el total de horas de este mes se calculaba a partir de
        # TimeEntryRepository.list_for_month() (acotado por mes ANTES de
        # emparejar entrada/salida) -- un turno que empezaba el último día
        # de un mes y terminaba al principio del siguiente no contaba horas
        # en NINGÚN mes. Ver time_tracking.total_worked_hours_in_range().
        repos = self._build_repos(conn)
        employee = repos.employees.search()[0]
        assert employee.id is not None
        repos.time_entries.create_manual(employee.id, "entrada", datetime(2026, 1, 31, 22, 0))
        repos.time_entries.create_manual(employee.id, "salida", datetime(2026, 2, 1, 6, 0))

        page = TimeClockPage(tk_root, repos)
        page._current_employee = employee
        page._view_year, page._view_month = 2026, 1
        page._refresh_month_table()
        assert "8.00 h" in page.total_label.cget("text")

        page._view_year, page._view_month = 2026, 2
        page._refresh_month_table()
        assert "0.00 h" in page.total_label.cget("text")
        page.destroy()


class TestTimeEntryDialogMarkedDates:
    def test_marks_the_employees_departments_closures(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
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

        dialog = TimeEntryDialog(tk_root, repos, employee, on_change=lambda: None)

        assert dialog.date_entry._marked_dates == frozenset({closure_date})
        dialog.destroy()
