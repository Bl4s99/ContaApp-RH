from __future__ import annotations

import sqlite3
import tkinter as tk
import tkinter.messagebox as messagebox
from datetime import date, timedelta
from pathlib import Path

import pytest

from app import employee_page
from app.employee_page import (
    ChangeObjectiveStatusDialog,
    EmployeeFichaPanel,
    EmployeePage,
    EquipmentDialog,
    GenerateDocumentDialog,
    MarkEquipmentReturnedDialog,
    ObjectiveDialog,
    PerformanceReviewDialog,
    SetSelfServicePinDialog,
    SeveranceViewDialog,
    TrainingDialog,
    _format_currency,
    _format_seniority,
)
from app.models import DocumentTemplate, Employee, SeveranceSettlement
from app.repository import (
    EmployeeInput,
    ProfessionalCategoryInput,
    Repositories,
    SeveranceSettlementRepository,
)
from app.severance import calculate_severance

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


class TestFormatCurrency:
    def test_whole_thousands(self) -> None:
        assert _format_currency(30000) == "30.000,00 €"

    def test_with_cents(self) -> None:
        assert _format_currency(1234.5) == "1.234,50 €"

    def test_millions(self) -> None:
        assert _format_currency(1_250_000) == "1.250.000,00 €"

    def test_under_a_thousand_has_no_thousands_separator(self) -> None:
        assert _format_currency(950) == "950,00 €"

    def test_zero(self) -> None:
        assert _format_currency(0) == "0,00 €"


class TestFormatSeniority:
    def test_hired_today_is_less_than_a_month(self) -> None:
        today = date(2026, 3, 15)
        assert _format_seniority(today, today) == "Menos de 1 mes"

    def test_a_few_days_ago_is_less_than_a_month(self) -> None:
        assert _format_seniority(date(2026, 3, 10), date(2026, 3, 15)) == "Menos de 1 mes"

    def test_singular_month(self) -> None:
        assert _format_seniority(date(2026, 2, 10), date(2026, 3, 15)) == "1 mes"

    def test_plural_months(self) -> None:
        assert _format_seniority(date(2025, 10, 10), date(2026, 3, 15)) == "5 meses"

    def test_exact_single_year_anniversary(self) -> None:
        assert _format_seniority(date(2025, 3, 15), date(2026, 3, 15)) == "1 año"

    def test_exact_multi_year_anniversary(self) -> None:
        assert _format_seniority(date(2023, 3, 15), date(2026, 3, 15)) == "3 años"

    def test_years_and_singular_month(self) -> None:
        assert _format_seniority(date(2025, 2, 15), date(2026, 3, 15)) == "1 año, 1 mes"

    def test_years_and_plural_months(self) -> None:
        assert _format_seniority(date(2023, 12, 15), date(2026, 3, 15)) == "2 años, 3 meses"

    def test_day_of_month_not_yet_reached_withholds_partial_month(self) -> None:
        # Hired the 25th; one day before the 2-month mark should still read
        # as only 1 full month elapsed, not 2.
        assert _format_seniority(date(2024, 1, 25), date(2024, 3, 20)) == "1 mes"

    def test_day_of_month_reached_counts_the_month(self) -> None:
        assert _format_seniority(date(2024, 1, 25), date(2024, 3, 25)) == "2 meses"


