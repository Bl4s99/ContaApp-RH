from __future__ import annotations

import os
import sqlite3
import tkinter as tk
import tkinter.messagebox as messagebox
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk

import pytest

from app import payroll_ui
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


class TestPrintButtonState:
    def test_disabled_when_no_employee_selected(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _dept_id, _employee_id = _build_repos(conn)
        page = PayrollPage(tk_root, repos)
        assert "disabled" in page.print_button.state()
        page.destroy()

    def test_disabled_for_a_live_estimate(self, tk_root: tk.Tk, conn: sqlite3.Connection) -> None:
        repos, _dept_id, employee_id = _build_repos(conn)
        page = PayrollPage(tk_root, repos)
        page.tree.selection_set(str(employee_id))
        page._handle_selection_changed()
        page._view_year, page._view_month = 2026, 3
        page._render_breakdown()

        assert "disabled" in page.print_button.state()
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

        assert "disabled" not in page.print_button.state()
        page.destroy()


class TestGenerateAllButton:
    def test_empty_view_shows_info_and_never_prompts_to_confirm(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repos = Repositories.create(conn)
        page = PayrollPage(tk_root, repos)
        assert page._employees == []

        confirm_calls: list[tuple[object, ...]] = []
        info_calls: list[tuple[object, ...]] = []

        def _fake_askyesno(*a: object, **_k: object) -> bool:
            confirm_calls.append(a)
            return True

        monkeypatch.setattr(messagebox, "askyesno", _fake_askyesno)
        monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: info_calls.append(a))

        page._handle_generate_all()

        assert confirm_calls == []
        assert info_calls
        page.destroy()

    def test_confirmed_generates_for_missing_and_skips_existing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repos, dept_id, employee_id = _build_repos(conn)
        second = repos.employees.create(
            EmployeeInput(
                first_name="Luis",
                last_name="Garcia",
                email="luis@example.com",
                phone="",
                position="Comercial",
                department_id=dept_id,
                salary=26000.0,
                dependent_children=0,
                hire_date="2022-01-01",
            )
        )
        assert second.id is not None
        repos.payroll_records.generate(employee_id, 2026, 3, irpf_pct_override=22.5)

        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        info_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: info_calls.append(a))

        page = PayrollPage(tk_root, repos)
        page._view_year, page._view_month = 2026, 3
        page._handle_generate_all()

        untouched = repos.payroll_records.get(employee_id, 2026, 3)
        assert untouched is not None
        assert untouched.payroll.irpf_pct == 22.5
        assert repos.payroll_records.get(second.id, 2026, 3) is not None
        assert info_calls
        page.destroy()

    def test_declining_the_confirmation_generates_nothing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repos, _dept_id, employee_id = _build_repos(conn)
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: False)

        page = PayrollPage(tk_root, repos)
        page._view_year, page._view_month = 2026, 3
        page._handle_generate_all()

        assert repos.payroll_records.get(employee_id, 2026, 3) is None
        page.destroy()

    def test_respects_locked_department_id_scope(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repos = Repositories.create(conn)
        dept_a = repos.departments.create("Ventas")
        dept_b = repos.departments.create("Almacén")
        assert dept_a.id is not None and dept_b.id is not None
        emp_a = repos.employees.create(
            EmployeeInput(
                first_name="Ana",
                last_name="A",
                email="ana.a@example.com",
                phone="",
                position="X",
                department_id=dept_a.id,
                salary=24000.0,
                dependent_children=0,
                hire_date="2022-01-01",
            )
        )
        emp_b = repos.employees.create(
            EmployeeInput(
                first_name="Bea",
                last_name="B",
                email="bea.b@example.com",
                phone="",
                position="X",
                department_id=dept_b.id,
                salary=24000.0,
                dependent_children=0,
                hire_date="2022-01-01",
            )
        )
        assert emp_a.id is not None and emp_b.id is not None
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)

        page = PayrollPage(tk_root, repos, locked_department_id=dept_a.id)
        page._view_year, page._view_month = 2026, 3
        page._handle_generate_all()

        assert repos.payroll_records.get(emp_a.id, 2026, 3) is not None
        assert repos.payroll_records.get(emp_b.id, 2026, 3) is None
        page.destroy()


