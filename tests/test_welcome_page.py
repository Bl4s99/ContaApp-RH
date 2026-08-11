from __future__ import annotations

import sqlite3
import tkinter as tk
from collections.abc import Callable
from datetime import date
from tkinter import ttk
from typing import TypedDict

from app.repository import CandidateInput, EmployeeInput, Repositories
from app.welcome_page import WelcomePage, _payroll_needs_warning

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


def _has_button(widget: tk.Misc, text: str) -> bool:
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button) and child.cget("text") == text:
            return True
        if _has_button(child, text):
            return True
    return False


def _find_button(widget: tk.Misc, text: str) -> ttk.Button | None:
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button) and child.cget("text") == text:
            return child
        found = _find_button(child, text)
        if found is not None:
            return found
    return None


def _label_texts(widget: tk.Misc) -> list[str]:
    texts = []
    for child in widget.winfo_children():
        # tk.Label también: el banner de alertas usa Label planos (color
        # fijado a mano, igual que el disclaimer de nóminas), no ttk.Label.
        if isinstance(child, (ttk.Label, tk.Label)):
            text = child.cget("text")
            if text:
                texts.append(text)
        texts.extend(_label_texts(child))
    return texts


def _card_values_by_caption(page: WelcomePage) -> dict[str, str]:
    # Cada tarjeta es un ttk.Frame con dos Label hijos directos (valor,
    # caption) -- ver WelcomePage._make_card().
    result: dict[str, str] = {}
    for card in page._cards_frame.winfo_children():
        labels = [c for c in card.winfo_children() if isinstance(c, ttk.Label)]
        if len(labels) == 2:
            value_label, caption_label = labels
            result[str(caption_label.cget("text"))] = str(value_label.cget("text"))
    return result


class _WelcomePageCallbacks(TypedDict):
    on_go_employees: Callable[[], None]
    on_go_payroll: Callable[[], None]
    on_go_departments: Callable[[], None]
    on_export: Callable[[], None]
    on_go_calendar: Callable[[], None]
    on_go_alerts: Callable[[], None]
    on_go_org_chart: Callable[[], None]
    on_go_candidates: Callable[[], None]


def _no_op_callbacks() -> _WelcomePageCallbacks:
    # TypedDict (no un dict[str, Callable] a secas) para que **-desempaquetar
    # esto en WelcomePage(...) se compruebe con precisión por parámetro --
    # con un dict normal, mypy no distingue estas claves de is_admin/
    # locked_department_id y las rechaza todas como "tipo incompatible".
    return _WelcomePageCallbacks(
        on_go_employees=lambda: None,
        on_go_payroll=lambda: None,
        on_go_departments=lambda: None,
        on_export=lambda: None,
        on_go_calendar=lambda: None,
        on_go_alerts=lambda: None,
        on_go_org_chart=lambda: None,
        on_go_candidates=lambda: None,
    )


def _make_employee(repos: Repositories, department_id: int, email: str) -> int:
    emp = repos.employees.create(
        EmployeeInput(
            first_name="Test",
            last_name="Employee",
            email=email,
            phone="",
            position="Puesto",
            department_id=department_id,
            salary=24000.0,
            hire_date="2020-01-01",
        )
    )
    assert emp.id is not None
    return emp.id


