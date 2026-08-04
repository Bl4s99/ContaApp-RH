from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import date

import pytest

from app.data_export import export_employee_data
from app.repository import (
    EmployeeInput,
    NotFoundError,
    ProfessionalCategoryInput,
    Repositories,
    ShiftInput,
)

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


def _build_employee(conn: sqlite3.Connection) -> tuple[Repositories, int]:
    repos = Repositories.create(conn)
    dept = repos.departments.create("Ventas")
    assert dept.id is not None
    employee = repos.employees.create(
        EmployeeInput(
            first_name="Ana",
            last_name="García",
            email="ana@example.com",
            phone="600111222",
            position="Comercial",
            department_id=dept.id,
            salary=24000.0,
            hire_date="2022-03-01",
            dni_nie="12345678Z",
            ss_number="281234567890",
            bank_account="ES9121000418450200051332",
        )
    )
    assert employee.id is not None
    return repos, employee.id


class TestExportEmployeeData:
    def test_unknown_employee_raises(self, conn: sqlite3.Connection) -> None:
        repos = Repositories.create(conn)
        with pytest.raises(NotFoundError):
            export_employee_data(repos, 999)

    def test_produces_a_zip_with_datos_json(self, conn: sqlite3.Connection) -> None:
        repos, employee_id = _build_employee(conn)
        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            assert "datos.json" in archive.namelist()

    def test_datos_json_has_the_expected_top_level_sections(
        self, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee(conn)
        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert set(data.keys()) == {
            "empleado",
            "historial_puesto_salario",
            "ausencias",
            "asignaciones_turno_diarias",
            "nominas_generadas",
            "complementos_nomina",
            "finiquitos",
            "fichajes",
            "documentos",
            "accidentes_trabajo",
            "episodios_it",
            "checklist_incorporacion",
            "formacion_certificaciones",
        }

    def test_audit_log_is_deliberately_excluded(self, conn: sqlite3.Connection) -> None:
        # El registro de auditoría es metadato de uso del sistema, no un dato
        # "sobre" el empleado -- ver el docstring de app/data_export.py.
        repos, employee_id = _build_employee(conn)
        repos.audit_log.record("employee_created", f"Empleado: {employee_id}")
        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert "auditoria" not in data
        assert "registro_auditoria" not in data

    def test_employee_dict_has_readable_department_name_and_no_raw_photo(
        self, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee(conn)
        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert data["empleado"]["departamento"] == "Ventas"
        assert data["empleado"]["first_name"] == "Ana"
        assert "photo" not in data["empleado"]
        assert data["empleado"]["foto_incluida"] is False
        assert data["empleado"]["supervisor_directo"] is None
        assert data["empleado"]["encargado_de_departamento"] is None

    def test_employee_dict_has_readable_manager_full_name(
        self, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee(conn)
        dept_row = repos.departments.list_all()[0]
        assert dept_row.id is not None
        manager = repos.employees.create(
            EmployeeInput(
                first_name="Marta",
                last_name="Ruiz",
                email="marta@example.com",
                phone="",
                position="Jefa de equipo",
                department_id=dept_row.id,
                salary=32000.0,
                hire_date="2019-01-01",
            )
        )
        assert manager.id is not None
        repos.employees.update(
            employee_id,
            EmployeeInput(
                first_name="Ana", last_name="García", email="ana@example.com",
                phone="600111222", position="Comercial", department_id=dept_row.id,
                salary=24000.0, hire_date="2022-03-01", manager_id=manager.id,
            ),
        )

        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert data["empleado"]["supervisor_directo"] == "Marta Ruiz"
        assert data["empleado"]["manager_id"] == manager.id

    def test_employee_dict_has_readable_headed_department_name(
        self, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee(conn)
        headed_department = repos.departments.create("Marketing")
        assert headed_department.id is not None
        dept_row = repos.departments.list_all()[1]  # "Ventas", creada en _build_employee
        assert dept_row.id is not None
        repos.employees.update(
            employee_id,
            EmployeeInput(
                first_name="Ana", last_name="García", email="ana@example.com",
                phone="600111222", position="Comercial", department_id=dept_row.id,
                salary=24000.0, hire_date="2022-03-01", head_of_department_id=headed_department.id,
            ),
        )

        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert data["empleado"]["encargado_de_departamento"] == "Marketing"
        assert data["empleado"]["head_of_department_id"] == headed_department.id

    def test_employee_dict_has_readable_professional_category_and_agreement_name(
        self, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee(conn)
        agreement = repos.collective_agreements.create("Convenio Estatal de Comercio")
        assert agreement.id is not None
        category = repos.professional_categories.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement.id, name="Oficial de primera",
                minimum_salary=18000.0,
            )
        )
        assert category.id is not None
        dept = repos.departments.list_all()[0]
        assert dept.id is not None
        repos.employees.update(
            employee_id,
            EmployeeInput(
                first_name="Ana", last_name="García", email="ana@example.com",
                phone="600111222", position="Comercial", department_id=dept.id,
                salary=24000.0, hire_date="2022-03-01", professional_category_id=category.id,
            ),
        )

        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert data["empleado"]["categoria_profesional"] == "Oficial de primera"
        assert data["empleado"]["convenio_colectivo"] == "Convenio Estatal de Comercio"

    def test_employee_dict_has_null_category_and_agreement_when_unassigned(
        self, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee(conn)
        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert data["empleado"]["categoria_profesional"] is None
        assert data["empleado"]["convenio_colectivo"] is None

    def test_absences_are_included_regardless_of_status(
        self, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee(conn)
        day_type = repos.day_types.create("Vacaciones", "#2ecc71", is_vacation=True)
        assert day_type.id is not None
        repos.absences.request(employee_id, day_type.id, date(2026, 8, 3))  # pendiente

        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert len(data["ausencias"]) == 1
        assert data["ausencias"][0]["status"] == "pendiente"

    def test_work_accidents_included(self, conn: sqlite3.Connection) -> None:
        repos, employee_id = _build_employee(conn)
        repos.work_accidents.create(
            employee_id, date(2026, 2, 1), "Leve", "Corte con papel", False, False
        )

        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert len(data["accidentes_trabajo"]) == 1
        assert data["accidentes_trabajo"][0]["severity"] == "Leve"

    def test_it_episodes_included(self, conn: sqlite3.Connection) -> None:
        # Regresión: el test anterior de "secciones esperadas" solo
        # comprobaba que la CLAVE existiera en el JSON, no que el dato
        # realmente se exportara -- episodios_it faltaba por completo (son
        # datos de salud, categoría especial del art. 9 RGPD).
        repos, employee_id = _build_employee(conn)
        repos.it_episodes.create(employee_id, "Común", date(2026, 2, 1))

        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert len(data["episodios_it"]) == 1
        assert data["episodios_it"][0]["contingency"] == "Común"

    def test_training_records_included(self, conn: sqlite3.Connection) -> None:
        repos, employee_id = _build_employee(conn)
        repos.trainings.create(
            employee_id, "Carné de carretillero", date(2024, 1, 1), date(2027, 1, 1)
        )

        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert len(data["formacion_certificaciones"]) == 1
        assert data["formacion_certificaciones"][0]["name"] == "Carné de carretillero"
        assert data["formacion_certificaciones"][0]["expiration_date"] == "2027-01-01"

    def test_onboarding_checklist_included(self, conn: sqlite3.Connection) -> None:
        repos, employee_id = _build_employee(conn)
        task = repos.onboarding_tasks.create("Contrato firmado")
        assert task.id is not None
        repos.onboarding_tasks.mark_complete(employee_id, task.id, date(2026, 2, 1))

        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert len(data["checklist_incorporacion"]) == 1
        assert data["checklist_incorporacion"][0]["task"]["name"] == "Contrato firmado"
        assert data["checklist_incorporacion"][0]["completed_at"] == "2026-02-01"

    def test_daily_assignments_included(self, conn: sqlite3.Connection) -> None:
        repos, employee_id = _build_employee(conn)
        dept_row = repos.departments.list_all()[0]
        assert dept_row.id is not None
        shift = repos.shifts.create(
            ShiftInput(
                department_id=dept_row.id,
                name="Turno mañana",
                start_time="09:00",
                end_time="17:00",
                days_of_week=frozenset({1, 2, 3, 4, 5}),
            )
        )
        assert shift.id is not None
        repos.daily_assignments.set_day(employee_id, date(2026, 8, 3), shift.id)

        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert len(data["asignaciones_turno_diarias"]) == 1

    def test_documents_are_written_as_real_files_and_listed_in_datos_json(
        self, conn: sqlite3.Connection
    ) -> None:
        repos, employee_id = _build_employee(conn)
        doc = repos.documents.upload(employee_id, "contrato.pdf", "Contrato", b"contenido-pdf")
        assert doc.id is not None

        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            names = archive.namelist()
            expected_path = f"documentos/{doc.id}_contrato.pdf"
            assert expected_path in names
            assert archive.read(expected_path) == b"contenido-pdf"
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert data["documentos"] == [
            {
                "id": doc.id,
                "nombre": "contrato.pdf",
                "categoria": "Contrato",
                "subido_el": doc.uploaded_at.isoformat(),
                "fichero": expected_path,
            }
        ]

    def test_other_employees_data_is_not_included(self, conn: sqlite3.Connection) -> None:
        repos, employee_id = _build_employee(conn)
        dept_row = repos.departments.list_all()[0]
        assert dept_row.id is not None
        other = repos.employees.create(
            EmployeeInput(
                first_name="Luis",
                last_name="Pérez",
                email="luis@example.com",
                phone="",
                position="Comercial",
                department_id=dept_row.id,
                salary=21000.0,
                hire_date="2023-01-01",
            )
        )
        assert other.id is not None
        repos.documents.upload(other.id, "otro.pdf", "Contrato", b"otro-contenido")

        archive_bytes = export_employee_data(repos, employee_id)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            assert not any("otro.pdf" in name for name in archive.namelist())
            data = json.loads(archive.read("datos.json").decode("utf-8"))
        assert data["documentos"] == []
