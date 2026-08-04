from __future__ import annotations

import sqlite3
import tkinter as tk
from datetime import date
from tkinter import ttk

from app.repository import EmployeeInput, Repositories
from app.welcome_page import WelcomePage

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


def _has_button(widget: tk.Misc, text: str) -> bool:
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button) and child.cget("text") == text:
            return True
        if _has_button(child, text):
            return True
    return False


def _label_texts(widget: tk.Misc) -> list[str]:
    texts = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Label):
            text = child.cget("text")
            if text:
                texts.append(text)
        texts.extend(_label_texts(child))
    return texts


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
            is_admin=False, locked_department_id=ventas_id,
        )
        texts = " ".join(_label_texts(page))
        assert "Ana Lopez" in texts
        assert "Luis Perez" not in texts
        assert "Ventas" in texts
        assert "Producción" not in texts
        page.destroy()
