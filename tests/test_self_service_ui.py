from __future__ import annotations

import sqlite3
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import ttk

from app.repository import EmployeeInput, Repositories
from app.self_service_ui import EmployeeAccessDialog, EmployeeSelfServiceWindow

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


def _build_employee_with_pin(conn: sqlite3.Connection, pin: str = "1234") -> tuple[Repositories, int]:
    repos = Repositories.create(conn)
    dept = repos.departments.create("Ventas")
    assert dept.id is not None
    employee = repos.employees.create(
        EmployeeInput(
            first_name="Ana", last_name="Ruiz", email="ana@example.com", phone="",
            position="Comercial", department_id=dept.id, salary=24000,
            hire_date="2020-01-01",
        )
    )
    assert employee.id is not None
    repos.employees.set_self_service_pin(employee.id, pin)
    return repos, employee.id


class TestEmployeeAccessDialog:
    def test_empty_fields_shows_error(self, tk_root: tk.Tk, conn: sqlite3.Connection) -> None:
        repos, _ = _build_employee_with_pin(conn)
        dialog = EmployeeAccessDialog(tk_root, repos)
        dialog._handle_access()
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()

    def test_wrong_pin_shows_generic_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _ = _build_employee_with_pin(conn)
        dialog = EmployeeAccessDialog(tk_root, repos)
        dialog.email_var.set("ana@example.com")
        dialog.pin_var.set("0000")
        dialog._handle_access()
        assert dialog.error_label.cget("text") == "Email o PIN incorrectos."
        dialog.destroy()

    def test_wrong_pin_clears_the_pin_field(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _ = _build_employee_with_pin(conn)
        dialog = EmployeeAccessDialog(tk_root, repos)
        dialog.email_var.set("ana@example.com")
        dialog.pin_var.set("0000")
        dialog._handle_access()
        assert dialog.pin_var.get() == ""
        dialog.destroy()

    def test_correct_credentials_closes_the_dialog_without_raising(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _ = _build_employee_with_pin(conn)
        dialog = EmployeeAccessDialog(tk_root, repos)
        dialog.email_var.set("ana@example.com")
        dialog.pin_var.set("1234")
        dialog._handle_access()  # must not raise; opens EmployeeSelfServiceWindow internally


class TestEmployeeSelfServiceWindow:
    def test_header_shows_name_and_position(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee_with_pin(conn)
        employee = repos.employees.get(employee_id)
        window = EmployeeSelfServiceWindow(tk_root, repos, employee)
        assert window.title() == "Mis datos — Ana Ruiz"
        window.destroy()

    def test_vacation_balance_reflects_real_data(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee_with_pin(conn)
        day_type = repos.day_types.create("Vacaciones", "#2ecc71", is_vacation=True)
        assert day_type.id is not None
        # mark_range() only marks days that fall on a working weekday for
        # this employee (Mon-Fri by default, no shift assigned) -- a fixed
        # calendar date like "March 1st" can silently land on a weekend in
        # some years and mark 0 days instead of 1. Walk forward from Jan 1st
        # of the current year to the first Mon-Fri day instead.
        target = date(date.today().year, 1, 1)
        while target.isoweekday() not in (1, 2, 3, 4, 5):
            target += timedelta(days=1)
        result = repos.absences.mark_range(employee_id, day_type.id, target, target)
        assert result.marked == 1
        employee = repos.employees.get(employee_id)
        window = EmployeeSelfServiceWindow(tk_root, repos, employee)

        labels = _collect_label_texts(window)
        joined = " | ".join(labels)
        assert "21 días disponibles de 22 (1 ya disfrutados este año)" in joined
        window.destroy()

    def test_no_payroll_yet_shows_the_empty_state_message(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee_with_pin(conn)
        employee = repos.employees.get(employee_id)
        window = EmployeeSelfServiceWindow(tk_root, repos, employee)
        labels = _collect_label_texts(window)
        assert "Todavía no hay ninguna nómina generada." in labels
        window.destroy()

    def test_generated_payroll_shows_bruto_and_neto(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee_with_pin(conn)
        repos.payroll_records.generate(employee_id, date.today().year, date.today().month)
        employee = repos.employees.get(employee_id)
        window = EmployeeSelfServiceWindow(tk_root, repos, employee)
        labels = _collect_label_texts(window)
        joined = " | ".join(labels)
        assert "NETO A PERCIBIR" in joined
        assert "Bruto del mes" in joined
        window.destroy()

    def test_fichajes_this_month_appear_in_the_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee_with_pin(conn)
        now = datetime.now()
        repos.time_entries.create_manual(employee_id, "entrada", now - timedelta(hours=2), "")
        repos.time_entries.create_manual(employee_id, "salida", now - timedelta(hours=1), "")
        employee = repos.employees.get(employee_id)
        window = EmployeeSelfServiceWindow(tk_root, repos, employee)

        tree = _find_treeview(window)
        assert tree is not None
        rows = [tree.item(iid, "values") for iid in tree.get_children()]
        assert len(rows) == 2
        assert {row[2] for row in rows} == {"Entrada", "Salida"}
        window.destroy()

    def test_no_fichajes_this_month_shows_zero_hours(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee_with_pin(conn)
        employee = repos.employees.get(employee_id)
        window = EmployeeSelfServiceWindow(tk_root, repos, employee)
        labels = _collect_label_texts(window)
        joined = " | ".join(labels)
        assert "Total trabajado este mes: 0 h 0 min" in joined
        window.destroy()


def _collect_label_texts(widget: tk.Misc) -> list[str]:
    texts: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, (ttk.Label,)):
            text = child.cget("text")
            if text:
                texts.append(text)
        texts.extend(_collect_label_texts(child))
    return texts


def _find_treeview(widget: tk.Misc) -> ttk.Treeview | None:
    for child in widget.winfo_children():
        if isinstance(child, ttk.Treeview):
            return child
        found = _find_treeview(child)
        if found is not None:
            return found
    return None