class TestPrintPdfButton:
    def test_no_record_shows_info_titled_imprimir_and_never_calls_startfile(
        self,
        tk_root: tk.Tk,
        conn: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(payroll_ui.tempfile, "gettempdir", lambda: str(tmp_path))
        startfile_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(payroll_ui.os, "startfile", lambda *a: startfile_calls.append(a))
        info_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: info_calls.append(a))

        repos, _dept_id, employee_id = _build_repos(conn)
        page = PayrollPage(tk_root, repos)
        page.tree.selection_set(str(employee_id))
        page._handle_selection_changed()
        page._view_year, page._view_month = 2026, 3
        page._render_breakdown()

        page._handle_print_pdf()

        assert startfile_calls == []
        assert info_calls
        assert info_calls[0][0] == "Imprimir"
        page.destroy()

    def test_writes_a_valid_pdf_and_calls_startfile_with_the_print_verb(
        self,
        tk_root: tk.Tk,
        conn: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(payroll_ui.tempfile, "gettempdir", lambda: str(tmp_path))
        startfile_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(payroll_ui.os, "startfile", lambda *a: startfile_calls.append(a))
        monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)

        repos, _dept_id, employee_id = _build_repos(conn)
        repos.payroll_records.generate(employee_id, 2026, 3)
        page = PayrollPage(tk_root, repos)
        page.tree.selection_set(str(employee_id))
        page._handle_selection_changed()
        page._view_year, page._view_month = 2026, 3
        page._render_breakdown()

        page._handle_print_pdf()

        assert len(startfile_calls) == 1
        written_path, verb = startfile_calls[0]
        assert verb == "print"
        written = Path(written_path)  # type: ignore[arg-type]
        assert written.read_bytes().startswith(b"%PDF-")
        assert written.parent == tmp_path / "contaapp_rh_print"
        page.destroy()

    def test_startfile_oserror_shows_error_mentioning_imprimir(
        self,
        tk_root: tk.Tk,
        conn: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(payroll_ui.tempfile, "gettempdir", lambda: str(tmp_path))

        def _raise(*_args: object) -> None:
            raise OSError("no application is associated with this file type")

        monkeypatch.setattr(payroll_ui.os, "startfile", _raise)
        error_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: error_calls.append(a))

        repos, _dept_id, employee_id = _build_repos(conn)
        repos.payroll_records.generate(employee_id, 2026, 3)
        page = PayrollPage(tk_root, repos)
        page.tree.selection_set(str(employee_id))
        page._handle_selection_changed()
        page._view_year, page._view_month = 2026, 3
        page._render_breakdown()

        page._handle_print_pdf()

        assert len(error_calls) == 1
        title, message = error_calls[0][0], error_calls[0][1]
        assert title == "Imprimir"
        assert "imprimir" in str(message).lower()
        page.destroy()


class TestCleanupStalePrintFiles:
    def test_deletes_files_older_than_the_threshold_and_keeps_fresh_ones(
        self, tmp_path: Path
    ) -> None:
        old_file = tmp_path / "old.pdf"
        old_file.write_bytes(b"%PDF-old")
        old_time = (datetime.now() - timedelta(hours=2)).timestamp()
        os.utime(old_file, (old_time, old_time))

        fresh_file = tmp_path / "fresh.pdf"
        fresh_file.write_bytes(b"%PDF-fresh")

        payroll_ui._cleanup_stale_print_files(tmp_path, max_age_seconds=3600)

        assert not old_file.exists()
        assert fresh_file.exists()

    def test_missing_directory_does_not_raise(self, tmp_path: Path) -> None:
        payroll_ui._cleanup_stale_print_files(tmp_path / "does_not_exist")