class TestWelcomePageDepartmentsQuickAccess:
    def _build_repos(self, conn: sqlite3.Connection) -> Repositories:
        return Repositories.create(conn)

    def test_admin_sees_departments_quick_access(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = self._build_repos(conn)
        page = WelcomePage(
            tk_root,
            repos,
            on_go_employees=lambda: None,
            on_go_payroll=lambda: None,
            on_go_departments=lambda: None,
            on_export=lambda: None,
            on_go_calendar=lambda: None,
            on_go_alerts=lambda: None,
            on_go_org_chart=lambda: None,
            on_go_candidates=lambda: None,
            is_admin=True,
        )
        assert _has_button(page, "Departamentos")
        page.destroy()

    def test_encargado_does_not_see_departments_quick_access(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        # Regresión: este botón llamaba a MainWindow._open_department_manager()
        # sin ninguna comprobación de rol -- cualquier encargado podía crear
        # o eliminar cualquier departamento, y desde ahí escribir en el
        # calendario laboral de un departamento ajeno. Ver también el guard
        # equivalente dentro de la propia MainWindow._open_department_manager().
        repos = self._build_repos(conn)
        page = WelcomePage(
            tk_root,
            repos,
            on_go_employees=lambda: None,
            on_go_payroll=lambda: None,
            on_go_departments=lambda: None,
            on_export=lambda: None,
            on_go_calendar=lambda: None,
            on_go_alerts=lambda: None,
            on_go_org_chart=lambda: None,
            on_go_candidates=lambda: None,
            is_admin=False,
        )
        assert not _has_button(page, "Departamentos")
        # El resto de accesos rápidos siguen disponibles para un encargado.
        assert _has_button(page, "Lista de empleados")
        assert _has_button(page, "Nóminas")
        assert _has_button(page, "Exportar CSV...")
        page.destroy()


class TestWelcomePageDetailLinesScopedByDepartment:
    # Regresión: "Ausentes hoy"/"Cierres hoy" mostraban nombre + categoría
    # (incl. bajas médicas) de TODA la empresa a cualquier encargado -- las
    # 4 tarjetas de conteo siguen siendo agregadas a propósito (decisión ya
    # tomada, ver README), pero estas líneas de detalle nombran a personas
    # concretas y sí deben restringirse al propio departamento.
    def _build_two_departments_with_an_absence_and_a_closure_each(
        self, conn: sqlite3.Connection
    ) -> tuple[Repositories, int, int]:
        repos = Repositories.create(conn)
        ventas = repos.departments.create("Ventas")
        produccion = repos.departments.create("Producción")
        assert ventas.id is not None and produccion.id is not None
        day_type = repos.day_types.create("Enfermedad", "#e67e22")
        assert day_type.id is not None

        emp_ventas = repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@example.com", phone="",
                position="Comercial", department_id=ventas.id, salary=24000,
                hire_date="2020-01-01",
            )
        )
        emp_produccion = repos.employees.create(
            EmployeeInput(
                first_name="Luis", last_name="Perez", email="luis@example.com", phone="",
                position="Operario", department_id=produccion.id, salary=22000,
                hire_date="2020-01-01",
            )
        )
        assert emp_ventas.id is not None and emp_produccion.id is not None
        today = date.today()
        repos.absences.set_day(emp_ventas.id, today, day_type.id)
        repos.absences.set_day(emp_produccion.id, today, day_type.id)
        repos.closures.set_day(ventas.id, today, day_type.id)
        repos.closures.set_day(produccion.id, today, day_type.id)
        return repos, ventas.id, produccion.id

    def test_admin_sees_detail_lines_for_every_department(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _ventas_id, _produccion_id = (
            self._build_two_departments_with_an_absence_and_a_closure_each(conn)
        )
        page = WelcomePage(
            tk_root, repos,
            on_go_employees=lambda: None, on_go_payroll=lambda: None,
            on_go_departments=lambda: None, on_export=lambda: None,
            on_go_calendar=lambda: None, on_go_alerts=lambda: None,
            on_go_org_chart=lambda: None, on_go_candidates=lambda: None,
            is_admin=True, locked_department_id=None,
        )
        texts = " ".join(_label_texts(page))
        assert "Ana Lopez" in texts and "Luis Perez" in texts
        assert "Ventas" in texts and "Producción" in texts
        page.destroy()

    def test_encargado_only_sees_detail_lines_for_their_own_department(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, ventas_id, _produccion_id = (
            self._build_two_departments_with_an_absence_and_a_closure_each(conn)
        )
        page = WelcomePage(
            tk_root, repos,
            on_go_employees=lambda: None, on_go_payroll=lambda: None,
            on_go_departments=lambda: None, on_export=lambda: None,
            on_go_calendar=lambda: None, on_go_alerts=lambda: None,
            on_go_org_chart=lambda: None, on_go_candidates=lambda: None,
            is_admin=False, locked_department_id=ventas_id,
        )
        texts = " ".join(_label_texts(page))
        assert "Ana Lopez" in texts
        assert "Luis Perez" not in texts
        assert "Ventas" in texts
        assert "Producción" not in texts
        page.destroy()


class TestWelcomePageNewCards:
    def test_payroll_generated_count_out_of_active_employees(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        emp1 = _make_employee(repos, dept.id, "a@example.com")
        _make_employee(repos, dept.id, "b@example.com")
        today = date.today()
        repos.payroll_records.generate(emp1, today.year, today.month)

        page = WelcomePage(tk_root, repos, **_no_op_callbacks())
        assert _card_values_by_caption(page)["Nóminas generadas (mes actual)"] == "1/2"
        page.destroy()

    def test_pending_absence_requests_count(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        emp = _make_employee(repos, dept.id, "a@example.com")
        day_type = repos.day_types.create("Vacaciones", "#2ecc71")
        assert day_type.id is not None
        repos.absences.request(emp, day_type.id, date.today())

        page = WelcomePage(tk_root, repos, **_no_op_callbacks())
        assert _card_values_by_caption(page)["Solicitudes pendientes"] == "1"
        page.destroy()

    def test_candidates_in_process_excludes_terminal_phases(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        for phase in ("Recibido", "Entrevista", "Contratado", "Descartado"):
            repos.candidates.create(
                CandidateInput(
                    first_name="Cand",
                    last_name=phase,
                    email=f"{phase.lower()}@example.com",
                    phone="",
                    position="Puesto",
                    department_id=dept.id,
                    phase=phase,
                )
            )

        page = WelcomePage(tk_root, repos, **_no_op_callbacks())
        # Solo "Recibido" y "Entrevista" cuentan -- "Contratado"/"Descartado"
        # son las dos fases terminales, ya no "en proceso".
        assert _card_values_by_caption(page)["Candidatos en proceso"] == "2"
        page.destroy()

    def test_cards_wrap_onto_a_second_row(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        # Regresión: con 7 tarjetas (antes 4) en una rejilla de 4 columnas,
        # la 5ª debe caer en la fila 1, no seguir empaquetándose en una
        # sola fila interminable.
        repos = Repositories.create(conn)
        page = WelcomePage(tk_root, repos, **_no_op_callbacks())
        cards = page._cards_frame.winfo_children()
        assert len(cards) == 7
        fifth_card = cards[4]
        assert isinstance(fifth_card, ttk.Frame)
        assert int(fifth_card.grid_info()["row"]) == 1
        page.destroy()


class TestWelcomePageNewCardsScopedByDepartment:
    # A diferencia de las 4 tarjetas originales (compañía-completa a
    # propósito), estas 3 SÍ se acotan por locked_department_id -- ver el
    # comentario en WelcomePage.refresh() sobre por qué.
    def _build_two_departments_each_with_a_pending_request(
        self, conn: sqlite3.Connection
    ) -> tuple[Repositories, int, int]:
        repos = Repositories.create(conn)
        ventas = repos.departments.create("Ventas")
        produccion = repos.departments.create("Producción")
        assert ventas.id is not None and produccion.id is not None
        day_type = repos.day_types.create("Vacaciones", "#2ecc71")
        assert day_type.id is not None
        emp_ventas = _make_employee(repos, ventas.id, "a@example.com")
        emp_produccion = _make_employee(repos, produccion.id, "b@example.com")
        repos.absences.request(emp_ventas, day_type.id, date.today())
        repos.absences.request(emp_produccion, day_type.id, date.today())
        return repos, ventas.id, produccion.id

    def test_admin_sees_the_combined_company_wide_count(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, _ventas_id, _produccion_id = (
            self._build_two_departments_each_with_a_pending_request(conn)
        )
        page = WelcomePage(
            tk_root, repos, **_no_op_callbacks(), is_admin=True, locked_department_id=None
        )
        assert _card_values_by_caption(page)["Solicitudes pendientes"] == "2"
        page.destroy()

    def test_encargado_sees_only_their_own_department(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos, ventas_id, _produccion_id = (
            self._build_two_departments_each_with_a_pending_request(conn)
        )
        page = WelcomePage(
            tk_root, repos, **_no_op_callbacks(), is_admin=False, locked_department_id=ventas_id
        )
        assert _card_values_by_caption(page)["Solicitudes pendientes"] == "1"
        page.destroy()


class TestWelcomePageAlertBanner:
    def test_hidden_when_there_are_no_alerts(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        page = WelcomePage(tk_root, repos, **_no_op_callbacks())
        # winfo_ismapped() exige un ciclo real del bucle de eventos para
        # reflejar el estado -- winfo_manager() (vacío si no está bajo
        # ningún gestor de geometría) es la comprobación inmediata y fiable.
        assert page._alert_banner.winfo_manager() == ""
        page.destroy()

    def test_shown_with_the_correct_count_when_there_are_alerts(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@example.com", phone="",
                position="Comercial", department_id=dept.id, salary=24000.0,
                hire_date="2020-01-01", contract_type="Temporal",
                contract_end_date=date.today().isoformat(),
                prl_training_date="2020-01-01",
            )
        )
        page = WelcomePage(tk_root, repos, **_no_op_callbacks())
        assert page._alert_banner.winfo_manager() != ""
        texts = " ".join(_label_texts(page))
        assert "1 alerta" in texts
        page.destroy()

    def test_ver_alertas_button_invokes_on_go_alerts(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dept = repos.departments.create("Ventas")
        assert dept.id is not None
        repos.employees.create(
            EmployeeInput(
                first_name="Ana", last_name="Lopez", email="ana@example.com", phone="",
                position="Comercial", department_id=dept.id, salary=24000.0,
                hire_date="2020-01-01", contract_type="Temporal",
                contract_end_date=date.today().isoformat(),
                prl_training_date="2020-01-01",
            )
        )
        calls: list[int] = []
        callbacks = _no_op_callbacks()
        callbacks["on_go_alerts"] = lambda: calls.append(1)
        page = WelcomePage(tk_root, repos, **callbacks)
        button = _find_button(page._alert_banner, "Ver alertas")
        assert button is not None
        button.invoke()
        assert calls == [1]
        page.destroy()


class TestWelcomePageNewQuickAccessButtons:
    def test_all_four_new_buttons_visible_for_admin(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        page = WelcomePage(tk_root, repos, **_no_op_callbacks(), is_admin=True)
        for text in ("Calendario", "Alertas", "Organigrama", "Candidatos"):
            assert _has_button(page, text)
        page.destroy()

    def test_all_four_new_buttons_visible_for_encargado(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        page = WelcomePage(tk_root, repos, **_no_op_callbacks(), is_admin=False)
        for text in ("Calendario", "Alertas", "Organigrama", "Candidatos"):
            assert _has_button(page, text)
        page.destroy()


class TestPayrollNeedsWarning:
    def test_incomplete_and_day_29_or_later_warns(self) -> None:
        assert _payroll_needs_warning(0, 10, date(2026, 8, 29)) is True
        assert _payroll_needs_warning(5, 10, date(2026, 8, 31)) is True

    def test_incomplete_but_before_day_29_does_not_warn(self) -> None:
        assert _payroll_needs_warning(0, 10, date(2026, 8, 28)) is False
        assert _payroll_needs_warning(0, 10, date(2026, 8, 1)) is False

    def test_complete_never_warns_even_on_day_29(self) -> None:
        assert _payroll_needs_warning(10, 10, date(2026, 8, 29)) is False


class TestMakeCardWarningStyle:
    def test_warning_true_uses_the_warning_ttk_style(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        page = WelcomePage(tk_root, repos, **_no_op_callbacks())
        for widget in page._cards_frame.winfo_children():
            widget.destroy()
        page._make_card(0, 0, "5/10", "Nóminas generadas (mes actual)", warning=True)
        card = page._cards_frame.winfo_children()[0]
        assert card.cget("style") == "CardWarning.TFrame"
        page.destroy()
