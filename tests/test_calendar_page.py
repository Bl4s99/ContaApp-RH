from __future__ import annotations

import sqlite3
import tkinter as tk

from app.calendar_page import CalendarPage
from app.repository import EmployeeInput, Repositories

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


class TestActionTargets:
    def _build_repos_and_employee(
        self, conn: sqlite3.Connection, *, terminate: bool = False
    ) -> tuple[Repositories, int]:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@example.com", phone="",
                position="Comercial", department_id=dept.id, salary=24000,
                hire_date="2020-01-01",
            )
        )
        assert employee.id is not None
        if terminate:
            repos.employees.terminate(employee.id, "2024-06-30", "Baja voluntaria")
        return repos, employee.id

    def test_active_employee_is_a_valid_target_from_their_own_calendar(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = self._build_repos_and_employee(conn)
        page = CalendarPage(tk_root, repos)
        page.show_employee(repos.employees.get(employee_id))

        employees, _shifts, initial_id = page._action_targets()

        assert [e.id for e in employees] == [employee_id]
        assert initial_id == employee_id
        page.destroy()

    def test_inactive_employee_is_not_a_valid_target_from_their_own_calendar(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        # Regresión: el modo departamento ya filtraba por active_only=True,
        # pero el modo empleado no comprobaba employee.active en absoluto
        # -- se podía seguir asignando turno o marcando ausencias a un
        # empleado ya de baja desde su propio calendario individual.
        repos, employee_id = self._build_repos_and_employee(conn, terminate=True)
        page = CalendarPage(tk_root, repos)
        page.show_employee(repos.employees.get(employee_id))

        employees, _shifts, initial_id = page._action_targets()

        assert employees == []
        assert initial_id is None
        page.destroy()
