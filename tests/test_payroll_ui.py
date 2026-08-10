from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import ttk

from app.payroll import estimate_irpf_withholding_rate
from app.repository import EmployeeInput, Repositories
from app.payroll_ui import GeneratePayrollDialog, PayrollPage

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


def _build_repos(conn: sqlite3.Connection) -> tuple[Repositories, int, int]:
    repos = Repositories.create(conn)
    dept = repos.departments.create("Ventas")
    assert dept.id is not None
    employee = repos.employees.create(
        EmployeeInput(
            first_name="Ana",
            last_name="Lopez",
            email="ana@example.com",
            phone="",
            position="Comercial",
            department_id=dept.id,
            salary=24000.0,
            dependent_children=0,
            hire_date="2022-01-01",
        )
    )
    assert employee.id is not None
    return repos, dept.id, employee.id


def _grid_cell_text(frame: ttk.Frame, row: int, column: int) -> str | None:
    for child in frame.winfo_children():
        if not isinstance(child, ttk.Label):
            continue
        info = child.grid_info()
        if int(info.get("row", -1)) == row and int(info.get("column", -1)) == column:
            text = child.cget("text")
            assert isinstance(text, str)
            return text
    return None


class TestPayrollPageSnapshotDisplay:
    def test_generated_payroll_shows_the_frozen_snapshot_not_the_current_salary(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        # Regresión: la cabecera de una nómina ya generada mostraba
        # employee.salary/dependent_children ACTUALES en vez de los
        # congelados en el snapshot (record.annual_gross_salary_snapshot/
        # dependent_children_snapshot) -- el snapshot en sí ya era correcto
        # e inmune a cambios posteriores, el problema era solo de
        # visualización: la cabecera mostraba un salario nuevo encima de un
        # desglose (paga ordinaria, IRPF, neto...) que seguía basado en el
        # antiguo.
        repos, dept_id, employee_id = _build_repos(conn)
        repos.payroll_records.generate(employee_id, 2026, 3)
        repos.employees.update(
            employee_id,
            EmployeeInput(
                first_name="Ana",
                last_name="Lopez",
                email="ana@example.com",
                phone="",
                position="Comercial",
                department_id=dept_id,
                salary=30000.0,
                dependent_children=2,
                hire_date="2022-01-01",
            ),
        )

        page = PayrollPage(tk_root, repos)
        page.tree.selection_set(str(employee_id))
        page._handle_selection_changed()
        page._view_year, page._view_month = 2026, 3
        page._render_breakdown()

        assert _grid_cell_text(page.breakdown_frame, 0, 1) == "24.000,00 €"
        assert _grid_cell_text(page.breakdown_frame, 1, 1) == "0"
        page.destroy()

    def test_live_estimate_still_shows_the_current_salary(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _dept_id, employee_id = _build_repos(conn)
        # No se genera ninguna nómina para este mes -- sigue siendo una
        # estimación en vivo, que sí debe reflejar el salario actual.
        page = PayrollPage(tk_root, repos)
        page.tree.selection_set(str(employee_id))
        page._handle_selection_changed()
        page._view_year, page._view_month = 2026, 3
        page._render_breakdown()

        assert _grid_cell_text(page.breakdown_frame, 0, 1) == "24.000,00 €"
        page.destroy()

    def test_breakdown_amounts_use_spanish_currency_formatting(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        # Regresión: cada importe de esta página se formateaba con
        # f"{v:,.2f} €" (coma de millar, punto decimal, estilo EE. UU.) en
        # vez del formato español (punto de millar, coma decimal) que usa
        # el resto de la app (lista de empleados, coste de personal,
        # plantillas de documentos) -- Nóminas era la única pantalla con
        # el formato equivocado.
        repos, _dept_id, employee_id = _build_repos(conn)
        page = PayrollPage(tk_root, repos)
        page.tree.selection_set(str(employee_id))
        page._handle_selection_changed()
        page._view_year, page._view_month = 2026, 3
        page._render_breakdown()

        # 24.000 / 14 pagas = 1.714,29 -- con punto de millar y coma
        # decimal (formato español), no "1,714.29" (formato EE. UU.).
        assert _grid_cell_text(page.breakdown_frame, 6, 1) == "1.714,29 €"
        page.destroy()


class TestPayrollPageReloadDepartmentsRace:
    def test_reload_departments_survives_the_locked_department_disappearing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        # Regresión: next(...) sin valor por defecto lanzaba StopIteration
        # sin capturar si el departamento fijado para un encargado dejaba
        # de existir (solo posible en un escenario multiusuario muy
        # improbable: otra instancia de la app, contra la misma base de
        # datos, borra ese departamento mientras esta sesión sigue
        # abierta) -- mismo patrón ya usado de forma segura en
        # candidates_ui.py._visible_departments().
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        page = PayrollPage(tk_root, repos, locked_department_id=dept.id)

        conn.execute("DELETE FROM departments WHERE id = ?", (dept.id,))
        page.reload_departments()  # no debe lanzar StopIteration

        assert page._departments == []
        page.destroy()


class TestGeneratePayrollDialogPrefill:
    def test_prefills_with_the_automatic_estimate_when_no_record_exists(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _dept_id, employee_id = _build_repos(conn)
        employee = repos.employees.get(employee_id)
        settings = repos.payroll_settings.get()
        expected = estimate_irpf_withholding_rate(
            employee.salary, settings.ss_employee_pct, employee.dependent_children
        )

        dialog = GeneratePayrollDialog(
            tk_root, repos, employee, 2026, 3, on_change=lambda: None
        )
        assert float(dialog.irpf_var.get()) == expected
        dialog.destroy()

    def test_prefills_with_the_existing_records_percentage_not_a_fresh_estimate(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        # Regenerar (p. ej. tras añadir un complemento) no debe descartar
        # silenciosamente un % de IRPF puesto a mano la primera vez.
        repos, _dept_id, employee_id = _build_repos(conn)
        repos.payroll_records.generate(employee_id, 2026, 3, irpf_pct_override=22.5)
        employee = repos.employees.get(employee_id)

        dialog = GeneratePayrollDialog(
            tk_root, repos, employee, 2026, 3, on_change=lambda: None
        )
        assert float(dialog.irpf_var.get()) == 22.5
        dialog.destroy()

    def test_submit_persists_the_typed_percentage_and_calls_on_change(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _dept_id, employee_id = _build_repos(conn)
        employee = repos.employees.get(employee_id)
        calls = []

        dialog = GeneratePayrollDialog(
            tk_root, repos, employee, 2026, 3, on_change=lambda: calls.append(1)
        )
        dialog.irpf_var.set("18,25")  # coma decimal, como ya se escribe en el resto de la app
        dialog._handle_submit()

        record = repos.payroll_records.get(employee_id, 2026, 3)
        assert record is not None
        assert record.payroll.irpf_pct == 18.25
        assert calls == [1]

    def test_submit_with_invalid_percentage_shows_an_error_and_does_not_close(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _dept_id, employee_id = _build_repos(conn)
        employee = repos.employees.get(employee_id)

        dialog = GeneratePayrollDialog(
            tk_root, repos, employee, 2026, 3, on_change=lambda: None
        )
        dialog.irpf_var.set("no-es-un-numero")
        dialog._handle_submit()

        assert dialog.error_label.cget("text") != ""
        assert repos.payroll_records.get(employee_id, 2026, 3) is None
        dialog.destroy()


class TestDownloadPdfButtonState:
    def test_disabled_when_no_employee_selected(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _dept_id, _employee_id = _build_repos(conn)
        page = PayrollPage(tk_root, repos)
        assert "disabled" in page.download_pdf_button.state()
        page.destroy()

    def test_disabled_for_a_live_estimate(self, tk_root: tk.Tk, conn: sqlite3.Connection) -> None:
        repos, _dept_id, employee_id = _build_repos(conn)
        page = PayrollPage(tk_root, repos)
        page.tree.selection_set(str(employee_id))
        page._handle_selection_changed()
        page._view_year, page._view_month = 2026, 3
        page._render_breakdown()

        assert "disabled" in page.download_pdf_button.state()
        page.destroy()

    def test_enabled_once_a_record_is_generated(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _dept_id, employee_id = _build_repos(conn)
        repos.payroll_records.generate(employee_id, 2026, 3)
        page = PayrollPage(tk_root, repos)
        page.tree.selection_set(str(employee_id))
        page._handle_selection_changed()
        page._view_year, page._view_month = 2026, 3
        page._render_breakdown()

        assert "disabled" not in page.download_pdf_button.state()
        page.destroy()