class TestEmployeePageColumnSort:
    def _build_repos(self, conn: sqlite3.Connection) -> Repositories:
        repos = Repositories.create(conn)
        dept_a = repos.departments.create("Almacén")
        dept_f = repos.departments.create("Floristería")
        dept_p = repos.departments.create("Panadería")
        assert dept_a.id is not None and dept_f.id is not None and dept_p.id is not None
        today = date.today()

        repos.employees.create(
            EmployeeInput(
                first_name="Ana",
                last_name="García",
                email="ana@example.com",
                phone="",
                position="Dependienta",
                department_id=dept_f.id,
                salary=1400,
                hire_date=(today - timedelta(days=800)).isoformat(),
                active=True,
            )
        )
        repos.employees.create(
            EmployeeInput(
                first_name="Luis",
                last_name="Pérez",
                email="luis@example.com",
                phone="",
                position="Encargado",
                department_id=dept_a.id,
                salary=1600,
                hire_date=(today - timedelta(days=30)).isoformat(),
                active=True,
            )
        )
        repos.employees.create(
            EmployeeInput(
                first_name="María",
                last_name="López",
                email="maria@example.com",
                phone="",
                position="Cajera",
                department_id=dept_p.id,
                salary=1300,
                hire_date=(today - timedelta(days=5)).isoformat(),
                active=False,
            )
        )
        return repos

    def _names_in_order(self, page: EmployeePage) -> list[str]:
        return [
            str(page.tree.item(iid, "values")[0]) for iid in page.tree.get_children()
        ]

    def test_default_sort_is_name_ascending(self, tk_root: tk.Tk, conn: sqlite3.Connection) -> None:
        repos = self._build_repos(conn)
        page = EmployeePage(tk_root, repos, on_view_calendar=lambda _e: None)
        assert self._names_in_order(page) == ["Ana García", "María López", "Luis Pérez"]
        assert page.tree.heading("nombre", "text") == "Nombre ▲"
        assert page.tree.heading("puesto", "text") == "Puesto"
        page.destroy()

    def test_clicking_a_column_sorts_ascending_then_descending(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = self._build_repos(conn)
        page = EmployeePage(tk_root, repos, on_view_calendar=lambda _e: None)

        page._handle_sort_click("puesto")
        assert self._names_in_order(page) == ["María López", "Ana García", "Luis Pérez"]
        assert page.tree.heading("puesto", "text") == "Puesto ▲"
        assert page.tree.heading("nombre", "text") == "Nombre"  # arrow moved off nombre

        page._handle_sort_click("puesto")
        assert self._names_in_order(page) == ["Luis Pérez", "Ana García", "María López"]
        assert page.tree.heading("puesto", "text") == "Puesto ▼"
        page.destroy()

    def test_sort_by_department_name(self, tk_root: tk.Tk, conn: sqlite3.Connection) -> None:
        repos = self._build_repos(conn)
        page = EmployeePage(tk_root, repos, on_view_calendar=lambda _e: None)
        page._handle_sort_click("departamento")
        assert self._names_in_order(page) == ["Luis Pérez", "Ana García", "María López"]
        page.destroy()

    def test_sort_by_salary(self, tk_root: tk.Tk, conn: sqlite3.Connection) -> None:
        repos = self._build_repos(conn)
        page = EmployeePage(tk_root, repos, on_view_calendar=lambda _e: None)
        page._handle_sort_click("salario")
        assert self._names_in_order(page) == ["María López", "Ana García", "Luis Pérez"]
        page._handle_sort_click("salario")
        assert self._names_in_order(page) == ["Luis Pérez", "Ana García", "María López"]
        page.destroy()

    def test_salary_column_shows_formatted_currency(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = self._build_repos(conn)
        page = EmployeePage(tk_root, repos, on_view_calendar=lambda _e: None)
        values_by_name = {
            str(page.tree.item(iid, "values")[0]): page.tree.item(iid, "values")
            for iid in page.tree.get_children()
        }
        assert values_by_name["Luis Pérez"][3] == _format_currency(1600)
        assert values_by_name["Ana García"][3] == _format_currency(1400)
        assert values_by_name["María López"][3] == _format_currency(1300)
        page.destroy()

    def test_sort_by_seniority_ascending_is_newest_hire_first(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = self._build_repos(conn)
        page = EmployeePage(tk_root, repos, on_view_calendar=lambda _e: None)
        page._handle_sort_click("antiguedad")
        assert self._names_in_order(page) == ["María López", "Luis Pérez", "Ana García"]
        page._handle_sort_click("antiguedad")
        assert self._names_in_order(page) == ["Ana García", "Luis Pérez", "María López"]
        page.destroy()

    def test_sort_by_status_puts_inactive_last_ascending(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = self._build_repos(conn)
        page = EmployeePage(tk_root, repos, on_view_calendar=lambda _e: None)
        page._handle_sort_click("estado")
        names = self._names_in_order(page)
        assert names[-1] == "María López"  # the only inactive employee
        page._handle_sort_click("estado")
        names = self._names_in_order(page)
        assert names[0] == "María López"
        page.destroy()

    def test_seniority_column_shows_formatted_tenure(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = self._build_repos(conn)
        page = EmployeePage(tk_root, repos, on_view_calendar=lambda _e: None)
        today = date.today()
        values_by_name = {
            str(page.tree.item(iid, "values")[0]): page.tree.item(iid, "values")
            for iid in page.tree.get_children()
        }
        assert values_by_name["Luis Pérez"][4] == _format_seniority(
            today - timedelta(days=30), today
        )
        assert values_by_name["Ana García"][4] == _format_seniority(
            today - timedelta(days=800), today
        )
        page.destroy()

    def test_treeview_columns_include_salario_and_antiguedad(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = self._build_repos(conn)
        page = EmployeePage(tk_root, repos, on_view_calendar=lambda _e: None)
        assert page.tree.cget("columns") == (
            "nombre",
            "puesto",
            "departamento",
            "salario",
            "antiguedad",
            "estado",
        )
        page.destroy()


class TestRgpdButtons:
    def _build_repos_with_employee(
        self, conn: sqlite3.Connection, *, terminate: bool = False, anonymize: bool = False
    ) -> tuple[Repositories, Employee]:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ingeniería")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana",
                last_name="García",
                email="ana@example.com",
                phone="",
                position="Ingeniera",
                department_id=dept.id,
                salary=30000,
                hire_date="2020-01-01",
            )
        )
        assert employee.id is not None
        employee_id = employee.id
        if terminate or anonymize:
            employee = repos.employees.terminate(employee_id, "2026-06-30", "Baja voluntaria")
        if anonymize:
            employee = repos.employees.anonymize(employee_id)
        return repos, employee

    def _build_panel(
        self, tk_root: tk.Tk, repos: Repositories, *, is_admin: bool
    ) -> EmployeeFichaPanel:
        return EmployeeFichaPanel(
            tk_root,
            repos,
            on_saved=lambda _id: None,
            on_deleted=lambda: None,
            on_view_calendar=lambda _e: None,
            is_admin=is_admin,
        )

    def test_active_employee_admin_can_export_but_not_anonymize(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_repos_with_employee(conn)
        panel = self._build_panel(tk_root, repos, is_admin=True)
        panel.show_employee(employee)
        assert "disabled" not in panel.export_data_button.state()
        assert "disabled" in panel.anonymize_button.state()
        panel.destroy()

    def test_inactive_employee_admin_can_export_and_anonymize(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_repos_with_employee(conn, terminate=True)
        panel = self._build_panel(tk_root, repos, is_admin=True)
        panel.show_employee(employee)
        assert "disabled" not in panel.export_data_button.state()
        assert "disabled" not in panel.anonymize_button.state()
        panel.destroy()

    def test_already_anonymized_employee_cannot_be_anonymized_again(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_repos_with_employee(conn, anonymize=True)
        panel = self._build_panel(tk_root, repos, is_admin=True)
        panel.show_employee(employee)
        assert "disabled" not in panel.export_data_button.state()
        assert "disabled" in panel.anonymize_button.state()
        panel.destroy()

    def test_non_admin_cannot_export_or_anonymize(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_repos_with_employee(conn, terminate=True)
        panel = self._build_panel(tk_root, repos, is_admin=False)
        panel.show_employee(employee)
        assert "disabled" in panel.export_data_button.state()
        assert "disabled" in panel.anonymize_button.state()
        panel.destroy()

    def test_no_employee_selected_disables_both_buttons(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        panel = self._build_panel(tk_root, repos, is_admin=True)
        panel.show_employee(None)
        assert "disabled" in panel.export_data_button.state()
        assert "disabled" in panel.anonymize_button.state()
        panel.destroy()


class TestVacationBalanceDisplay:
    def _build_panel(self, tk_root: tk.Tk, repos: Repositories) -> EmployeeFichaPanel:
        return EmployeeFichaPanel(
            tk_root,
            repos,
            on_saved=lambda _id: None,
            on_deleted=lambda: None,
            on_view_calendar=lambda _e: None,
            is_admin=True,
        )

    def test_active_employee_shows_the_current_years_full_entitlement(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ingeniería")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="García", email="ana@example.com", phone="",
                position="Ingeniera", department_id=dept.id, salary=30000,
                hire_date="2020-01-01",
            )
        )
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        assert f"Vacaciones {date.today().year}:" in panel.vacation_balance_label.cget("text")
        panel.destroy()

    def test_terminated_employee_shows_balance_prorated_to_termination_not_the_full_year(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        # Regresión: se mostraba el devengo completo del año EN CURSO
        # (hasta el 31 de diciembre) para un empleado que puede llevar años
        # sin trabajar allí -- debe prorratearse hasta la fecha de baja,
        # igual que ya hace el finiquito, y mostrar el año de la baja, no
        # el año actual.
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ingeniería")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="García", email="ana@example.com", phone="",
                position="Ingeniera", department_id=dept.id, salary=30000,
                hire_date="2020-01-01",
            )
        )
        assert employee.id is not None
        terminated = repos.employees.terminate(employee.id, "2024-07-01", "Baja voluntaria")

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(terminated)
        text = panel.vacation_balance_label.cget("text")

        assert "Vacaciones 2024:" in text
        assert str(date.today().year) not in text
        # enero..junio de 2024 = 6 meses completos -> 6/12 de 22 = 11.
        assert "usa 0 de 11 días (quedan 11)" in text
        panel.destroy()


def _label_texts(widget: tk.Misc) -> list[str]:
    texts = []
    for child in widget.winfo_children():
        if hasattr(child, "cget"):
            try:
                text = child.cget("text")
            except tk.TclError:
                text = None
            if isinstance(text, str) and text:
                texts.append(text)
        texts.extend(_label_texts(child))
    return texts


class TestSeveranceViewDialogNavigation:
    # Regresión: tras varios ciclos baja→reactivar→baja, "Ver finiquito..."
    # solo mostraba el finiquito más reciente -- los anteriores seguían
    # intactos en la base de datos (y en la exportación RGPD) pero eran
    # inaccesibles desde la ficha, sin ningún selector para verlos.
    def _build_employee_and_two_settlements(
        self, conn: sqlite3.Connection
    ) -> tuple[Employee, list[SeveranceSettlement]]:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ingeniería")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="García", email="ana@example.com", phone="",
                position="Ingeniera", department_id=dept.id, salary=24000,
                hire_date="2020-01-01",
            )
        )
        assert employee.id is not None
        settlement_repo = SeveranceSettlementRepository(conn)

        first_calc = calculate_severance(
            hire_date=date(2020, 1, 1), termination_date=date(2023, 6, 30),
            annual_gross_salary=24000.0, annual_vacation_days=22.0,
            vacation_days_used_this_year=2,
        )
        settlement_repo.create(
            employee_id=employee.id, termination_date=date(2023, 6, 30),
            termination_reason="Baja voluntaria", hire_date=date(2020, 1, 1),
            annual_gross_salary=24000.0, annual_vacation_days=22.0,
            vacation_days_used_this_year=2, calculation=first_calc,
        )
        second_calc = calculate_severance(
            hire_date=date(2020, 1, 1), termination_date=date(2024, 12, 31),
            annual_gross_salary=24000.0, annual_vacation_days=22.0,
            vacation_days_used_this_year=5,
        )
        settlement_repo.create(
            employee_id=employee.id, termination_date=date(2024, 12, 31),
            termination_reason="Fin de contrato temporal", hire_date=date(2020, 1, 1),
            annual_gross_salary=24000.0, annual_vacation_days=22.0,
            vacation_days_used_this_year=5, calculation=second_calc,
        )
        settlements = settlement_repo.list_for_employee(employee.id)
        return employee, settlements

    def test_lists_most_recent_first_and_navigation_moves_correctly(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        employee, settlements = self._build_employee_and_two_settlements(conn)
        assert len(settlements) == 2
        dialog = SeveranceViewDialog(tk_root, employee, settlements)

        # Empieza en el más reciente (índice 0 de list_for_employee(), que
        # ya ordena generated_at DESC).
        assert settlements[dialog._index].termination_date == date(2024, 12, 31)
        assert any("1 de 2" in text for text in _label_texts(dialog))

        dialog._go_previous()
        assert settlements[dialog._index].termination_date == date(2023, 6, 30)

        dialog._go_next()
        assert settlements[dialog._index].termination_date == date(2024, 12, 31)
        dialog.destroy()

    def test_single_settlement_has_no_navigation_controls(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ingeniería")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="García", email="ana@example.com", phone="",
                position="Ingeniera", department_id=dept.id, salary=24000,
                hire_date="2020-01-01",
            )
        )
        assert employee.id is not None
        calc = calculate_severance(
            hire_date=date(2020, 1, 1), termination_date=date(2024, 12, 31),
            annual_gross_salary=24000.0, annual_vacation_days=22.0,
            vacation_days_used_this_year=5,
        )
        SeveranceSettlementRepository(conn).create(
            employee_id=employee.id, termination_date=date(2024, 12, 31),
            termination_reason="Fin de contrato temporal", hire_date=date(2020, 1, 1),
            annual_gross_salary=24000.0, annual_vacation_days=22.0,
            vacation_days_used_this_year=5, calculation=calc,
        )
        settlements = SeveranceSettlementRepository(conn).list_for_employee(employee.id)

        dialog = SeveranceViewDialog(tk_root, employee, settlements)
        assert not any("de 1" in text for text in _label_texts(dialog))


class TestManagerCombo:
    def _build_panel(self, tk_root: tk.Tk, repos: Repositories) -> EmployeeFichaPanel:
        return EmployeeFichaPanel(
            tk_root,
            repos,
            on_saved=lambda _id: None,
            on_deleted=lambda: None,
            on_view_calendar=lambda _e: None,
        )

    def _make_employee(
        self, repos: Repositories, department_id: int, email: str, **overrides: object
    ) -> Employee:
        fields: dict[str, object] = dict(
            first_name=email.split("@")[0].capitalize(), last_name="Test", email=email,
            phone="", position="Comercial", department_id=department_id, salary=25000,
            hire_date="2022-01-01",
        )
        fields.update(overrides)
        return repos.employees.create(EmployeeInput(**fields))  # type: ignore[arg-type]

    def test_options_exclude_self_and_are_scoped_to_the_same_department(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        other_dept = repos.departments.create("Marketing")
        assert other_dept.id is not None
        ana = self._make_employee(repos, dept.id, "ana@x.com")
        self._make_employee(repos, dept.id, "bob@x.com")
        self._make_employee(repos, other_dept.id, "fuera@x.com")

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(ana)
        values = list(panel.manager_combo["values"])
        assert "Ana Test" not in values
        assert "Bob Test" in values
        assert "Fuera Test" not in values
        panel.destroy()

    def test_saving_a_selected_manager_persists_it(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        boss = self._make_employee(repos, dept.id, "jefa@x.com")
        report = self._make_employee(repos, dept.id, "reporta@x.com")
        assert boss.id is not None and report.id is not None

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(report)
        idx = list(panel.manager_combo["values"]).index("Jefa Test")
        panel.manager_combo.current(idx)
        panel._handle_save()

        assert repos.employees.get(report.id).manager_id == boss.id
        panel.destroy()

    def test_selecting_no_manager_clears_it(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        boss = self._make_employee(repos, dept.id, "jefa2@x.com")
        assert boss.id is not None
        report = self._make_employee(repos, dept.id, "reporta2@x.com", manager_id=boss.id)
        assert report.id is not None

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(report)
        assert panel.manager_combo.get() == "Jefa2 Test"
        panel.manager_combo.current(0)  # "— Sin supervisor asignado —"
        panel._handle_save()

        assert repos.employees.get(report.id).manager_id is None
        panel.destroy()

    def test_a_manager_who_later_left_still_shows_marked_instead_of_disappearing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        boss = self._make_employee(repos, dept.id, "jefa3@x.com")
        assert boss.id is not None
        report = self._make_employee(repos, dept.id, "reporta3@x.com", manager_id=boss.id)
        assert report.id is not None
        repos.employees.terminate(boss.id, "2026-01-01", "Baja voluntaria")

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(repos.employees.get(report.id))
        assert panel.manager_combo.get() == "Jefa3 Test (de baja)"
        assert "Jefa3 Test" not in panel.manager_combo["values"]
        panel.destroy()

    def test_new_employee_defaults_to_no_manager_selected(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        self._make_employee(repos, dept.id, "existente@x.com")

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(None)
        assert panel.manager_combo.get() == "— Sin supervisor asignado —"
        panel.destroy()


class TestHeadOfDepartmentField:
    def _build_panel(self, tk_root: tk.Tk, repos: Repositories) -> EmployeeFichaPanel:
        return EmployeeFichaPanel(
            tk_root,
            repos,
            on_saved=lambda _id: None,
            on_deleted=lambda: None,
            on_view_calendar=lambda _e: None,
        )

    def test_new_employee_starts_unchecked_and_disabled(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        repos.departments.create("Ventas")
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(None)
        assert panel.is_department_head_var.get() is False
        assert str(panel.head_of_department_combo.cget("state")) == "disabled"
        panel.destroy()

    def test_existing_employee_without_it_starts_unchecked(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@x.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2022-01-01",
            )
        )
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        assert panel.is_department_head_var.get() is False
        assert str(panel.head_of_department_combo.cget("state")) == "disabled"
        panel.destroy()

    def test_checking_the_box_enables_the_combo(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        repos.departments.create("Ventas")
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(None)
        panel.is_department_head_var.set(True)
        panel._handle_department_head_toggled()
        assert str(panel.head_of_department_combo.cget("state")) == "readonly"
        panel.destroy()

    def test_saving_a_selected_department_persists_it(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        dept2 = repos.departments.create("Marketing")
        assert dept.id is not None and dept2.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@x.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2022-01-01",
            )
        )
        assert employee.id is not None

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        panel.is_department_head_var.set(True)
        panel._handle_department_head_toggled()
        idx = list(panel.head_of_department_combo["values"]).index("Marketing")
        panel.head_of_department_combo.current(idx)
        panel._handle_save()

        assert repos.employees.get(employee.id).head_of_department_id == dept2.id
        panel.destroy()

    def test_reload_shows_the_saved_department_and_re_enables_the_combo(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        dept2 = repos.departments.create("Marketing")
        assert dept.id is not None and dept2.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@x.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2022-01-01", head_of_department_id=dept2.id,
            )
        )

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        assert panel.is_department_head_var.get() is True
        assert panel.head_of_department_combo.get() == "Marketing"
        assert str(panel.head_of_department_combo.cget("state")) == "readonly"
        panel.destroy()

    def test_checked_without_a_selection_shows_an_error_instead_of_crashing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(None)
        panel.department_combo.current(0)
        panel.is_department_head_var.set(True)
        panel._handle_department_head_toggled()
        panel.head_of_department_combo.set("")
        panel.first_name_var.set("Nueva")
        panel.last_name_var.set("Persona")
        panel.email_var.set("nueva@x.com")
        panel.position_var.set("Comercial")
        panel.salary_var.set("20000")

        panel._handle_save()

        assert panel.error_label.cget("text") != ""
        assert repos.employees.search() == []  # no se llegó a guardar nada
        panel.destroy()

    def test_unchecking_clears_it_on_save(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@x.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2022-01-01", head_of_department_id=dept.id,
            )
        )
        assert employee.id is not None

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        panel.is_department_head_var.set(False)
        panel._handle_department_head_toggled()
        panel._handle_save()

        assert repos.employees.get(employee.id).head_of_department_id is None


class TestProfessionalCategoryField:
    def _build_panel(self, tk_root: tk.Tk, repos: Repositories) -> EmployeeFichaPanel:
        return EmployeeFichaPanel(
            tk_root,
            repos,
            on_saved=lambda _id: None,
            on_deleted=lambda: None,
            on_view_calendar=lambda _e: None,
        )

    def test_new_employee_defaults_to_no_category_selected(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        repos.departments.create("Ventas")
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(None)
        assert panel.professional_category_combo.get() == "— Sin categoría profesional —"
        panel.destroy()

    def test_options_are_labeled_with_agreement_and_category_name(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        repos.departments.create("Ventas")
        agreement = repos.collective_agreements.create("Convenio Estatal de Comercio")
        assert agreement.id is not None
        repos.professional_categories.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement.id, name="Oficial de primera",
                minimum_salary=18000.0,
            )
        )
        panel = self._build_panel(tk_root, repos)
        values = list(panel.professional_category_combo["values"])
        assert "Convenio Estatal de Comercio — Oficial de primera" in values
        panel.destroy()

    def test_saving_a_selected_category_persists_it(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        agreement = repos.collective_agreements.create("Convenio Estatal de Comercio")
        assert agreement.id is not None
        category = repos.professional_categories.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement.id, name="Oficial de primera",
                minimum_salary=18000.0,
            )
        )
        assert category.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@x.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2022-01-01",
            )
        )
        assert employee.id is not None

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        idx = list(panel.professional_category_combo["values"]).index(
            "Convenio Estatal de Comercio — Oficial de primera"
        )
        panel.professional_category_combo.current(idx)
        panel._handle_save()

        assert repos.employees.get(employee.id).professional_category_id == category.id
        panel.destroy()

    def test_reopening_an_employee_shows_their_saved_category(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        agreement = repos.collective_agreements.create("Convenio Estatal de Comercio")
        assert agreement.id is not None
        category = repos.professional_categories.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement.id, name="Oficial de primera",
                minimum_salary=18000.0,
            )
        )
        assert category.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@x.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2022-01-01", professional_category_id=category.id,
            )
        )

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        assert (
            panel.professional_category_combo.get()
            == "Convenio Estatal de Comercio — Oficial de primera"
        )
        panel.destroy()

    def test_selecting_no_category_clears_it(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        agreement = repos.collective_agreements.create("Convenio Estatal de Comercio")
        assert agreement.id is not None
        category = repos.professional_categories.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement.id, name="Oficial de primera",
                minimum_salary=18000.0,
            )
        )
        assert category.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@x.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2022-01-01", professional_category_id=category.id,
            )
        )
        assert employee.id is not None

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        panel.professional_category_combo.current(0)  # "— Sin categoría profesional —"
        panel._handle_save()

        assert repos.employees.get(employee.id).professional_category_id is None
        panel.destroy()

    def test_reload_after_deleting_the_assigned_category_falls_back_to_sentinel(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        agreement = repos.collective_agreements.create("Convenio Estatal de Comercio")
        assert agreement.id is not None
        category = repos.professional_categories.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement.id, name="Oficial de primera",
                minimum_salary=18000.0,
            )
        )
        assert category.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@x.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2022-01-01", professional_category_id=category.id,
            )
        )
        assert employee.id is not None

        # Deleting the category (ON DELETE SET NULL) leaves the employee's
        # own record already cleared -- reload_professional_categories()
        # must not crash trying to resolve a now-missing category id.
        repos.professional_categories.delete(category.id)
        panel = self._build_panel(tk_root, repos)
        panel.reload_professional_categories()
        panel.show_employee(repos.employees.get(employee.id))
        assert panel.professional_category_combo.get() == "— Sin categoría profesional —"
        panel.destroy()


