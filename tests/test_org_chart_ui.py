from __future__ import annotations

import sqlite3
import tkinter as tk

from app.org_chart_ui import OrgChartPage
from app.repository import EmployeeInput, Repositories

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


def _make_employee(
    repos: Repositories, department_id: int, email: str, **overrides: object
) -> int:
    fields: dict[str, object] = dict(
        first_name=email.split("@")[0].capitalize(), last_name="Test", email=email,
        phone="", position="Comercial", department_id=department_id, salary=25000,
        hire_date="2022-01-01",
    )
    fields.update(overrides)
    employee = repos.employees.create(EmployeeInput(**fields))  # type: ignore[arg-type]
    assert employee.id is not None
    return employee.id


class TestOrgChartTreeStructure:
    def test_employees_with_no_manager_are_roots(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        ana_id = _make_employee(repos, dept.id, "ana@x.com")
        bob_id = _make_employee(repos, dept.id, "bob@x.com")

        page = OrgChartPage(tk_root, repos)
        assert set(page.tree.get_children("")) == {str(ana_id), str(bob_id)}
        page.destroy()

    def test_direct_reports_nest_under_their_manager(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        ana_id = _make_employee(repos, dept.id, "ana@x.com")
        bob_id = _make_employee(repos, dept.id, "bob@x.com", manager_id=ana_id)
        carla_id = _make_employee(repos, dept.id, "carla@x.com", manager_id=ana_id)
        dora_id = _make_employee(repos, dept.id, "dora@x.com", manager_id=bob_id)

        page = OrgChartPage(tk_root, repos)
        assert page.tree.get_children("") == (str(ana_id),)
        assert set(page.tree.get_children(str(ana_id))) == {str(bob_id), str(carla_id)}
        assert page.tree.get_children(str(bob_id)) == (str(dora_id),)
        assert page.tree.get_children(str(carla_id)) == ()
        page.destroy()

    def test_tree_row_shows_full_name_and_position(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        ana_id = _make_employee(repos, dept.id, "ana@x.com", position="Directora de Ventas")

        page = OrgChartPage(tk_root, repos)
        assert page.tree.item(str(ana_id), "text") == "Ana Test"
        assert page.tree.item(str(ana_id), "values") == ("Directora de Ventas",)
        page.destroy()

    def test_inactive_employees_are_excluded_entirely(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        ana_id = _make_employee(repos, dept.id, "ana@x.com")
        repos.employees.terminate(ana_id, "2026-01-01", "Baja voluntaria")

        page = OrgChartPage(tk_root, repos)
        assert page.tree.get_children("") == ()
        page.destroy()

    def test_a_report_whose_manager_has_since_left_becomes_a_root(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        # Regresión: manager_id no se limpia al dar de baja (solo al
        # eliminar por completo, vía ON DELETE SET NULL) -- el árbol debe
        # tratar a un supervisor ya inactivo como si no estuviera, en vez
        # de fallar o de ocultar en silencio a quien le reportaba.
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        ana_id = _make_employee(repos, dept.id, "ana@x.com")
        bob_id = _make_employee(repos, dept.id, "bob@x.com", manager_id=ana_id)
        repos.employees.terminate(ana_id, "2026-01-01", "Baja voluntaria")

        page = OrgChartPage(tk_root, repos)
        assert page.tree.get_children("") == (str(bob_id),)
        page.destroy()

    def test_departments_are_isolated_from_each_other(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        dept2 = repos.departments.create("Marketing")
        assert dept.id is not None and dept2.id is not None
        ana_id = _make_employee(repos, dept.id, "ana@x.com")
        fran_id = _make_employee(repos, dept2.id, "fran@x.com")

        page = OrgChartPage(tk_root, repos)
        page.department_filter_var.set("Ventas")
        page._render_tree()
        assert page.tree.get_children("") == (str(ana_id),)

        page.department_filter_var.set("Marketing")
        page._render_tree()
        assert page.tree.get_children("") == (str(fran_id),)
        page.destroy()


class TestOrgChartDepartmentLock:
    def test_locked_department_disables_the_filter_and_scopes_the_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        dept2 = repos.departments.create("Marketing")
        assert dept.id is not None and dept2.id is not None
        _make_employee(repos, dept.id, "ana@x.com")
        fran_id = _make_employee(repos, dept2.id, "fran@x.com")

        page = OrgChartPage(tk_root, repos, locked_department_id=dept2.id)
        assert str(page.department_filter_combo.cget("state")) == "disabled"
        assert page.tree.get_children("") == (str(fran_id),)
        page.destroy()

    def test_refresh_after_a_department_is_added_updates_the_filter_options(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None

        page = OrgChartPage(tk_root, repos)
        assert set(page.department_filter_combo["values"]) == {"Ventas"}

        repos.departments.create("Marketing")
        page.refresh()
        assert set(page.department_filter_combo["values"]) == {"Ventas", "Marketing"}
        page.destroy()