class TestTrainingSection:
    def _build_employee(self, conn: sqlite3.Connection) -> tuple[Repositories, Employee]:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ingeniería")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="García", email="ana@example.com", phone="",
                position="Ingeniera", department_id=dept.id, salary=30000,
                hire_date="2020-01-01",
            )
        )
        return repos, employee

    def _build_panel(self, tk_root: tk.Tk, repos: Repositories) -> EmployeeFichaPanel:
        return EmployeeFichaPanel(
            tk_root,
            repos,
            on_saved=lambda _id: None,
            on_deleted=lambda: None,
            on_view_calendar=lambda _e: None,
        )

    def test_new_employee_has_no_training_rows(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(None)
        assert panel.trainings_tree.get_children() == ()
        panel.destroy()

    def test_adding_a_training_via_the_dialog_shows_up_in_the_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)

        dialog = TrainingDialog(panel, repos, employee, on_change=panel._refresh_trainings)
        dialog.name_var.set("Carné de carretillero")
        dialog.completion_date_entry.value_var.set("2024-01-01")
        dialog.no_expiration_var.set(False)
        dialog._handle_no_expiration_toggled()
        dialog.expiration_date_entry.value_var.set("2027-01-01")
        dialog._handle_save()

        rows = [panel.trainings_tree.item(i, "values") for i in panel.trainings_tree.get_children()]
        assert rows == [("Carné de carretillero", "01/01/2024", "01/01/2027")]
        panel.destroy()

    def test_training_without_expiration_shows_an_em_dash(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        assert employee.id is not None
        repos.trainings.create(employee.id, "Curso de Excel", date(2023, 6, 1), None)

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        rows = [panel.trainings_tree.item(i, "values") for i in panel.trainings_tree.get_children()]
        assert rows == [("Curso de Excel", "01/06/2023", "—")]
        panel.destroy()

    def test_invalid_dialog_input_shows_an_error_instead_of_crashing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)

        dialog = TrainingDialog(panel, repos, employee, on_change=panel._refresh_trainings)
        dialog.name_var.set("")  # nombre vacío
        dialog.completion_date_entry.value_var.set("2024-01-01")
        dialog._handle_save()

        assert dialog.error_label.cget("text") != ""
        assert employee.id is not None
        assert repos.trainings.list_for_employee(employee.id) == []
        panel.destroy()

    def test_delete_button_with_nothing_selected_shows_an_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        panel._handle_delete_training()
        assert panel.trainings_error_label.cget("text") != ""
        panel.destroy()

    def test_switching_to_a_different_employee_reloads_the_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, ana = self._build_employee(conn)
        assert ana.id is not None
        repos.trainings.create(ana.id, "Formación de Ana", date(2024, 1, 1), None)
        dept = repos.departments.list_all()[0]
        assert dept.id is not None
        bob = repos.employees.create(
            EmployeeInput(
                first_name="Bob", last_name="Ruiz", email="bob@example.com", phone="",
                position="Ingeniero", department_id=dept.id, salary=28000,
                hire_date="2021-01-01",
            )
        )

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(ana)
        assert len(panel.trainings_tree.get_children()) == 1
        panel.show_employee(bob)
        assert panel.trainings_tree.get_children() == ()
        panel.destroy()
        panel.destroy()


class TestSelfServiceSection:
    def _build_panel(self, tk_root: tk.Tk, repos: Repositories) -> EmployeeFichaPanel:
        return EmployeeFichaPanel(
            tk_root,
            repos,
            on_saved=lambda _id: None,
            on_deleted=lambda: None,
            on_view_calendar=lambda _e: None,
        )

    def _build_employee(self, conn: sqlite3.Connection) -> tuple[Repositories, Employee]:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Ruiz", email="ana@example.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2020-01-01",
            )
        )
        return repos, employee

    def test_new_employee_has_no_status_text(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        repos.departments.create("Ventas")
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(None)
        assert panel.self_service_status_label.cget("text") == ""
        panel.destroy()

    def test_existing_employee_without_pin_shows_correct_status(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        assert panel.self_service_status_label.cget("text") == "Sin PIN de acceso configurado."
        panel.destroy()

    def test_clicking_set_pin_on_a_new_employee_shows_info_not_a_crash(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shown = []
        monkeypatch.setattr(
            messagebox, "showinfo", lambda *a, **k: shown.append(a)
        )
        repos = Repositories.create(conn)
        repos.departments.create("Ventas")
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(None)
        panel._handle_set_self_service_pin()
        assert len(shown) == 1
        panel.destroy()

    def test_setting_a_pin_via_the_dialog_updates_status_and_audit_log(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        assert employee.id is not None
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)

        dialog = SetSelfServicePinDialog(
            panel, repos, employee, on_change=panel._handle_self_service_pin_changed
        )
        dialog.pin_var.set("1234")
        dialog.confirm_pin_var.set("1234")
        dialog._handle_save()

        assert repos.employees.has_self_service_pin(employee.id) is True
        assert panel.self_service_status_label.cget("text") == "PIN de acceso configurado."
        actions = [entry.action for entry in repos.audit_log.list_all()]
        assert "self_service_pin_set" in actions
        panel.destroy()

    def test_mismatched_pin_confirmation_shows_error_and_does_not_save(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        assert employee.id is not None
        panel = self._build_panel(tk_root, repos)
        dialog = SetSelfServicePinDialog(
            panel, repos, employee, on_change=panel._handle_self_service_pin_changed
        )
        dialog.pin_var.set("1234")
        dialog.confirm_pin_var.set("4321")
        dialog._handle_save()
        assert dialog.error_label.cget("text") != ""
        assert repos.employees.has_self_service_pin(employee.id) is False
        dialog.destroy()
        panel.destroy()

    def test_invalid_pin_format_shows_validation_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        dialog = SetSelfServicePinDialog(
            panel, repos, employee, on_change=panel._handle_self_service_pin_changed
        )
        dialog.pin_var.set("12")
        dialog.confirm_pin_var.set("12")
        dialog._handle_save()
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()
        panel.destroy()

    def test_clearing_with_no_pin_set_shows_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        panel._handle_clear_self_service_pin()
        assert panel.self_service_error_label.cget("text") != ""
        panel.destroy()

    def test_clearing_via_the_ficha_removes_the_pin_and_records_audit(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        repos, employee = self._build_employee(conn)
        assert employee.id is not None
        repos.employees.set_self_service_pin(employee.id, "1234")
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)

        panel._handle_clear_self_service_pin()

        assert repos.employees.has_self_service_pin(employee.id) is False
        assert panel.self_service_status_label.cget("text") == "Sin PIN de acceso configurado."
        actions = [entry.action for entry in repos.audit_log.list_all()]
        assert "self_service_pin_cleared" in actions
        panel.destroy()

    def test_declining_the_clear_confirmation_keeps_the_pin(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: False)
        repos, employee = self._build_employee(conn)
        assert employee.id is not None
        repos.employees.set_self_service_pin(employee.id, "1234")
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)

        panel._handle_clear_self_service_pin()

        assert repos.employees.has_self_service_pin(employee.id) is True
        panel.destroy()


class TestPerformanceSection:
    def _build_panel(self, tk_root: tk.Tk, repos: Repositories) -> EmployeeFichaPanel:
        return EmployeeFichaPanel(
            tk_root,
            repos,
            on_saved=lambda _id: None,
            on_deleted=lambda: None,
            on_view_calendar=lambda _e: None,
        )

    def _build_employee(self, conn: sqlite3.Connection) -> tuple[Repositories, Employee]:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Ruiz", email="ana@example.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2020-01-01",
            )
        )
        return repos, employee

    def test_new_employee_has_empty_trees(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
        repos = Repositories.create(conn)
        repos.departments.create("Ventas")
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(None)
        panel._handle_add_objective()
        panel._handle_add_review()
        assert panel.objectives_tree.get_children() == ()
        assert panel.reviews_tree.get_children() == ()
        panel.destroy()

    def test_adding_an_objective_via_the_dialog_shows_up_in_the_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        dialog = ObjectiveDialog(
            panel, repos, employee, on_change=panel._refresh_objectives
        )
        dialog.title_var.set("Aumentar ventas un 10%")
        dialog.target_date_entry.value_var.set("2026-12-31")
        dialog._handle_save()

        rows = [
            panel.objectives_tree.item(iid, "values")
            for iid in panel.objectives_tree.get_children()
        ]
        assert rows == [("Aumentar ventas un 10%", "31/12/2026", "Pendiente")]
        panel.destroy()

    def test_invalid_objective_shows_an_error_instead_of_crashing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        dialog = ObjectiveDialog(
            panel, repos, employee, on_change=panel._refresh_objectives
        )
        dialog.title_var.set("   ")
        dialog.target_date_entry.value_var.set("2026-12-31")
        dialog._handle_save()
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()
        panel.destroy()

    def test_changing_objective_status_updates_the_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        assert employee.id is not None
        objective = repos.objectives.create(employee.id, "Objetivo", date(2026, 12, 31))
        assert objective.id is not None
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)

        status_dialog = ChangeObjectiveStatusDialog(
            panel, repos, objective, on_change=panel._refresh_objectives
        )
        status_dialog.status_combo.set("Cumplido")
        status_dialog._handle_save()

        row = panel.objectives_tree.item(str(objective.id), "values")
        assert row[2] == "Cumplido"
        panel.destroy()

    def test_delete_objective_with_nothing_selected_shows_an_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        panel._handle_delete_objective()
        assert panel.objectives_error_label.cget("text") != ""
        panel.destroy()

    def test_delete_objective_removes_it_and_records_audit(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        repos, employee = self._build_employee(conn)
        assert employee.id is not None
        objective = repos.objectives.create(employee.id, "Objetivo", date(2026, 12, 31))
        assert objective.id is not None
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)

        panel.objectives_tree.selection_set(str(objective.id))
        panel._handle_delete_objective()

        assert panel.objectives_tree.get_children() == ()
        actions = [entry.action for entry in repos.audit_log.list_all()]
        assert "objective_deleted" in actions
        panel.destroy()

    def test_adding_a_review_via_the_dialog_shows_up_in_the_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        dialog = PerformanceReviewDialog(
            panel, repos, employee, on_change=panel._refresh_reviews
        )
        dialog.review_date_entry.value_var.set("2026-06-15")
        dialog.comments_text.insert("1.0", "Buen desempeño este semestre.")
        dialog._handle_save()

        rows = [
            panel.reviews_tree.item(iid, "values") for iid in panel.reviews_tree.get_children()
        ]
        assert rows == [("15/06/2026", "Buen desempeño este semestre.")]
        panel.destroy()

    def test_review_with_empty_comments_shows_an_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        dialog = PerformanceReviewDialog(
            panel, repos, employee, on_change=panel._refresh_reviews
        )
        dialog.review_date_entry.value_var.set("2026-06-15")
        dialog._handle_save()
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()
        panel.destroy()

    def test_delete_review_removes_it_and_records_audit(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        repos, employee = self._build_employee(conn)
        assert employee.id is not None
        review = repos.performance_reviews.create(employee.id, date(2026, 6, 15), "Nota")
        assert review.id is not None
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)

        panel.reviews_tree.selection_set(str(review.id))
        panel._handle_delete_review()

        assert panel.reviews_tree.get_children() == ()
        actions = [entry.action for entry in repos.audit_log.list_all()]
        assert "performance_review_deleted" in actions
        panel.destroy()

    def test_switching_employee_reloads_both_trees(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, ana = self._build_employee(conn)
        assert ana.id is not None
        repos.objectives.create(ana.id, "Objetivo de Ana", date(2026, 12, 31))
        dept = repos.departments.list_all()[0]
        assert dept.id is not None
        bob = repos.employees.create(
            EmployeeInput(
                first_name="Bob", last_name="Ruiz", email="bob@example.com", phone="",
                position="Ingeniero", department_id=dept.id, salary=28000,
                hire_date="2021-01-01",
            )
        )

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(ana)
        assert len(panel.objectives_tree.get_children()) == 1
        panel.show_employee(bob)
        assert panel.objectives_tree.get_children() == ()
        panel.destroy()


class TestEquipmentSection:
    def _build_panel(self, tk_root: tk.Tk, repos: Repositories) -> EmployeeFichaPanel:
        return EmployeeFichaPanel(
            tk_root,
            repos,
            on_saved=lambda _id: None,
            on_deleted=lambda: None,
            on_view_calendar=lambda _e: None,
        )

    def _build_employee(self, conn: sqlite3.Connection) -> tuple[Repositories, Employee]:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        employee = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Ruiz", email="ana@example.com", phone="",
                position="Comercial", department_id=dept.id, salary=25000,
                hire_date="2020-01-01",
            )
        )
        return repos, employee

    def test_new_employee_has_empty_equipment_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
        repos = Repositories.create(conn)
        repos.departments.create("Ventas")
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(None)
        panel._handle_add_equipment()
        assert panel.equipment_tree.get_children() == ()
        panel.destroy()

    def test_adding_equipment_via_the_dialog_shows_up_in_the_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        dialog = EquipmentDialog(panel, repos, employee, on_change=panel._refresh_equipment)
        dialog.description_var.set("Portatil Dell XPS")
        dialog.assigned_date_entry.value_var.set("2024-01-10")
        dialog._handle_save()

        rows = [
            panel.equipment_tree.item(iid, "values")
            for iid in panel.equipment_tree.get_children()
        ]
        assert rows == [("Portatil Dell XPS", "10/01/2024", "—")]
        panel.destroy()

    def test_invalid_equipment_shows_an_error_instead_of_crashing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        dialog = EquipmentDialog(panel, repos, employee, on_change=panel._refresh_equipment)
        dialog.description_var.set("   ")
        dialog.assigned_date_entry.value_var.set("2024-01-10")
        dialog._handle_save()
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()
        panel.destroy()

    def test_marking_equipment_returned_updates_the_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        assert employee.id is not None
        equipment = repos.assigned_equipment.create(
            employee.id, "Portatil", date(2024, 1, 10)
        )
        assert equipment.id is not None
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)

        returned_dialog = MarkEquipmentReturnedDialog(
            panel, repos, equipment, on_change=panel._refresh_equipment
        )
        returned_dialog.returned_date_entry.value_var.set("2024-02-01")
        returned_dialog._handle_save()

        row = panel.equipment_tree.item(str(equipment.id), "values")
        assert row[2] == "01/02/2024"
        panel.destroy()

    def test_mark_equipment_returned_before_assigned_date_shows_an_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        assert employee.id is not None
        equipment = repos.assigned_equipment.create(
            employee.id, "Portatil", date(2024, 1, 10)
        )
        assert equipment.id is not None
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)

        returned_dialog = MarkEquipmentReturnedDialog(
            panel, repos, equipment, on_change=panel._refresh_equipment
        )
        returned_dialog.returned_date_entry.value_var.set("2024-01-01")
        returned_dialog._handle_save()
        assert returned_dialog.error_label.cget("text") != ""
        returned_dialog.destroy()
        panel.destroy()

    def test_delete_equipment_with_nothing_selected_shows_an_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, employee = self._build_employee(conn)
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)
        panel._handle_delete_equipment()
        assert panel.equipment_error_label.cget("text") != ""
        panel.destroy()

    def test_delete_equipment_removes_it_and_records_audit(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        repos, employee = self._build_employee(conn)
        assert employee.id is not None
        equipment = repos.assigned_equipment.create(
            employee.id, "Portatil", date(2024, 1, 10)
        )
        assert equipment.id is not None
        panel = self._build_panel(tk_root, repos)
        panel.show_employee(employee)

        panel.equipment_tree.selection_set(str(equipment.id))
        panel._handle_delete_equipment()

        assert panel.equipment_tree.get_children() == ()
        actions = [entry.action for entry in repos.audit_log.list_all()]
        assert "equipment_deleted" in actions
        panel.destroy()

    def test_switching_employee_reloads_equipment_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, ana = self._build_employee(conn)
        assert ana.id is not None
        repos.assigned_equipment.create(ana.id, "Portatil de Ana", date(2024, 6, 1))
        dept = repos.departments.list_all()[0]
        assert dept.id is not None
        bob = repos.employees.create(
            EmployeeInput(
                first_name="Bob", last_name="Ruiz", email="bob@example.com", phone="",
                position="Ingeniero", department_id=dept.id, salary=28000,
                hire_date="2021-01-01",
            )
        )

        panel = self._build_panel(tk_root, repos)
        panel.show_employee(ana)
        assert len(panel.equipment_tree.get_children()) == 1
        panel.show_employee(bob)
        assert panel.equipment_tree.get_children() == ()
        panel.destroy()


def _build_repos_with_template(conn: sqlite3.Connection) -> tuple[Repositories, Employee, DocumentTemplate]:
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
    template = repos.document_templates.create(
        "Oferta de trabajo", "Estimado/a {nombre}, le ofrecemos el puesto de {puesto}."
    )
    return repos, employee, template


class TestGenerateDocumentDialogSaveAsDocument:
    def test_stores_a_pdf_not_a_txt(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Antes de anadir la generacion de PDF, este boton guardaba texto
        # plano; ahora debe guardar un PDF real con el mismo nombre de
        # plantilla pero extension .pdf.
        monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
        repos, employee, template = _build_repos_with_template(conn)
        dialog = GenerateDocumentDialog(
            tk_root, repos, employee, [template], on_change=lambda: None
        )

        dialog._handle_save_as_document()

        assert employee.id is not None
        summaries = repos.documents.list_for_employee(employee.id)
        assert len(summaries) == 1
        assert summaries[0].filename == f"{template.name} - {employee.full_name}.pdf"
        stored = repos.documents.get(summaries[0].id)
        assert stored.content.startswith(b"%PDF-")


class TestGenerateDocumentDialogDownloadPdf:
    def test_no_template_shows_error_and_writes_nothing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, tmp_path: Path
    ) -> None:
        repos, employee, _template = _build_repos_with_template(conn)
        dialog = GenerateDocumentDialog(tk_root, repos, employee, [], on_change=lambda: None)

        dialog._handle_download_pdf()

        assert dialog.error_label.cget("text") == "Seleccione una plantilla."
        assert list(tmp_path.iterdir()) == []
        dialog.destroy()

    def test_writes_a_valid_pdf_to_the_chosen_path(
        self,
        tk_root: tk.Tk,
        conn: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "oferta.pdf"
        monkeypatch.setattr(employee_page.filedialog, "asksaveasfilename", lambda **_k: str(target))
        monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
        repos, employee, template = _build_repos_with_template(conn)
        dialog = GenerateDocumentDialog(
            tk_root, repos, employee, [template], on_change=lambda: None
        )

        dialog._handle_download_pdf()

        assert target.read_bytes().startswith(b"%PDF-")
        dialog.destroy()

    def test_user_cancel_writes_nothing_and_shows_no_error(
        self,
        tk_root: tk.Tk,
        conn: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(employee_page.filedialog, "asksaveasfilename", lambda **_k: "")
        error_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: error_calls.append(a))
        repos, employee, template = _build_repos_with_template(conn)
        dialog = GenerateDocumentDialog(
            tk_root, repos, employee, [template], on_change=lambda: None
        )

        dialog._handle_download_pdf()

        assert error_calls == []
        assert list(tmp_path.iterdir()) == []
        dialog.destroy()


class TestGenerateDocumentDialogPrintPdf:
    def test_writes_a_valid_pdf_and_calls_startfile_with_the_print_verb(
        self,
        tk_root: tk.Tk,
        conn: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(employee_page.tempfile, "gettempdir", lambda: str(tmp_path))
        startfile_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(employee_page.os, "startfile", lambda *a: startfile_calls.append(a))
        monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
        repos, employee, template = _build_repos_with_template(conn)
        dialog = GenerateDocumentDialog(
            tk_root, repos, employee, [template], on_change=lambda: None
        )

        dialog._handle_print_pdf()

        assert len(startfile_calls) == 1
        written_path, verb = startfile_calls[0]
        assert verb == "print"
        written = Path(written_path)  # type: ignore[arg-type]
        assert written.read_bytes().startswith(b"%PDF-")
        assert written.parent == tmp_path / "contaapp_rh_print"
        dialog.destroy()

    def test_startfile_oserror_shows_error_mentioning_imprimir(
        self,
        tk_root: tk.Tk,
        conn: sqlite3.Connection,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(employee_page.tempfile, "gettempdir", lambda: str(tmp_path))

        def _raise(*_args: object) -> None:
            raise OSError("no application is associated with this file type")

        monkeypatch.setattr(employee_page.os, "startfile", _raise)
        error_calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: error_calls.append(a))
        repos, employee, template = _build_repos_with_template(conn)
        dialog = GenerateDocumentDialog(
            tk_root, repos, employee, [template], on_change=lambda: None
        )

        dialog._handle_print_pdf()

        assert len(error_calls) == 1
        title, message = error_calls[0][0], error_calls[0][1]
        assert title == "Imprimir"
        assert "imprimir" in str(message).lower()
        dialog.destroy()
