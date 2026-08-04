from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from app import validation
from app.models import User
from app.repository import (
    AUDIT_LOGIN_FAILURE,
    AUDIT_LOGIN_SUCCESS,
    AppSettingsRepository,
    AssignedEquipmentRepository,
    AuditLogRepository,
    CandidateInput,
    CandidateRepository,
    CollectiveAgreementRepository,
    DepartmentRepository,
    DocumentTemplateRepository,
    DuplicateError,
    EmployeeDocumentRepository,
    EmployeeHistoryRepository,
    EmployeeInput,
    EmployeeRepository,
    EmployeeTrainingRepository,
    ITEpisodeRepository,
    NotFoundError,
    OnboardingTaskRepository,
    PayrollRecordRepository,
    PayrollSettingsRepository,
    PayrollSupplementRepository,
    ObjectiveRepository,
    PerformanceReviewRepository,
    ProfessionalCategoryInput,
    ProfessionalCategoryRepository,
    ReferenceInUseError,
    RepositoryError,
    SeveranceSettlementRepository,
    UserRepository,
    WorkAccidentRepository,
)
from app.severance import SeveranceCalculation, calculate_severance


def make_input(**overrides: object) -> EmployeeInput:
    defaults: dict[str, object] = dict(
        first_name="Ana",
        last_name="Lopez",
        email="ana.lopez@example.com",
        phone="+34 600 111 222",
        position="Ingeniera",
        department_id=1,
        salary=35000.0,
        hire_date="2023-05-01",
        active=True,
    )
    defaults.update(overrides)
    return EmployeeInput(**defaults)  # type: ignore[arg-type]


class TestDepartmentRepository:
    def test_create_and_get(self, conn: sqlite3.Connection) -> None:
        repo = DepartmentRepository(conn)
        created = repo.create("Ingeniería")
        assert created.id is not None
        fetched = repo.get(created.id)
        assert fetched.name == "Ingeniería"

    def test_create_duplicate_name_rejected(self, conn: sqlite3.Connection) -> None:
        repo = DepartmentRepository(conn)
        repo.create("Ventas")
        with pytest.raises(DuplicateError):
            repo.create("Ventas")

    def test_create_duplicate_name_case_insensitive(self, conn: sqlite3.Connection) -> None:
        repo = DepartmentRepository(conn)
        repo.create("Ventas")
        with pytest.raises(DuplicateError):
            repo.create("ventas")

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        repo = DepartmentRepository(conn)
        with pytest.raises(NotFoundError):
            repo.get(999)

    def test_list_all_sorted_by_name(self, conn: sqlite3.Connection) -> None:
        repo = DepartmentRepository(conn)
        repo.create("Ventas")
        repo.create("Almacén")
        names = [d.name for d in repo.list_all()]
        assert names == ["Almacén", "Ventas"]

    def test_delete_removes_department(self, conn: sqlite3.Connection) -> None:
        repo = DepartmentRepository(conn)
        dept = repo.create("Temporal")
        assert dept.id is not None
        repo.delete(dept.id)
        with pytest.raises(NotFoundError):
            repo.get(dept.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        repo = DepartmentRepository(conn)
        with pytest.raises(NotFoundError):
            repo.delete(999)

    def test_delete_in_use_is_blocked(self, conn: sqlite3.Connection) -> None:
        dept_repo = DepartmentRepository(conn)
        emp_repo = EmployeeRepository(conn)
        dept = dept_repo.create("Ingeniería")
        assert dept.id is not None
        emp_repo.create(make_input(department_id=dept.id))
        with pytest.raises(ReferenceInUseError):
            dept_repo.delete(dept.id)

    def test_delete_blocked_by_candidates_names_candidates_not_employees(
        self, conn: sqlite3.Connection
    ) -> None:
        # Un departamento sin empleados pero con candidatos en proceso debe
        # dar un mensaje que hable de candidatos, no del mensaje genérico de
        # "empleados asignados" -- ver el comentario en
        # DepartmentRepository.delete() sobre por qué esto necesitaba una
        # comprobación explícita en vez de fiarse del IntegrityError de la
        # FK (que no distingue qué tabla lo causó).
        dept_repo = DepartmentRepository(conn)
        dept = dept_repo.create("Ingeniería")
        assert dept.id is not None
        CandidateRepository(conn).create(
            CandidateInput(
                first_name="Luis", last_name="Perez", email="luis@example.com", phone="",
                position="Comercial", department_id=dept.id, phase="Recibido",
            )
        )
        with pytest.raises(ReferenceInUseError, match="candidatos"):
            dept_repo.delete(dept.id)

    def test_delete_blocked_by_both_employees_and_candidates_names_both(
        self, conn: sqlite3.Connection
    ) -> None:
        dept_repo = DepartmentRepository(conn)
        dept = dept_repo.create("Ingeniería")
        assert dept.id is not None
        EmployeeRepository(conn).create(make_input(department_id=dept.id))
        CandidateRepository(conn).create(
            CandidateInput(
                first_name="Luis", last_name="Perez", email="luis@example.com", phone="",
                position="Comercial", department_id=dept.id, phase="Recibido",
            )
        )
        with pytest.raises(ReferenceInUseError, match="empleados y candidatos"):
            dept_repo.delete(dept.id)

    def test_delete_blocked_by_user_assigned_as_encargado(self, conn: sqlite3.Connection) -> None:
        # users.department_id es ON DELETE SET NULL (no RESTRICT), así que
        # sin esta comprobación explícita el borrado tendría éxito y
        # dejaría al encargado con department_id=NULL -- el mismo valor
        # que usa un administrador para "sin restricción" (ver
        # MainWindow.__init__ en app/ui.py), concediéndole sin querer
        # acceso a todos los departamentos.
        dept_repo = DepartmentRepository(conn)
        dept = dept_repo.create("Ingeniería")
        assert dept.id is not None
        UserRepository(conn).create(
            "encargado1", "clave12345", role="encargado", department_id=dept.id
        )
        with pytest.raises(ReferenceInUseError, match="usuarios"):
            dept_repo.delete(dept.id)

    def test_delete_blocked_by_employees_and_users_names_both(
        self, conn: sqlite3.Connection
    ) -> None:
        dept_repo = DepartmentRepository(conn)
        dept = dept_repo.create("Ingeniería")
        assert dept.id is not None
        EmployeeRepository(conn).create(make_input(department_id=dept.id))
        UserRepository(conn).create(
            "encargado1", "clave12345", role="encargado", department_id=dept.id
        )
        with pytest.raises(ReferenceInUseError, match="empleados.*usuarios"):
            dept_repo.delete(dept.id)


class TestEmployeeRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    def test_create_returns_persisted_employee(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id))
        assert employee.id is not None
        assert employee.full_name == "Ana Lopez"
        assert employee.email == "ana.lopez@example.com"
        assert employee.active is True

    def test_create_normalizes_email_case(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(
            make_input(department_id=department_id, email="Ana.Lopez@EXAMPLE.com")
        )
        assert employee.email == "ana.lopez@example.com"

    def test_create_with_unknown_department_raises(self, conn: sqlite3.Connection) -> None:
        repo = EmployeeRepository(conn)
        with pytest.raises(NotFoundError):
            repo.create(make_input(department_id=999))

    def test_create_with_invalid_email_raises_validation_error(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        with pytest.raises(validation.ValidationError):
            repo.create(make_input(department_id=department_id, email="not-an-email"))

    def test_create_duplicate_email_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.create(make_input(department_id=department_id))
        with pytest.raises(DuplicateError):
            repo.create(make_input(department_id=department_id, first_name="Otra"))

    def test_update_changes_fields(self, conn: sqlite3.Connection, department_id: int) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id))
        assert employee.id is not None
        updated = repo.update(
            employee.id, make_input(department_id=department_id, position="Ingeniera Senior")
        )
        assert updated.position == "Ingeniera Senior"

    def test_update_missing_employee_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        with pytest.raises(NotFoundError):
            repo.update(999, make_input(department_id=department_id))

    def test_delete_removes_employee(self, conn: sqlite3.Connection, department_id: int) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id))
        assert employee.id is not None
        repo.delete(employee.id)
        with pytest.raises(NotFoundError):
            repo.get(employee.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        repo = EmployeeRepository(conn)
        with pytest.raises(NotFoundError):
            repo.delete(999)

    def test_search_by_name_fragment(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.create(make_input(department_id=department_id, first_name="Ana", email="a@x.com"))
        repo.create(make_input(department_id=department_id, first_name="Bruno", email="b@x.com"))
        results = repo.search(query="ana")
        assert [e.first_name for e in results] == ["Ana"]

    def test_search_by_email(self, conn: sqlite3.Connection, department_id: int) -> None:
        repo = EmployeeRepository(conn)
        repo.create(make_input(department_id=department_id, email="findme@example.com"))
        results = repo.search(query="findme")
        assert len(results) == 1

    def test_search_escapes_like_wildcards(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.create(
            make_input(department_id=department_id, first_name="A_B", email="weird@example.com")
        )
        repo.create(
            make_input(department_id=department_id, first_name="AxB", email="other@example.com")
        )
        results = repo.search(query="A_B")
        assert [e.first_name for e in results] == ["A_B"]

    def test_search_filters_by_department(self, conn: sqlite3.Connection) -> None:
        dept_repo = DepartmentRepository(conn)
        emp_repo = EmployeeRepository(conn)
        dept_a = dept_repo.create("A")
        dept_b = dept_repo.create("B")
        assert dept_a.id is not None and dept_b.id is not None
        emp_repo.create(make_input(department_id=dept_a.id, email="a@x.com"))
        emp_repo.create(make_input(department_id=dept_b.id, email="b@x.com"))
        results = emp_repo.search(department_id=dept_a.id)
        assert len(results) == 1
        assert results[0].department_id == dept_a.id

    def test_search_filters_by_active(self, conn: sqlite3.Connection, department_id: int) -> None:
        repo = EmployeeRepository(conn)
        repo.create(make_input(department_id=department_id, email="active@x.com", active=True))
        repo.create(
            make_input(department_id=department_id, email="inactive@x.com", active=False)
        )
        active_results = repo.search(active_only=True)
        inactive_results = repo.search(active_only=False)
        assert len(active_results) == 1
        assert len(inactive_results) == 1
        assert active_results[0].email == "active@x.com"

    def test_list_all_orders_by_last_then_first_name(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.create(
            make_input(
                department_id=department_id,
                first_name="Zoe",
                last_name="Alonso",
                email="z@x.com",
            )
        )
        repo.create(
            make_input(
                department_id=department_id,
                first_name="Ana",
                last_name="Bravo",
                email="a@x.com",
            )
        )
        names = [(e.last_name, e.first_name) for e in repo.list_all()]
        assert names == [("Alonso", "Zoe"), ("Bravo", "Ana")]


class TestEmployeeManagerId:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    def test_create_with_manager_persists_and_round_trips(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        manager = repo.create(make_input(department_id=department_id, email="jefa@x.com"))
        assert manager.id is not None
        report = repo.create(
            make_input(department_id=department_id, email="reporta@x.com", manager_id=manager.id)
        )
        assert report.manager_id == manager.id
        assert report.id is not None
        assert repo.get(report.id).manager_id == manager.id

    def test_manager_id_defaults_to_none(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id))
        assert employee.manager_id is None

    def test_search_also_returns_manager_id(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # search()/list_all() usan _EMPLOYEE_SUMMARY_COLUMNS (una lista
        # explícita de columnas, no SELECT *) -- una comprobación aparte de
        # test_create_with_manager_persists_and_round_trips (que solo pasa
        # por get()) para no dar por hecho que manager_id se propagó a las
        # dos vías de lectura por igual.
        repo = EmployeeRepository(conn)
        manager = repo.create(make_input(department_id=department_id, email="jefa2@x.com"))
        assert manager.id is not None
        repo.create(
            make_input(department_id=department_id, email="reporta2@x.com", manager_id=manager.id)
        )
        [found] = [e for e in repo.search(department_id=department_id) if e.email == "reporta2@x.com"]
        assert found.manager_id == manager.id

    def test_update_can_assign_and_clear_the_manager(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        manager = repo.create(make_input(department_id=department_id, email="jefa3@x.com"))
        assert manager.id is not None
        employee = repo.create(make_input(department_id=department_id, email="empleado3@x.com"))
        assert employee.id is not None

        assigned = repo.update(
            employee.id,
            make_input(department_id=department_id, email="empleado3@x.com", manager_id=manager.id),
        )
        assert assigned.manager_id == manager.id

        cleared = repo.update(
            employee.id,
            make_input(department_id=department_id, email="empleado3@x.com", manager_id=None),
        )
        assert cleared.manager_id is None

    def test_manager_pointing_to_nonexistent_employee_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        with pytest.raises(NotFoundError):
            repo.create(make_input(department_id=department_id, manager_id=999))

    def test_manager_from_a_different_department_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        other_department = DepartmentRepository(conn).create("Marketing")
        assert other_department.id is not None
        outsider = repo.create(make_input(department_id=other_department.id, email="fuera@x.com"))
        assert outsider.id is not None
        with pytest.raises(validation.ValidationError):
            repo.create(
                make_input(department_id=department_id, manager_id=outsider.id, email="a@x.com")
            )

    def test_inactive_employee_cannot_be_assigned_as_manager(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        former_manager = repo.create(make_input(department_id=department_id, email="baja@x.com"))
        assert former_manager.id is not None
        repo.terminate(former_manager.id, "2026-01-01", "Baja voluntaria")
        with pytest.raises(validation.ValidationError):
            repo.create(
                make_input(
                    department_id=department_id, manager_id=former_manager.id, email="a@x.com"
                )
            )

    def test_self_reference_is_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id, email="a@x.com"))
        assert employee.id is not None
        with pytest.raises(validation.ValidationError):
            repo.update(
                employee.id,
                make_input(department_id=department_id, email="a@x.com", manager_id=employee.id),
            )

    def test_indirect_cycle_is_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # A supervisa a B, B supervisa a C -- intentar hacer que A pase a
        # depender de C (que ya depende, indirectamente, de A) cerraría el
        # ciclo A -> C -> B -> A.
        repo = EmployeeRepository(conn)
        a = repo.create(make_input(department_id=department_id, email="a@x.com"))
        assert a.id is not None
        b = repo.create(make_input(department_id=department_id, email="b@x.com", manager_id=a.id))
        assert b.id is not None
        c = repo.create(make_input(department_id=department_id, email="c@x.com", manager_id=b.id))
        assert c.id is not None
        with pytest.raises(validation.ValidationError):
            repo.update(
                a.id, make_input(department_id=department_id, email="a@x.com", manager_id=c.id)
            )

    def test_unrelated_reassignment_still_works_despite_an_existing_hierarchy(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # Regresión de diseño: la comprobación de ciclos no debe rechazar
        # una reasignación válida solo porque YA existe alguna jerarquía en
        # el departamento -- debe rechazar únicamente el caso que de verdad
        # cerraría un ciclo.
        repo = EmployeeRepository(conn)
        a = repo.create(make_input(department_id=department_id, email="a@x.com"))
        assert a.id is not None
        b = repo.create(make_input(department_id=department_id, email="b@x.com", manager_id=a.id))
        assert b.id is not None
        c = repo.create(make_input(department_id=department_id, email="c@x.com"))
        assert c.id is not None
        updated = repo.update(
            c.id, make_input(department_id=department_id, email="c@x.com", manager_id=b.id)
        )
        assert updated.manager_id == b.id

    def test_deleting_the_manager_clears_manager_id_on_their_reports(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # ON DELETE SET NULL a nivel de esquema -- verificado aquí a través
        # del propio repositorio, no solo con SQL suelto.
        repo = EmployeeRepository(conn)
        manager = repo.create(make_input(department_id=department_id, email="jefa4@x.com"))
        assert manager.id is not None
        report = repo.create(
            make_input(department_id=department_id, email="reporta4@x.com", manager_id=manager.id)
        )
        assert report.id is not None
        repo.delete(manager.id)
        assert repo.get(report.id).manager_id is None


class TestEmployeeHeadOfDepartment:
    """Puramente informativo (a diferencia de manager_id, no tiene ninguna
    comprobación de ciclo/departamento/actividad): marca qué empleado
    encabeza qué departamento, sin tocar el sistema de login/permisos
    (User.role == "encargado" sigue siendo la única vía real de permisos,
    completamente aparte)."""

    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    def test_create_with_head_of_department_persists_and_round_trips(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        other_department = DepartmentRepository(conn).create("Marketing")
        assert other_department.id is not None
        employee = repo.create(
            make_input(department_id=department_id, head_of_department_id=other_department.id)
        )
        assert employee.head_of_department_id == other_department.id
        assert employee.id is not None
        assert repo.get(employee.id).head_of_department_id == other_department.id

    def test_defaults_to_none(self, conn: sqlite3.Connection, department_id: int) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id))
        assert employee.head_of_department_id is None

    def test_search_also_returns_head_of_department_id(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.create(
            make_input(department_id=department_id, head_of_department_id=department_id)
        )
        [found] = repo.search(department_id=department_id)
        assert found.head_of_department_id == department_id

    def test_update_can_assign_and_clear_it(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id))
        assert employee.id is not None

        assigned = repo.update(
            employee.id, make_input(department_id=department_id, head_of_department_id=department_id)
        )
        assert assigned.head_of_department_id == department_id

        cleared = repo.update(
            employee.id, make_input(department_id=department_id, head_of_department_id=None)
        )
        assert cleared.head_of_department_id is None

    def test_nonexistent_department_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        with pytest.raises(NotFoundError):
            repo.create(make_input(department_id=department_id, head_of_department_id=999))

    def test_can_head_a_different_department_than_ones_own(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # A diferencia de manager_id, no hay ninguna restricción de "mismo
        # departamento": alguien puede figurar como encargado de un
        # departamento distinto al suyo propio.
        repo = EmployeeRepository(conn)
        other_department = DepartmentRepository(conn).create("Marketing")
        assert other_department.id is not None
        employee = repo.create(
            make_input(department_id=department_id, head_of_department_id=other_department.id)
        )
        assert employee.department_id == department_id
        assert employee.head_of_department_id == other_department.id

    def test_deleting_the_headed_department_clears_the_field(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # ON DELETE SET NULL a nivel de esquema.
        repo = EmployeeRepository(conn)
        other_department = DepartmentRepository(conn).create("Marketing")
        assert other_department.id is not None
        employee = repo.create(
            make_input(department_id=department_id, head_of_department_id=other_department.id)
        )
        assert employee.id is not None
        DepartmentRepository(conn).delete(other_department.id)
        assert repo.get(employee.id).head_of_department_id is None


class TestEmployeeHistoryRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    def test_create_records_an_initial_entry(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_input(department_id=department_id, position="Junior", salary=20000)
        )
        assert employee.id is not None
        [entry] = EmployeeHistoryRepository(conn).list_for_employee(employee.id)
        assert entry.position == "Junior"
        assert entry.salary == 20000
        assert entry.effective_date == employee.hire_date
        assert entry.note == "Alta inicial"

    def test_update_without_position_or_salary_change_adds_no_entry(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        emp_repo = EmployeeRepository(conn)
        employee = emp_repo.create(
            make_input(department_id=department_id, position="Junior", salary=20000)
        )
        assert employee.id is not None
        emp_repo.update(
            employee.id,
            make_input(
                department_id=department_id,
                position="Junior",
                salary=20000,
                phone="+34 600 999 000",
            ),
        )
        assert len(EmployeeHistoryRepository(conn).list_for_employee(employee.id)) == 1

    def test_update_with_position_change_adds_an_entry(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        emp_repo = EmployeeRepository(conn)
        employee = emp_repo.create(
            make_input(department_id=department_id, position="Junior", salary=20000)
        )
        assert employee.id is not None
        emp_repo.update(
            employee.id,
            make_input(department_id=department_id, position="Senior", salary=20000),
        )
        history = EmployeeHistoryRepository(conn).list_for_employee(employee.id)
        assert [h.position for h in history] == ["Senior", "Junior"]

    def test_update_with_salary_change_adds_an_entry(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        emp_repo = EmployeeRepository(conn)
        employee = emp_repo.create(
            make_input(department_id=department_id, position="Junior", salary=20000)
        )
        assert employee.id is not None
        emp_repo.update(
            employee.id,
            make_input(department_id=department_id, position="Junior", salary=25000),
        )
        history = EmployeeHistoryRepository(conn).list_for_employee(employee.id)
        assert [h.salary for h in history] == [25000, 20000]

    def test_update_with_position_and_salary_change_adds_a_single_entry(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        emp_repo = EmployeeRepository(conn)
        employee = emp_repo.create(
            make_input(department_id=department_id, position="Junior", salary=20000)
        )
        assert employee.id is not None
        emp_repo.update(
            employee.id,
            make_input(department_id=department_id, position="Senior", salary=28000),
        )
        history = EmployeeHistoryRepository(conn).list_for_employee(employee.id)
        assert len(history) == 2
        assert history[0].position == "Senior" and history[0].salary == 28000

    def test_new_entry_uses_todays_date_as_effective_date(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        emp_repo = EmployeeRepository(conn)
        employee = emp_repo.create(
            make_input(
                department_id=department_id,
                position="Junior",
                salary=20000,
                hire_date="2020-01-01",
            )
        )
        assert employee.id is not None
        emp_repo.update(
            employee.id, make_input(department_id=department_id, position="Senior", salary=20000)
        )
        [latest, _initial] = EmployeeHistoryRepository(conn).list_for_employee(employee.id)
        assert latest.effective_date == date.today()

    def test_repeated_updates_accumulate_multiple_entries(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        emp_repo = EmployeeRepository(conn)
        employee = emp_repo.create(
            make_input(department_id=department_id, position="Junior", salary=20000)
        )
        assert employee.id is not None
        emp_repo.update(
            employee.id, make_input(department_id=department_id, position="Semi-senior", salary=24000)
        )
        emp_repo.update(
            employee.id, make_input(department_id=department_id, position="Senior", salary=28000)
        )
        history = EmployeeHistoryRepository(conn).list_for_employee(employee.id)
        assert [h.position for h in history] == ["Senior", "Semi-senior", "Junior"]

    def test_list_for_employee_orders_most_recent_first(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        emp_repo = EmployeeRepository(conn)
        employee = emp_repo.create(
            make_input(department_id=department_id, position="Junior", salary=20000)
        )
        assert employee.id is not None
        emp_repo.update(
            employee.id, make_input(department_id=department_id, position="Senior", salary=28000)
        )
        history = EmployeeHistoryRepository(conn).list_for_employee(employee.id)
        assert [h.note for h in history] == ["", "Alta inicial"]

    def test_deleting_employee_cascades_to_history(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        emp_repo = EmployeeRepository(conn)
        employee = emp_repo.create(make_input(department_id=department_id))
        assert employee.id is not None
        emp_repo.delete(employee.id)
        assert EmployeeHistoryRepository(conn).list_for_employee(employee.id) == []

    def test_list_for_unknown_employee_returns_empty(self, conn: sqlite3.Connection) -> None:
        assert EmployeeHistoryRepository(conn).list_for_employee(999) == []


class TestEmployeeBankAccountAndPhoto:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    def test_defaults_to_no_bank_account_and_no_photo(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(make_input(department_id=department_id))
        assert employee.bank_account == ""
        assert employee.photo is None

    def test_create_stores_normalized_iban(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_input(
                department_id=department_id, bank_account="es9121000418450200051332"
            )
        )
        assert employee.bank_account == "ES91 2100 0418 4502 0005 1332"

    def test_create_with_invalid_iban_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).create(
                make_input(department_id=department_id, bank_account="not-an-iban")
            )

    def test_update_changes_bank_account(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id))
        assert employee.id is not None
        updated = repo.update(
            employee.id,
            make_input(
                department_id=department_id, bank_account="GB29NWBK60161331926819"
            ),
        )
        assert updated.bank_account == "GB29 NWBK 6016 1331 9268 19"

    def test_set_photo_stores_and_clears_bytes(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id))
        assert employee.id is not None

        fake_png_bytes = b"\x89PNG\r\n\x1a\nfake-image-data"
        repo.set_photo(employee.id, fake_png_bytes)
        assert repo.get(employee.id).photo == fake_png_bytes

        repo.set_photo(employee.id, None)
        assert repo.get(employee.id).photo is None

    def test_set_photo_missing_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeRepository(conn).set_photo(999, b"data")

    def test_search_and_list_all_never_return_photo_bytes(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # search()/list_all() back the Treeview and must stay cheap regardless of
        # employee count or photo size — only get(employee_id) loads photo bytes.
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id))
        assert employee.id is not None
        repo.set_photo(employee.id, b"\x89PNG\r\n\x1a\nfake-image-data")

        assert repo.get(employee.id).photo is not None
        assert all(e.photo is None for e in repo.search())
        assert all(e.photo is None for e in repo.list_all())

    def test_defaults_to_zero_dependent_children(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(make_input(department_id=department_id))
        assert employee.dependent_children == 0

    def test_create_and_update_dependent_children(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id, dependent_children=2))
        assert employee.dependent_children == 2
        assert employee.id is not None
        updated = repo.update(
            employee.id, make_input(department_id=department_id, dependent_children=3)
        )
        assert updated.dependent_children == 3

    def test_negative_dependent_children_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).create(
                make_input(department_id=department_id, dependent_children=-1)
            )

    def test_dependent_children_returned_by_search_too(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # Unlike photo, this is a small int -- fine to include in the cheap
        # list/search query, and payroll browsing needs it without a get() per row.
        EmployeeRepository(conn).create(make_input(department_id=department_id, dependent_children=4))
        results = EmployeeRepository(conn).search()
        assert results[0].dependent_children == 4


class TestEmployeeDniNieAndSsNumber:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    def test_defaults_to_no_dni_nie_and_no_ss_number(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(make_input(department_id=department_id))
        assert employee.dni_nie is None
        assert employee.ss_number is None

    def test_create_stores_normalized_dni_nie(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_input(department_id=department_id, dni_nie="12345678z")
        )
        assert employee.dni_nie == "12345678Z"

    def test_create_stores_normalized_ss_number(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_input(department_id=department_id, ss_number="28/12345678/90")
        )
        assert employee.ss_number == "281234567890"

    def test_create_with_invalid_dni_nie_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).create(
                make_input(department_id=department_id, dni_nie="12345678A")
            )

    def test_create_with_invalid_ss_number_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).create(
                make_input(department_id=department_id, ss_number="not-a-number")
            )

    def test_update_changes_dni_nie(self, conn: sqlite3.Connection, department_id: int) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id, dni_nie="00000000T"))
        assert employee.id is not None
        updated = repo.update(
            employee.id, make_input(department_id=department_id, dni_nie="12345678Z")
        )
        assert updated.dni_nie == "12345678Z"

    def test_duplicate_dni_nie_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.create(make_input(department_id=department_id, dni_nie="12345678Z"))
        with pytest.raises(DuplicateError):
            repo.create(
                make_input(
                    department_id=department_id,
                    email="otro@example.com",
                    dni_nie="12345678Z",
                )
            )

    def test_duplicate_dni_nie_case_insensitive(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.create(make_input(department_id=department_id, dni_nie="12345678Z"))
        with pytest.raises(DuplicateError):
            repo.create(
                make_input(
                    department_id=department_id,
                    email="otro@example.com",
                    dni_nie="12345678z",
                )
            )

    def test_multiple_employees_without_dni_nie_do_not_conflict(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # Both leave dni_nie blank -> stored as NULL, and NULL never
        # collides with NULL under a UNIQUE index (unlike empty strings).
        repo = EmployeeRepository(conn)
        repo.create(make_input(department_id=department_id, email="uno@example.com"))
        second = repo.create(make_input(department_id=department_id, email="dos@example.com"))
        assert second.dni_nie is None

    def test_duplicate_ss_number_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # Igual de identificativo que el DNI/NIE, pero antes no tenía
        # ninguna restricción de unicidad -- dos empleados distintos podían
        # compartir el mismo número sin ningún aviso.
        repo = EmployeeRepository(conn)
        repo.create(make_input(department_id=department_id, ss_number="281234567890"))
        with pytest.raises(DuplicateError):
            repo.create(
                make_input(
                    department_id=department_id,
                    email="otro@example.com",
                    ss_number="281234567890",
                )
            )

    def test_multiple_employees_without_ss_number_do_not_conflict(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.create(make_input(department_id=department_id, email="uno@example.com"))
        second = repo.create(make_input(department_id=department_id, email="dos@example.com"))
        assert second.ss_number is None

    def test_search_and_list_all_include_dni_nie_and_ss_number(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        EmployeeRepository(conn).create(
            make_input(department_id=department_id, dni_nie="12345678Z", ss_number="281234567890")
        )
        results = EmployeeRepository(conn).search()
        assert results[0].dni_nie == "12345678Z"
        assert results[0].ss_number == "281234567890"


class TestEmployeeContractInfo:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    def test_defaults_to_indefinido_with_no_end_date(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(make_input(department_id=department_id))
        assert employee.contract_type == "Indefinido"
        assert employee.contract_end_date is None

    def test_create_temporal_with_end_date(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_input(
                department_id=department_id,
                hire_date="2024-01-01",
                contract_type="Temporal",
                contract_end_date="2026-12-31",
            )
        )
        assert employee.contract_type == "Temporal"
        assert employee.contract_end_date == date(2026, 12, 31)

    def test_indefinido_with_end_date_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).create(
                make_input(
                    department_id=department_id,
                    contract_type="Indefinido",
                    contract_end_date="2026-12-31",
                )
            )

    def test_end_date_before_hire_date_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).create(
                make_input(
                    department_id=department_id,
                    hire_date="2024-06-01",
                    contract_type="Temporal",
                    contract_end_date="2024-01-01",
                )
            )

    def test_invalid_contract_type_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).create(
                make_input(department_id=department_id, contract_type="Becario")
            )

    def test_update_changes_contract_type_and_end_date(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(
            make_input(department_id=department_id, hire_date="2024-01-01")
        )
        assert employee.id is not None
        updated = repo.update(
            employee.id,
            make_input(
                department_id=department_id,
                hire_date="2024-01-01",
                contract_type="Fijo-discontinuo",
                contract_end_date="2026-06-30",
            ),
        )
        assert updated.contract_type == "Fijo-discontinuo"
        assert updated.contract_end_date == date(2026, 6, 30)

    def test_update_back_to_indefinido_clears_end_date(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(
            make_input(
                department_id=department_id,
                hire_date="2024-01-01",
                contract_type="Temporal",
                contract_end_date="2026-12-31",
            )
        )
        assert employee.id is not None
        updated = repo.update(
            employee.id,
            make_input(department_id=department_id, hire_date="2024-01-01"),
        )
        assert updated.contract_type == "Indefinido"
        assert updated.contract_end_date is None

    def test_search_and_list_all_include_contract_info(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        EmployeeRepository(conn).create(
            make_input(
                department_id=department_id,
                hire_date="2024-01-01",
                contract_type="Prácticas",
                contract_end_date="2026-09-30",
            )
        )
        results = EmployeeRepository(conn).search()
        assert results[0].contract_type == "Prácticas"
        assert results[0].contract_end_date == date(2026, 9, 30)


class TestEmployeeAlertsFields:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    def test_defaults_to_no_birth_date_and_no_checkup_date(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(make_input(department_id=department_id))
        assert employee.birth_date is None
        assert employee.next_medical_checkup_date is None

    def test_create_stores_birth_date_and_checkup_date(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_input(
                department_id=department_id,
                birth_date="1990-05-20",
                next_medical_checkup_date="2027-01-15",
            )
        )
        assert employee.birth_date == date(1990, 5, 20)
        assert employee.next_medical_checkup_date == date(2027, 1, 15)

    def test_create_with_invalid_birth_date_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).create(
                make_input(department_id=department_id, birth_date="not-a-date")
            )

    def test_create_with_birth_date_after_hire_date_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).create(
                make_input(
                    department_id=department_id,
                    hire_date="2020-01-01",
                    birth_date="2021-01-01",
                )
            )

    def test_update_changes_birth_date_and_checkup_date(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(
            make_input(department_id=department_id, birth_date="1990-05-20")
        )
        assert employee.id is not None
        updated = repo.update(
            employee.id,
            make_input(
                department_id=department_id,
                birth_date="1985-03-10",
                next_medical_checkup_date="2026-11-01",
            ),
        )
        assert updated.birth_date == date(1985, 3, 10)
        assert updated.next_medical_checkup_date == date(2026, 11, 1)

    def test_update_can_clear_the_checkup_date(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(
            make_input(department_id=department_id, next_medical_checkup_date="2026-11-01")
        )
        assert employee.id is not None
        updated = repo.update(employee.id, make_input(department_id=department_id))
        assert updated.next_medical_checkup_date is None

    def test_search_and_list_all_include_alerts_fields(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        EmployeeRepository(conn).create(
            make_input(
                department_id=department_id,
                birth_date="1990-05-20",
                next_medical_checkup_date="2027-01-15",
            )
        )
        results = EmployeeRepository(conn).search()
        assert results[0].birth_date == date(1990, 5, 20)
        assert results[0].next_medical_checkup_date == date(2027, 1, 15)


class TestEmployeeTermination:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_input(department_id=department_id, hire_date="2020-01-01")
        )
        assert employee.id is not None
        return employee.id

    def test_terminate_deactivates_and_sets_termination_fields(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        updated = EmployeeRepository(conn).terminate(
            employee_id, "2026-06-30", "Baja voluntaria"
        )
        assert updated.active is False
        assert updated.termination_date == date(2026, 6, 30)
        assert updated.termination_reason == "Baja voluntaria"

    def test_terminate_already_inactive_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.terminate(employee_id, "2026-06-30", "Baja voluntaria")
        with pytest.raises(RepositoryError):
            repo.terminate(employee_id, "2026-07-01", "Otro")

    def test_terminate_invalid_reason_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).terminate(employee_id, "2026-06-30", "motivo inventado")

    def test_terminate_date_before_hire_date_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).terminate(employee_id, "2019-12-31", "Baja voluntaria")

    def test_terminate_future_date_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        future = (date.today() + timedelta(days=30)).isoformat()
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).terminate(employee_id, future, "Baja voluntaria")

    def test_terminate_unknown_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeRepository(conn).terminate(999, "2026-06-30", "Baja voluntaria")

    def test_reactivate_restores_active_and_clears_termination_fields(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.terminate(employee_id, "2026-06-30", "Baja voluntaria")
        reactivated = repo.reactivate(employee_id)
        assert reactivated.active is True
        assert reactivated.termination_date is None
        assert reactivated.termination_reason is None

    def test_reactivate_already_active_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(RepositoryError):
            EmployeeRepository(conn).reactivate(employee_id)

    def test_reactivate_unknown_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeRepository(conn).reactivate(999)

    def test_search_reflects_termination_fields(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.terminate(employee_id, "2026-06-30", "Fin de contrato temporal")
        results = repo.search(active_only=False)
        assert results[0].termination_date == date(2026, 6, 30)
        assert results[0].termination_reason == "Fin de contrato temporal"


class TestEmployeeAnonymization:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_input(
                department_id=department_id,
                hire_date="2020-01-01",
                dni_nie="12345678Z",
                ss_number="281234567890",
                bank_account="ES9121000418450200051332",
                phone="+34 600 111 222",
            )
        )
        assert employee.id is not None
        return employee.id

    def test_anonymize_requires_the_employee_to_be_inactive(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(RepositoryError):
            EmployeeRepository(conn).anonymize(employee_id)

    def test_anonymize_scrubs_identifying_fields(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.terminate(employee_id, "2026-06-30", "Baja voluntaria")
        anonymized = repo.anonymize(employee_id)
        assert anonymized.first_name == "Anonimizado"
        assert anonymized.email != "ana.lopez@example.com"
        assert anonymized.phone == ""
        assert anonymized.bank_account == ""
        assert anonymized.photo is None
        assert anonymized.dni_nie is None
        assert anonymized.ss_number is None
        assert anonymized.anonymized is True

    def test_anonymize_preserves_structural_fields(
        self, conn: sqlite3.Connection, employee_id: int, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.terminate(employee_id, "2026-06-30", "Baja voluntaria")
        anonymized = repo.anonymize(employee_id)
        assert anonymized.department_id == department_id
        assert anonymized.salary == 35000.0
        assert anonymized.position == "Ingeniera"
        assert anonymized.hire_date == date(2020, 1, 1)
        assert anonymized.termination_date == date(2026, 6, 30)
        assert anonymized.termination_reason == "Baja voluntaria"

    def test_anonymize_deletes_attached_documents(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        doc_repo = EmployeeDocumentRepository(conn)
        doc_repo.upload(employee_id, "contrato.pdf", "Contrato", b"contenido")
        repo.terminate(employee_id, "2026-06-30", "Baja voluntaria")
        repo.anonymize(employee_id)
        assert doc_repo.list_for_employee(employee_id) == []

    def test_anonymize_twice_raises(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = EmployeeRepository(conn)
        repo.terminate(employee_id, "2026-06-30", "Baja voluntaria")
        repo.anonymize(employee_id)
        with pytest.raises(RepositoryError):
            repo.anonymize(employee_id)

    def test_anonymize_unknown_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeRepository(conn).anonymize(999)

    def test_anonymized_email_placeholders_do_not_collide(
        self, conn: sqlite3.Connection, employee_id: int, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.terminate(employee_id, "2026-06-30", "Baja voluntaria")
        repo.anonymize(employee_id)

        other = repo.create(make_input(department_id=department_id, email="otro@example.com"))
        assert other.id is not None
        repo.terminate(other.id, "2026-06-30", "Baja voluntaria")
        # No debe chocar con el email placeholder del primero (UNIQUE en la BD).
        repo.anonymize(other.id)

    def test_anonymize_scrubs_birth_date_and_medical_checkup(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # birth_date/next_medical_checkup_date no tienen la misma obligación
        # legal de conservación que hire_date/salary: a diferencia de esos
        # campos "estructurales", se borran igual que el resto de datos
        # identificativos.
        repo = EmployeeRepository(conn)
        employee = repo.create(
            make_input(
                department_id=department_id,
                hire_date="2020-01-01",
                birth_date="1985-06-15",
                next_medical_checkup_date="2026-12-01",
            )
        )
        assert employee.id is not None
        repo.terminate(employee.id, "2026-06-30", "Baja voluntaria")
        anonymized = repo.anonymize(employee.id)
        assert anonymized.birth_date is None
        assert anonymized.next_medical_checkup_date is None

    def test_update_rejected_after_anonymize(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        # Regresión: "Guardar cambios" podía restaurar todos los datos que
        # anonymize() acababa de borrar, mientras el campo `anonymized`
        # seguía en True -- dando una falsa sensación de cumplimiento.
        repo = EmployeeRepository(conn)
        repo.terminate(employee_id, "2026-06-30", "Baja voluntaria")
        repo.anonymize(employee_id)
        with pytest.raises(RepositoryError):
            repo.update(employee_id, make_input(email="restaurado@example.com"))
        # Y el intento no debe haber colado ningún dato de vuelta.
        still_anonymized = repo.get(employee_id)
        assert still_anonymized.first_name == "Anonimizado"
        assert still_anonymized.anonymized is True

    def test_set_photo_rejected_after_anonymize(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.terminate(employee_id, "2026-06-30", "Baja voluntaria")
        repo.anonymize(employee_id)
        with pytest.raises(RepositoryError):
            repo.set_photo(employee_id, b"contenido-de-foto")
        assert repo.get(employee_id).photo is None

    def test_upload_document_rejected_after_anonymize(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        doc_repo = EmployeeDocumentRepository(conn)
        repo.terminate(employee_id, "2026-06-30", "Baja voluntaria")
        repo.anonymize(employee_id)
        with pytest.raises(RepositoryError):
            doc_repo.upload(employee_id, "nuevo.pdf", "Otro", b"contenido")
        assert doc_repo.list_for_employee(employee_id) == []


class TestSeveranceSettlementRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_input(department_id=department_id, hire_date="2020-01-01", salary=14000.0)
        )
        assert employee.id is not None
        return employee.id

    def _calculation(self) -> SeveranceCalculation:
        return calculate_severance(
            hire_date=date(2020, 1, 1),
            termination_date=date(2026, 6, 30),
            annual_gross_salary=14000.0,
            annual_vacation_days=24.0,
            vacation_days_used_this_year=3,
        )

    def test_create_and_get(self, conn: sqlite3.Connection, employee_id: int) -> None:
        calculation = self._calculation()
        settlement = SeveranceSettlementRepository(conn).create(
            employee_id=employee_id,
            termination_date=date(2026, 6, 30),
            termination_reason="Baja voluntaria",
            hire_date=date(2020, 1, 1),
            annual_gross_salary=14000.0,
            annual_vacation_days=24.0,
            vacation_days_used_this_year=3,
            calculation=calculation,
        )
        assert settlement.id is not None
        fetched = SeveranceSettlementRepository(conn).get(settlement.id)
        assert fetched.employee_id == employee_id
        assert fetched.termination_reason == "Baja voluntaria"
        assert fetched.hire_date == date(2020, 1, 1)
        assert fetched.annual_gross_salary == 14000.0
        assert fetched.vacation_days_used_this_year == 3
        assert fetched.total_amount == calculation.total_amount

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            SeveranceSettlementRepository(conn).get(999)

    def test_list_for_unknown_employee_returns_empty(self, conn: sqlite3.Connection) -> None:
        assert SeveranceSettlementRepository(conn).list_for_employee(999) == []

    def test_list_for_employee_orders_most_recent_first(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = SeveranceSettlementRepository(conn)
        calculation = self._calculation()
        first = repo.create(
            employee_id=employee_id,
            termination_date=date(2026, 6, 30),
            termination_reason="Baja voluntaria",
            hire_date=date(2020, 1, 1),
            annual_gross_salary=14000.0,
            annual_vacation_days=24.0,
            vacation_days_used_this_year=3,
            calculation=calculation,
        )
        second = repo.create(
            employee_id=employee_id,
            termination_date=date(2026, 6, 30),
            termination_reason="Otro",
            hire_date=date(2020, 1, 1),
            annual_gross_salary=14000.0,
            annual_vacation_days=24.0,
            vacation_days_used_this_year=3,
            calculation=calculation,
        )
        results = repo.list_for_employee(employee_id)
        assert [r.id for r in results] == [second.id, first.id]

    def test_deleting_employee_cascades_settlements(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        calculation = self._calculation()
        SeveranceSettlementRepository(conn).create(
            employee_id=employee_id,
            termination_date=date(2026, 6, 30),
            termination_reason="Baja voluntaria",
            hire_date=date(2020, 1, 1),
            annual_gross_salary=14000.0,
            annual_vacation_days=24.0,
            vacation_days_used_this_year=3,
            calculation=calculation,
        )
        EmployeeRepository(conn).delete(employee_id)
        assert SeveranceSettlementRepository(conn).list_for_employee(employee_id) == []


class TestAuditLogRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def user(self, conn: sqlite3.Connection, department_id: int) -> User:
        # role="encargado" (no "admin", el valor por defecto de create()) a
        # propósito: test_deleting_the_user_keeps_the_readable_username
        # necesita poder borrar de verdad a este usuario, y borrar el único
        # admin de la base de datos está bloqueado por UserRepository.delete().
        # UserRepository no tiene get(): se guarda el propio User devuelto
        # por create() en vez de tener que releerlo por id después.
        user = UserRepository(conn).create(
            "encargado1", "pass1234", role="encargado", department_id=department_id
        )
        assert user.id is not None
        return user

    def test_record_uses_the_current_user(self, conn: sqlite3.Connection, user: User) -> None:
        repo = AuditLogRepository(conn)
        repo.set_current_user(user)
        entry = repo.record("employee_created", "Empleado: Ana García")
        assert entry.user_id == user.id
        assert entry.username == "encargado1"
        assert entry.action == "employee_created"
        assert entry.details == "Empleado: Ana García"

    def test_record_without_a_current_user_still_records(
        self, conn: sqlite3.Connection
    ) -> None:
        # No debe fallar ni bloquear la acción real que se está auditando
        # solo porque nadie llamó a set_current_user() todavía -- se
        # registra igual, con un usuario "desconocido" en vez de reventar.
        repo = AuditLogRepository(conn)
        entry = repo.record("employee_deleted", "Empleado: Ana García")
        assert entry.user_id is None
        assert entry.username == "?"

    def test_record_login_attempt_success(self, conn: sqlite3.Connection, user: User) -> None:
        repo = AuditLogRepository(conn)
        entry = repo.record_login_attempt("encargado1", success=True, user_id=user.id)
        assert entry.action == AUDIT_LOGIN_SUCCESS
        assert entry.user_id == user.id
        assert entry.username == "encargado1"

    def test_record_login_attempt_failure_has_no_user_id(
        self, conn: sqlite3.Connection
    ) -> None:
        # Usuario que no existe (o contraseña incorrecta): no hay user_id
        # real, pero el nombre tecleado sí queda registrado tal cual, útil
        # para detectar intentos repetidos contra un usuario inventado.
        repo = AuditLogRepository(conn)
        entry = repo.record_login_attempt("noexiste", success=False, user_id=None)
        assert entry.action == AUDIT_LOGIN_FAILURE
        assert entry.user_id is None
        assert entry.username == "noexiste"

    def test_list_all_orders_most_recent_first(self, conn: sqlite3.Connection) -> None:
        repo = AuditLogRepository(conn)
        first = repo.record("employee_created", "primero")
        second = repo.record("employee_created", "segundo")
        results = repo.list_all()
        assert [r.id for r in results] == [second.id, first.id]

    def test_list_all_respects_limit(self, conn: sqlite3.Connection) -> None:
        repo = AuditLogRepository(conn)
        for i in range(5):
            repo.record("employee_created", f"entrada {i}")
        assert len(repo.list_all(limit=3)) == 3

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            AuditLogRepository(conn).get(999)

    def test_empty_action_rejected_by_the_database(self, conn: sqlite3.Connection) -> None:
        # El CHECK de la tabla ya no valida contra una lista cerrada de
        # códigos (ver _migrate_audit_log_action_check en database.py: un
        # CHECK así no se puede ampliar con ALTER TABLE, así que cada
        # AUDIT_* nuevo habría exigido recrear la tabla) -- la lista real
        # de códigos válidos vive solo en las constantes AUDIT_* de
        # app/repository.py. Lo único que el CHECK sigue rechazando es una
        # acción vacía.
        with pytest.raises(sqlite3.IntegrityError):
            AuditLogRepository(conn).record("")

    def test_deleting_the_user_keeps_the_readable_username(
        self, conn: sqlite3.Connection, user: User
    ) -> None:
        repo = AuditLogRepository(conn)
        repo.set_current_user(user)
        entry = repo.record("employee_created", "Empleado: Ana García")
        assert entry.id is not None
        assert user.id is not None
        UserRepository(conn).delete(user.id)
        reloaded = repo.get(entry.id)
        assert reloaded.user_id is None  # ON DELETE SET NULL
        assert reloaded.username == "encargado1"  # pero el nombre sigue legible


class TestEmployeeDocumentRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(make_input(department_id=department_id))
        assert employee.id is not None
        return employee.id

    def test_upload_and_get(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = EmployeeDocumentRepository(conn)
        doc = repo.upload(employee_id, "contrato.pdf", "Contrato", b"%PDF-1.4 fake")
        assert doc.id is not None
        assert doc.filename == "contrato.pdf"
        assert doc.category == "Contrato"
        assert doc.content == b"%PDF-1.4 fake"
        assert doc.size_bytes == len(b"%PDF-1.4 fake")

        fetched = repo.get(doc.id)
        assert fetched.content == b"%PDF-1.4 fake"

    def test_upload_unknown_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeDocumentRepository(conn).upload(999, "a.pdf", "Contrato", b"data")

    def test_upload_invalid_category_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeDocumentRepository(conn).upload(employee_id, "a.pdf", "Factura", b"data")

    def test_upload_empty_content_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeDocumentRepository(conn).upload(employee_id, "a.pdf", "Otro", b"")

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeDocumentRepository(conn).get(999)

    def test_list_for_employee_excludes_content(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeDocumentRepository(conn)
        repo.upload(employee_id, "contrato.pdf", "Contrato", b"a" * 5000)
        summaries = repo.list_for_employee(employee_id)
        assert len(summaries) == 1
        assert summaries[0].size_bytes == 5000
        assert not hasattr(summaries[0], "content")

    def test_list_for_employee_excludes_other_employees(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other = EmployeeRepository(conn).create(
            make_input(department_id=department_id, email="otro@example.com")
        )
        assert other.id is not None
        repo = EmployeeDocumentRepository(conn)
        repo.upload(employee_id, "a.pdf", "Contrato", b"data")
        repo.upload(other.id, "b.pdf", "Contrato", b"data")
        assert len(repo.list_for_employee(employee_id)) == 1

    def test_list_for_employee_orders_most_recent_first(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        # Inserted directly via SQL with distinct timestamps, out of order,
        # to isolate the ORDER BY from upload()'s own (identical, "now")
        # timestamp across near-instant calls in a fast test.
        conn.execute(
            "INSERT INTO employee_documents (employee_id, filename, category, content, "
            "size_bytes, uploaded_at) VALUES (?, 'old.pdf', 'Contrato', ?, 4, ?)",
            (employee_id, b"data", "2026-01-01T09:00:00"),
        )
        conn.execute(
            "INSERT INTO employee_documents (employee_id, filename, category, content, "
            "size_bytes, uploaded_at) VALUES (?, 'new.pdf', 'Contrato', ?, 4, ?)",
            (employee_id, b"data", "2026-06-01T09:00:00"),
        )
        conn.commit()
        summaries = EmployeeDocumentRepository(conn).list_for_employee(employee_id)
        assert [s.filename for s in summaries] == ["new.pdf", "old.pdf"]

    def test_delete_removes_the_document(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeDocumentRepository(conn)
        doc = repo.upload(employee_id, "a.pdf", "Contrato", b"data")
        assert doc.id is not None
        repo.delete(doc.id)
        with pytest.raises(NotFoundError):
            repo.get(doc.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeDocumentRepository(conn).delete(999)

    def test_deleting_employee_cascades_documents(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        EmployeeDocumentRepository(conn).upload(employee_id, "a.pdf", "Contrato", b"data")
        EmployeeRepository(conn).delete(employee_id)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM employee_documents WHERE employee_id = ?", (employee_id,)
        ).fetchone()[0]
        assert remaining == 0


class TestDocumentTemplateRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_input(department_id=department_id, first_name="Ana", salary=24000.0)
        )
        assert employee.id is not None
        return employee.id

    def test_create_and_get(self, conn: sqlite3.Connection) -> None:
        repo = DocumentTemplateRepository(conn)
        template = repo.create("Oferta estándar", "Hola {nombre}.")
        assert template.id is not None
        assert template.name == "Oferta estándar"
        assert template.body == "Hola {nombre}."
        assert template.created_at == date.today()
        assert repo.get(template.id) == template

    def test_create_rejects_duplicate_name_case_insensitive(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = DocumentTemplateRepository(conn)
        repo.create("Oferta estándar", "Hola {nombre}.")
        with pytest.raises(DuplicateError):
            repo.create("oferta estándar", "Otro texto.")

    def test_create_rejects_blank_name(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            DocumentTemplateRepository(conn).create("   ", "Hola {nombre}.")

    def test_create_rejects_blank_body(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            DocumentTemplateRepository(conn).create("Oferta", "   ")

    def test_get_unknown_template_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            DocumentTemplateRepository(conn).get(999)

    def test_list_all_orders_by_name(self, conn: sqlite3.Connection) -> None:
        repo = DocumentTemplateRepository(conn)
        repo.create("Oferta", "texto")
        repo.create("Carta de baja", "texto")
        names = [t.name for t in repo.list_all()]
        assert names == ["Carta de baja", "Oferta"]

    def test_update_changes_name_and_body(self, conn: sqlite3.Connection) -> None:
        repo = DocumentTemplateRepository(conn)
        template = repo.create("Oferta", "Hola {nombre}.")
        assert template.id is not None
        updated = repo.update(template.id, "Oferta v2", "Estimado/a {nombre_completo}.")
        assert updated.name == "Oferta v2"
        assert updated.body == "Estimado/a {nombre_completo}."
        assert updated.id == template.id
        assert updated.created_at == template.created_at

    def test_update_unknown_template_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            DocumentTemplateRepository(conn).update(999, "Oferta", "texto")

    def test_update_rejects_duplicate_name(self, conn: sqlite3.Connection) -> None:
        repo = DocumentTemplateRepository(conn)
        repo.create("Oferta", "texto")
        other = repo.create("Carta de baja", "texto")
        assert other.id is not None
        with pytest.raises(DuplicateError):
            repo.update(other.id, "Oferta", "texto")

    def test_delete_removes_template(self, conn: sqlite3.Connection) -> None:
        repo = DocumentTemplateRepository(conn)
        template = repo.create("Oferta", "texto")
        assert template.id is not None
        repo.delete(template.id)
        with pytest.raises(NotFoundError):
            repo.get(template.id)

    def test_delete_unknown_template_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            DocumentTemplateRepository(conn).delete(999)

    def test_render_for_employee_substitutes_real_data(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = DocumentTemplateRepository(conn)
        template = repo.create(
            "Oferta", "Hola {nombre}, el puesto es {puesto} en {departamento}."
        )
        assert template.id is not None
        rendered = repo.render_for_employee(template.id, employee_id)
        assert rendered == "Hola Ana, el puesto es Ingeniera en Ventas."

    def test_render_for_employee_unknown_template_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(NotFoundError):
            DocumentTemplateRepository(conn).render_for_employee(999, employee_id)

    def test_render_for_employee_unknown_employee_raises(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = DocumentTemplateRepository(conn)
        template = repo.create("Oferta", "Hola {nombre}.")
        assert template.id is not None
        with pytest.raises(NotFoundError):
            repo.render_for_employee(template.id, 999)

    def test_render_for_employee_leaves_unknown_placeholder_untouched(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = DocumentTemplateRepository(conn)
        template = repo.create("Oferta", "Campo desconocido: {no_existe}.")
        assert template.id is not None
        rendered = repo.render_for_employee(template.id, employee_id)
        assert rendered == "Campo desconocido: {no_existe}."


class TestOnboardingTaskRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(make_input(department_id=department_id))
        assert employee.id is not None
        return employee.id

    def test_create_and_get(self, conn: sqlite3.Connection) -> None:
        repo = OnboardingTaskRepository(conn)
        task = repo.create("Contrato firmado")
        assert task.id is not None
        assert task.name == "Contrato firmado"
        assert repo.get(task.id) == task

    def test_create_rejects_duplicate_name_case_insensitive(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = OnboardingTaskRepository(conn)
        repo.create("Contrato firmado")
        with pytest.raises(DuplicateError):
            repo.create("contrato firmado")

    def test_create_rejects_blank_name(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            OnboardingTaskRepository(conn).create("   ")

    def test_get_unknown_task_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            OnboardingTaskRepository(conn).get(999)

    def test_list_all_orders_by_name(self, conn: sqlite3.Connection) -> None:
        repo = OnboardingTaskRepository(conn)
        repo.create("Equipo entregado")
        repo.create("Accesos creados")
        names = [t.name for t in repo.list_all()]
        assert names == ["Accesos creados", "Equipo entregado"]

    def test_update_renames_a_task(self, conn: sqlite3.Connection) -> None:
        repo = OnboardingTaskRepository(conn)
        task = repo.create("Contrato firmado")
        assert task.id is not None
        renamed = repo.update(task.id, "Contrato firmado y entregado")
        assert renamed.name == "Contrato firmado y entregado"
        assert renamed.id == task.id

    def test_update_unknown_task_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            OnboardingTaskRepository(conn).update(999, "Otro nombre")

    def test_update_rejects_duplicate_name(self, conn: sqlite3.Connection) -> None:
        repo = OnboardingTaskRepository(conn)
        repo.create("Contrato firmado")
        other = repo.create("Accesos creados")
        assert other.id is not None
        with pytest.raises(DuplicateError):
            repo.update(other.id, "Contrato firmado")

    def test_delete_removes_task(self, conn: sqlite3.Connection) -> None:
        repo = OnboardingTaskRepository(conn)
        task = repo.create("Contrato firmado")
        assert task.id is not None
        repo.delete(task.id)
        with pytest.raises(NotFoundError):
            repo.get(task.id)

    def test_delete_unknown_task_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            OnboardingTaskRepository(conn).delete(999)

    def test_delete_rejects_a_task_already_marked_complete_for_someone(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = OnboardingTaskRepository(conn)
        task = repo.create("Contrato firmado")
        assert task.id is not None
        repo.mark_complete(employee_id, task.id, date(2026, 1, 5))
        with pytest.raises(ReferenceInUseError):
            repo.delete(task.id)

    def test_checklist_for_employee_starts_all_pending(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = OnboardingTaskRepository(conn)
        repo.create("Contrato firmado")
        repo.create("Accesos creados")
        checklist = repo.checklist_for_employee(employee_id)
        assert len(checklist) == 2
        assert all(not status.is_complete for status in checklist)
        assert all(status.completed_at is None for status in checklist)

    def test_checklist_for_employee_unknown_employee_raises(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(NotFoundError):
            OnboardingTaskRepository(conn).checklist_for_employee(999)

    def test_mark_complete_reflects_in_the_checklist(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = OnboardingTaskRepository(conn)
        task = repo.create("Contrato firmado")
        assert task.id is not None
        repo.mark_complete(employee_id, task.id, date(2026, 1, 5))
        [status] = repo.checklist_for_employee(employee_id)
        assert status.is_complete
        assert status.completed_at == date(2026, 1, 5)

    def test_mark_complete_unknown_employee_raises(self, conn: sqlite3.Connection) -> None:
        repo = OnboardingTaskRepository(conn)
        task = repo.create("Contrato firmado")
        assert task.id is not None
        with pytest.raises(NotFoundError):
            repo.mark_complete(999, task.id, date.today())

    def test_mark_complete_unknown_task_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(NotFoundError):
            OnboardingTaskRepository(conn).mark_complete(employee_id, 999, date.today())

    def test_mark_complete_twice_updates_the_date_without_duplicating(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = OnboardingTaskRepository(conn)
        task = repo.create("Contrato firmado")
        assert task.id is not None
        repo.mark_complete(employee_id, task.id, date(2026, 1, 5))
        repo.mark_complete(employee_id, task.id, date(2026, 1, 6))
        checklist = repo.checklist_for_employee(employee_id)
        assert len(checklist) == 1
        assert checklist[0].completed_at == date(2026, 1, 6)

    def test_mark_incomplete_clears_the_completion(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = OnboardingTaskRepository(conn)
        task = repo.create("Contrato firmado")
        assert task.id is not None
        repo.mark_complete(employee_id, task.id, date(2026, 1, 5))
        repo.mark_incomplete(employee_id, task.id)
        [status] = repo.checklist_for_employee(employee_id)
        assert not status.is_complete
        assert status.completed_at is None

    def test_mark_incomplete_on_an_already_pending_task_is_a_no_op(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = OnboardingTaskRepository(conn)
        task = repo.create("Contrato firmado")
        assert task.id is not None
        repo.mark_incomplete(employee_id, task.id)  # never marked complete -- should not raise

    def test_a_task_added_later_appears_immediately_for_existing_employees(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = OnboardingTaskRepository(conn)
        first = repo.create("Contrato firmado")
        assert first.id is not None
        repo.mark_complete(employee_id, first.id, date(2026, 1, 5))

        repo.create("Equipo entregado")
        checklist = {s.task.name: s for s in repo.checklist_for_employee(employee_id)}
        assert "Equipo entregado" in checklist
        assert not checklist["Equipo entregado"].is_complete
        assert checklist["Contrato firmado"].is_complete

    def test_deleting_employee_cascades_checklist_items(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = OnboardingTaskRepository(conn)
        task = repo.create("Contrato firmado")
        assert task.id is not None
        repo.mark_complete(employee_id, task.id, date(2026, 1, 5))
        EmployeeRepository(conn).delete(employee_id)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM onboarding_checklist_items"
        ).fetchone()[0]
        assert remaining == 0


class TestCandidateRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def other_department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Producción")
        assert dept.id is not None
        return dept.id

    @staticmethod
    def make_candidate_input(**overrides: object) -> CandidateInput:
        defaults: dict[str, object] = dict(
            first_name="Luis",
            last_name="Perez",
            email="luis.perez@example.com",
            phone="600111222",
            position="Comercial",
            department_id=1,
            phase="Recibido",
        )
        defaults.update(overrides)
        return CandidateInput(**defaults)  # type: ignore[arg-type]

    def test_create_and_get(self, conn: sqlite3.Connection, department_id: int) -> None:
        repo = CandidateRepository(conn)
        candidate = repo.create(self.make_candidate_input(department_id=department_id))
        assert candidate.id is not None
        assert candidate.full_name == "Luis Perez"
        assert candidate.phase == "Recibido"
        assert candidate.department_id == department_id
        assert candidate.created_at == date.today()
        assert repo.get(candidate.id) == candidate

    def test_create_rejects_invalid_email(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            CandidateRepository(conn).create(
                self.make_candidate_input(department_id=department_id, email="not-an-email")
            )

    def test_create_rejects_invalid_phase(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            CandidateRepository(conn).create(
                self.make_candidate_input(department_id=department_id, phase="Fase inventada")
            )

    def test_create_rejects_blank_position(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            CandidateRepository(conn).create(
                self.make_candidate_input(department_id=department_id, position="   ")
            )

    def test_create_unknown_department_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            CandidateRepository(conn).create(self.make_candidate_input(department_id=999))

    def test_create_allows_duplicate_email(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # A diferencia de Employee.email, el email de un candidato no es
        # único: puede volver a presentarse a otra vacante, o a la misma
        # más adelante.
        repo = CandidateRepository(conn)
        first = repo.create(self.make_candidate_input(department_id=department_id))
        second = repo.create(self.make_candidate_input(department_id=department_id))
        assert first.id != second.id
        assert first.email == second.email

    def test_get_unknown_candidate_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            CandidateRepository(conn).get(999)

    def test_update_changes_phase_and_position(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = CandidateRepository(conn)
        candidate = repo.create(self.make_candidate_input(department_id=department_id))
        assert candidate.id is not None
        updated = repo.update(
            candidate.id,
            self.make_candidate_input(
                department_id=department_id, phase="Entrevista", position="Comercial Senior"
            ),
        )
        assert updated.phase == "Entrevista"
        assert updated.position == "Comercial Senior"
        assert updated.id == candidate.id
        assert updated.created_at == candidate.created_at

    def test_update_unknown_candidate_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(NotFoundError):
            CandidateRepository(conn).update(
                999, self.make_candidate_input(department_id=department_id)
            )

    def test_update_can_move_a_candidate_to_another_department(
        self, conn: sqlite3.Connection, department_id: int, other_department_id: int
    ) -> None:
        repo = CandidateRepository(conn)
        candidate = repo.create(self.make_candidate_input(department_id=department_id))
        assert candidate.id is not None
        updated = repo.update(
            candidate.id, self.make_candidate_input(department_id=other_department_id)
        )
        assert updated.department_id == other_department_id

    def test_delete_removes_candidate(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = CandidateRepository(conn)
        candidate = repo.create(self.make_candidate_input(department_id=department_id))
        assert candidate.id is not None
        repo.delete(candidate.id)
        with pytest.raises(NotFoundError):
            repo.get(candidate.id)

    def test_delete_unknown_candidate_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            CandidateRepository(conn).delete(999)

    def test_list_all_orders_most_recent_first(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = CandidateRepository(conn)
        conn.execute(
            "INSERT INTO candidates (first_name, last_name, email, phone, position, "
            "department_id, phase, notes, created_at) VALUES "
            "('Ana', 'Lopez', 'ana@example.com', '', 'Comercial', ?, 'Recibido', '', ?)",
            (department_id, "2026-01-01"),
        )
        conn.execute(
            "INSERT INTO candidates (first_name, last_name, email, phone, position, "
            "department_id, phase, notes, created_at) VALUES "
            "('Bea', 'Ruiz', 'bea@example.com', '', 'Comercial', ?, 'Recibido', '', ?)",
            (department_id, "2026-06-01"),
        )
        conn.commit()
        names = [c.full_name for c in repo.list_all()]
        assert names == ["Bea Ruiz", "Ana Lopez"]

    def test_list_all_scoped_to_department(
        self, conn: sqlite3.Connection, department_id: int, other_department_id: int
    ) -> None:
        repo = CandidateRepository(conn)
        repo.create(self.make_candidate_input(department_id=department_id))
        repo.create(self.make_candidate_input(department_id=other_department_id))
        scoped = repo.list_all(department_id=department_id)
        assert len(scoped) == 1
        assert scoped[0].department_id == department_id

    def test_list_all_scoped_to_phase(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = CandidateRepository(conn)
        repo.create(self.make_candidate_input(department_id=department_id, phase="Recibido"))
        repo.create(self.make_candidate_input(department_id=department_id, phase="Entrevista"))
        scoped = repo.list_all(phase="Entrevista")
        assert len(scoped) == 1
        assert scoped[0].phase == "Entrevista"

    def test_deleting_department_is_blocked_while_it_has_candidates(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        CandidateRepository(conn).create(self.make_candidate_input(department_id=department_id))
        with pytest.raises(ReferenceInUseError):
            DepartmentRepository(conn).delete(department_id)


class TestWorkAccidentRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_input(department_id=department_id, hire_date="2020-01-01")
        )
        assert employee.id is not None
        return employee.id

    def test_create_and_get(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = WorkAccidentRepository(conn)
        accident = repo.create(
            employee_id, date(2026, 3, 10), "Grave", "Caída desde escalera", True, True
        )
        assert accident.id is not None
        assert accident.severity == "Grave"
        assert accident.description == "Caída desde escalera"
        assert accident.caused_leave is True
        assert accident.reported_to_authority is True

        fetched = repo.get(accident.id)
        assert fetched == accident

    def test_create_unknown_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            WorkAccidentRepository(conn).create(999, date(2026, 3, 10), "Leve", "X", False, False)

    def test_create_invalid_severity_rejected_by_the_database(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        # La validación de gravedad vive en app/validation.py y en el propio
        # WorkAccidentDialog -- WorkAccidentRepository.create() no la repite
        # (a diferencia de otros repos, no llama a validation.* aquí), así
        # que el CHECK de la tabla es la última línea de defensa real.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO work_accidents (employee_id, accident_date, severity, "
                "description, caused_leave, reported_to_authority, created_at) "
                "VALUES (?, '2026-03-10', 'Catastrófico', 'X', 0, 0, '2026-03-10T00:00:00')",
                (employee_id,),
            )

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            WorkAccidentRepository(conn).get(999)

    def test_list_for_employee_orders_most_recent_first(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = WorkAccidentRepository(conn)
        repo.create(employee_id, date(2026, 1, 5), "Leve", "Primero", False, False)
        repo.create(employee_id, date(2026, 6, 1), "Leve", "Segundo", False, False)
        results = repo.list_for_employee(employee_id)
        assert [a.description for a in results] == ["Segundo", "Primero"]

    def test_list_for_employee_excludes_other_employees(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other = EmployeeRepository(conn).create(
            make_input(department_id=department_id, email="otro@example.com")
        )
        assert other.id is not None
        repo = WorkAccidentRepository(conn)
        repo.create(employee_id, date(2026, 1, 5), "Leve", "Mío", False, False)
        repo.create(other.id, date(2026, 1, 5), "Leve", "De otro", False, False)
        assert len(repo.list_for_employee(employee_id)) == 1

    def test_delete_removes_the_accident(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = WorkAccidentRepository(conn)
        accident = repo.create(employee_id, date(2026, 1, 5), "Leve", "X", False, False)
        assert accident.id is not None
        repo.delete(accident.id)
        with pytest.raises(NotFoundError):
            repo.get(accident.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            WorkAccidentRepository(conn).delete(999)

    def test_deleting_employee_cascades_accidents(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        WorkAccidentRepository(conn).create(
            employee_id, date(2026, 1, 5), "Leve", "X", False, False
        )
        EmployeeRepository(conn).delete(employee_id)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM work_accidents WHERE employee_id = ?", (employee_id,)
        ).fetchone()[0]
        assert remaining == 0


class TestEmployeeTrainingRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_input(department_id=department_id, hire_date="2020-01-01")
        )
        assert employee.id is not None
        return employee.id

    def test_create_and_get(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = EmployeeTrainingRepository(conn)
        training = repo.create(
            employee_id, "Carné de carretillero", date(2024, 1, 1), date(2027, 1, 1)
        )
        assert training.id is not None
        assert training.name == "Carné de carretillero"
        assert training.completion_date == date(2024, 1, 1)
        assert training.expiration_date == date(2027, 1, 1)

        fetched = repo.get(training.id)
        assert fetched == training

    def test_create_without_expiration(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeTrainingRepository(conn)
        training = repo.create(employee_id, "Curso de Excel", date(2023, 5, 1), None)
        assert training.expiration_date is None

    def test_create_unknown_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeTrainingRepository(conn).create(999, "X", date(2024, 1, 1), None)

    def test_create_empty_name_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeTrainingRepository(conn).create(employee_id, "   ", date(2024, 1, 1), None)

    def test_expiration_before_completion_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeTrainingRepository(conn).create(
                employee_id, "X", date(2024, 1, 1), date(2023, 1, 1)
            )

    def test_expiration_equal_to_completion_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeTrainingRepository(conn).create(
                employee_id, "X", date(2024, 1, 1), date(2024, 1, 1)
            )

    def test_completion_before_hire_date_is_allowed(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        # A diferencia de un accidente de trabajo, una certificación (un
        # carné, un idioma) puede haberse obtenido antes de empezar a
        # trabajar aquí -- deliberadamente sin comprobación de hire_date.
        repo = EmployeeTrainingRepository(conn)
        training = repo.create(employee_id, "Carné de conducir", date(2010, 1, 1), None)
        assert training.completion_date == date(2010, 1, 1)

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeTrainingRepository(conn).get(999)

    def test_list_for_employee_orders_most_recent_first(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeTrainingRepository(conn)
        repo.create(employee_id, "Primero", date(2020, 1, 5), None)
        repo.create(employee_id, "Segundo", date(2026, 6, 1), None)
        results = repo.list_for_employee(employee_id)
        assert [t.name for t in results] == ["Segundo", "Primero"]

    def test_list_for_employee_excludes_other_employees(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other = EmployeeRepository(conn).create(
            make_input(department_id=department_id, email="otro@example.com")
        )
        assert other.id is not None
        repo = EmployeeTrainingRepository(conn)
        repo.create(employee_id, "Mío", date(2024, 1, 5), None)
        repo.create(other.id, "De otro", date(2024, 1, 5), None)
        assert len(repo.list_for_employee(employee_id)) == 1

    def test_list_all_includes_every_employee(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other = EmployeeRepository(conn).create(
            make_input(department_id=department_id, email="otro2@example.com")
        )
        assert other.id is not None
        repo = EmployeeTrainingRepository(conn)
        repo.create(employee_id, "Mío", date(2024, 1, 5), None)
        repo.create(other.id, "De otro", date(2024, 1, 5), None)
        assert len(repo.list_all()) == 2

    def test_delete_removes_the_training(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeTrainingRepository(conn)
        training = repo.create(employee_id, "X", date(2024, 1, 5), None)
        assert training.id is not None
        repo.delete(training.id)
        with pytest.raises(NotFoundError):
            repo.get(training.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeTrainingRepository(conn).delete(999)

    def test_deleting_employee_cascades_trainings(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        EmployeeTrainingRepository(conn).create(employee_id, "X", date(2024, 1, 5), None)
        EmployeeRepository(conn).delete(employee_id)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM employee_trainings WHERE employee_id = ?", (employee_id,)
        ).fetchone()[0]
        assert remaining == 0


class TestITEpisodeRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_input(department_id=department_id, hire_date="2020-01-01")
        )
        assert employee.id is not None
        return employee.id

    def test_create_and_get(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = ITEpisodeRepository(conn)
        episode = repo.create(employee_id, "Común", date(2026, 3, 10))
        assert episode.id is not None
        assert episode.contingency == "Común"
        assert episode.leave_date == date(2026, 3, 10)
        assert episode.last_confirmation_date is None
        assert episode.return_date is None
        assert episode.is_open is True
        assert repo.get(episode.id) == episode

    def test_create_unknown_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            ITEpisodeRepository(conn).create(999, "Común", date(2026, 3, 10))

    def test_create_invalid_contingency_rejected_by_the_database(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO it_episodes (employee_id, contingency, leave_date, created_at) "
                "VALUES (?, 'Inventada', '2026-03-10', '2026-03-10T00:00:00')",
                (employee_id,),
            )

    def test_create_second_open_episode_for_the_same_employee_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = ITEpisodeRepository(conn)
        repo.create(employee_id, "Común", date(2026, 3, 10))
        with pytest.raises(RepositoryError):
            repo.create(employee_id, "Accidente de trabajo", date(2026, 3, 15))

    def test_create_new_episode_allowed_after_previous_one_closed(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = ITEpisodeRepository(conn)
        first = repo.create(employee_id, "Común", date(2026, 3, 10))
        assert first.id is not None
        repo.close(first.id, date(2026, 3, 20))
        second = repo.create(employee_id, "Accidente de trabajo", date(2026, 4, 1))
        assert second.id is not None

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            ITEpisodeRepository(conn).get(999)

    def test_list_for_employee_orders_most_recent_first(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = ITEpisodeRepository(conn)
        first = repo.create(employee_id, "Común", date(2026, 1, 5))
        assert first.id is not None
        repo.close(first.id, date(2026, 1, 10))
        second = repo.create(employee_id, "Accidente de trabajo", date(2026, 6, 1))
        results = repo.list_for_employee(employee_id)
        assert [e.id for e in results] == [second.id, first.id]

    def test_list_for_employee_excludes_other_employees(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other = EmployeeRepository(conn).create(
            make_input(department_id=department_id, email="otro@example.com")
        )
        assert other.id is not None
        repo = ITEpisodeRepository(conn)
        repo.create(employee_id, "Común", date(2026, 1, 5))
        repo.create(other.id, "Común", date(2026, 1, 5))
        assert len(repo.list_for_employee(employee_id)) == 1

    def test_get_open_episode_for_employee(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = ITEpisodeRepository(conn)
        assert repo.get_open_episode_for_employee(employee_id) is None
        episode = repo.create(employee_id, "Común", date(2026, 1, 5))
        assert repo.get_open_episode_for_employee(employee_id) == episode
        assert episode.id is not None
        repo.close(episode.id, date(2026, 1, 10))
        assert repo.get_open_episode_for_employee(employee_id) is None

    def test_set_confirmation(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = ITEpisodeRepository(conn)
        episode = repo.create(employee_id, "Común", date(2026, 1, 5))
        assert episode.id is not None
        updated = repo.set_confirmation(episode.id, date(2026, 1, 15))
        assert updated.last_confirmation_date == date(2026, 1, 15)

    def test_set_confirmation_on_closed_episode_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = ITEpisodeRepository(conn)
        episode = repo.create(employee_id, "Común", date(2026, 1, 5))
        assert episode.id is not None
        repo.close(episode.id, date(2026, 1, 10))
        with pytest.raises(RepositoryError):
            repo.set_confirmation(episode.id, date(2026, 1, 8))

    def test_close_sets_return_date_and_is_open_becomes_false(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = ITEpisodeRepository(conn)
        episode = repo.create(employee_id, "Común", date(2026, 1, 5))
        assert episode.id is not None
        closed = repo.close(episode.id, date(2026, 1, 20))
        assert closed.return_date == date(2026, 1, 20)
        assert closed.is_open is False

    def test_close_already_closed_episode_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = ITEpisodeRepository(conn)
        episode = repo.create(employee_id, "Común", date(2026, 1, 5))
        assert episode.id is not None
        repo.close(episode.id, date(2026, 1, 20))
        with pytest.raises(RepositoryError):
            repo.close(episode.id, date(2026, 1, 25))

    def test_delete_removes_the_episode(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = ITEpisodeRepository(conn)
        episode = repo.create(employee_id, "Común", date(2026, 1, 5))
        assert episode.id is not None
        repo.delete(episode.id)
        with pytest.raises(NotFoundError):
            repo.get(episode.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            ITEpisodeRepository(conn).delete(999)

    def test_deleting_employee_cascades_episodes(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        ITEpisodeRepository(conn).create(employee_id, "Común", date(2026, 1, 5))
        EmployeeRepository(conn).delete(employee_id)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM it_episodes WHERE employee_id = ?", (employee_id,)
        ).fetchone()[0]
        assert remaining == 0


class TestEmployeePrlTrainingDate:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ingeniería")
        assert dept.id is not None
        return dept.id

    def test_create_with_training_date(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_input(
                department_id=department_id, hire_date="2020-01-01", prl_training_date="2020-01-05"
            )
        )
        assert employee.prl_training_date == date(2020, 1, 5)

    def test_create_without_training_date_defaults_to_none(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(make_input(department_id=department_id))
        assert employee.prl_training_date is None

    def test_update_sets_training_date(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id, hire_date="2020-01-01"))
        assert employee.id is not None
        updated = repo.update(
            employee.id,
            make_input(
                department_id=department_id, hire_date="2020-01-01", prl_training_date="2020-02-01"
            ),
        )
        assert updated.prl_training_date == date(2020, 2, 1)

    def test_training_date_before_hire_date_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).create(
                make_input(
                    department_id=department_id,
                    hire_date="2020-01-01",
                    prl_training_date="2019-12-31",
                )
            )


class TestPayrollSettingsRepository:
    def test_get_returns_seeded_defaults(self, conn: sqlite3.Connection) -> None:
        settings = PayrollSettingsRepository(conn).get()
        assert settings.ss_employee_pct == 6.35
        assert settings.ss_employer_pct == 31.40

    def test_update_persists_new_values(self, conn: sqlite3.Connection) -> None:
        repo = PayrollSettingsRepository(conn)
        updated = repo.update(6.40, 30.0)
        assert updated.ss_employee_pct == 6.40
        assert updated.ss_employer_pct == 30.0
        assert repo.get().ss_employee_pct == 6.40

    def test_update_rejects_negative_percentage(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            PayrollSettingsRepository(conn).update(-1.0, 30.0)

    def test_update_rejects_percentage_above_100(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            PayrollSettingsRepository(conn).update(6.35, 100.1)


class TestPayrollRecordRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_input(department_id=department_id, salary=28000.0)
        )
        assert employee.id is not None
        return employee.id

    def test_generate_persists_a_snapshot(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        record = PayrollRecordRepository(conn).generate(employee_id, 2026, 3)
        assert record.id is not None
        assert record.employee_id == employee_id
        assert record.annual_gross_salary_snapshot == 28000.0
        assert record.payroll.year == 2026
        assert record.payroll.month == 3
        assert record.payroll.bruto_mes == round(28000.0 / 14, 2)

    def test_get_returns_none_when_not_generated(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        assert PayrollRecordRepository(conn).get(employee_id, 2026, 3) is None

    def test_get_returns_the_persisted_record(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        PayrollRecordRepository(conn).generate(employee_id, 2026, 3)
        found = PayrollRecordRepository(conn).get(employee_id, 2026, 3)
        assert found is not None
        assert found.payroll.month == 3

    def test_generate_unknown_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            PayrollRecordRepository(conn).generate(999, 2026, 3)

    def test_regenerating_overwrites_the_snapshot(
        self, conn: sqlite3.Connection, employee_id: int, department_id: int
    ) -> None:
        repo = PayrollRecordRepository(conn)
        first = repo.generate(employee_id, 2026, 3)
        assert first.annual_gross_salary_snapshot == 28000.0

        # Salary changes after the first generation -- regenerating should
        # snapshot the NEW salary, not silently keep the old one.
        EmployeeRepository(conn).update(
            employee_id, make_input(department_id=department_id, salary=32000.0)
        )
        second = repo.generate(employee_id, 2026, 3)
        assert second.annual_gross_salary_snapshot == 32000.0
        # Still one record for that employee/year/month, not two.
        assert len(repo.list_for_employee(employee_id)) == 1

    def test_salary_change_does_not_alter_an_existing_snapshot(
        self, conn: sqlite3.Connection, employee_id: int, department_id: int
    ) -> None:
        repo = PayrollRecordRepository(conn)
        repo.generate(employee_id, 2026, 3)
        EmployeeRepository(conn).update(
            employee_id, make_input(department_id=department_id, salary=99000.0)
        )
        # Re-fetching (not regenerating) must still show the frozen snapshot.
        still_frozen = repo.get(employee_id, 2026, 3)
        assert still_frozen is not None
        assert still_frozen.annual_gross_salary_snapshot == 28000.0

    def test_list_for_employee_sorted_chronologically(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = PayrollRecordRepository(conn)
        repo.generate(employee_id, 2026, 6)
        repo.generate(employee_id, 2026, 1)
        repo.generate(employee_id, 2025, 12)
        periods = [(r.payroll.year, r.payroll.month) for r in repo.list_for_employee(employee_id)]
        assert periods == [(2025, 12), (2026, 1), (2026, 6)]

    def test_list_for_employee_excludes_other_employees(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other = EmployeeRepository(conn).create(
            make_input(department_id=department_id, email="otro@example.com")
        )
        assert other.id is not None
        repo = PayrollRecordRepository(conn)
        repo.generate(employee_id, 2026, 3)
        repo.generate(other.id, 2026, 3)
        assert len(repo.list_for_employee(employee_id)) == 1

    def test_delete_removes_the_record(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = PayrollRecordRepository(conn)
        repo.generate(employee_id, 2026, 3)
        repo.delete(employee_id, 2026, 3)
        assert repo.get(employee_id, 2026, 3) is None

    def test_delete_missing_raises(self, conn: sqlite3.Connection, employee_id: int) -> None:
        with pytest.raises(NotFoundError):
            PayrollRecordRepository(conn).delete(employee_id, 2026, 3)

    def test_deleting_employee_cascades_records(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        PayrollRecordRepository(conn).generate(employee_id, 2026, 3)
        EmployeeRepository(conn).delete(employee_id)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM payroll_records WHERE employee_id = ?", (employee_id,)
        ).fetchone()[0]
        assert remaining == 0

    def test_generate_uses_current_payroll_settings(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        PayrollSettingsRepository(conn).update(10.0, 30.0)
        record = PayrollRecordRepository(conn).generate(employee_id, 2026, 3)
        assert record.payroll.ss_employee_pct == 10.0
        assert record.payroll.ss_employer_pct == 30.0

    def test_generate_snapshots_existing_supplements_and_advances(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        supplements = PayrollSupplementRepository(conn)
        supplements.create(employee_id, 2026, 3, "plus", "Plus de transporte", amount=100.0)
        supplements.create(employee_id, 2026, 3, "anticipo", "Anticipo urgencia", amount=250.0)

        record = PayrollRecordRepository(conn).generate(employee_id, 2026, 3)
        assert record.payroll.supplements_total == 100.0
        assert record.payroll.advances_total == 250.0
        assert record.payroll.bruto_mes == pytest.approx(round(28000.0 / 14, 2) + 100.0)

    def test_supplement_added_after_generating_does_not_alter_the_snapshot(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        record = PayrollRecordRepository(conn).generate(employee_id, 2026, 3)
        assert record.payroll.supplements_total == 0.0

        PayrollSupplementRepository(conn).create(
            employee_id, 2026, 3, "plus", "Añadido tarde", amount=999.0
        )
        still_frozen = PayrollRecordRepository(conn).get(employee_id, 2026, 3)
        assert still_frozen is not None
        assert still_frozen.payroll.supplements_total == 0.0

        regenerated = PayrollRecordRepository(conn).generate(employee_id, 2026, 3)
        assert regenerated.payroll.supplements_total == 999.0

    def test_monthly_totals_returns_all_twelve_months_zero_filled(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = PayrollRecordRepository(conn)
        repo.generate(employee_id, 2026, 3)
        summaries = repo.monthly_totals(2026)
        assert [s.month for s in summaries] == list(range(1, 13))
        march = next(s for s in summaries if s.month == 3)
        assert march.payroll_count == 1
        assert march.total_gross == pytest.approx(round(28000.0 / 14, 2))
        february = next(s for s in summaries if s.month == 2)
        assert february.payroll_count == 0
        assert february.total_gross == 0.0
        assert february.total_employer_cost == 0.0

    def test_monthly_totals_aggregates_across_employees(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other = EmployeeRepository(conn).create(
            make_input(department_id=department_id, email="otro@example.com", salary=28000.0)
        )
        assert other.id is not None
        repo = PayrollRecordRepository(conn)
        first = repo.generate(employee_id, 2026, 3)
        second = repo.generate(other.id, 2026, 3)
        march = next(s for s in repo.monthly_totals(2026) if s.month == 3)
        assert march.payroll_count == 2
        assert march.total_gross == pytest.approx(
            first.payroll.bruto_mes + second.payroll.bruto_mes
        )
        assert march.total_employer_cost == pytest.approx(
            first.payroll.coste_total_empresa + second.payroll.coste_total_empresa
        )

    def test_monthly_totals_scoped_to_department_excludes_other_departments(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other_department = DepartmentRepository(conn).create("Producción")
        assert other_department.id is not None
        other_employee = EmployeeRepository(conn).create(
            make_input(department_id=other_department.id, email="otro@example.com")
        )
        assert other_employee.id is not None
        repo = PayrollRecordRepository(conn)
        repo.generate(employee_id, 2026, 3)
        repo.generate(other_employee.id, 2026, 3)

        scoped = next(
            s for s in repo.monthly_totals(2026, department_id=department_id) if s.month == 3
        )
        assert scoped.payroll_count == 1

    def test_monthly_totals_excludes_other_years(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = PayrollRecordRepository(conn)
        repo.generate(employee_id, 2025, 3)
        march_2026 = next(s for s in repo.monthly_totals(2026) if s.month == 3)
        assert march_2026.payroll_count == 0

    def test_department_totals_aggregates_per_department(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other_department = DepartmentRepository(conn).create("Producción")
        assert other_department.id is not None
        other_employee = EmployeeRepository(conn).create(
            make_input(department_id=other_department.id, email="otro@example.com", salary=21000.0)
        )
        assert other_employee.id is not None
        repo = PayrollRecordRepository(conn)
        first = repo.generate(employee_id, 2026, 3)
        second = repo.generate(other_employee.id, 2026, 3)

        totals = {d.department_id: d for d in repo.department_totals(2026, 3)}
        assert totals[department_id].payroll_count == 1
        assert totals[department_id].total_gross == pytest.approx(first.payroll.bruto_mes)
        assert totals[other_department.id].payroll_count == 1
        assert totals[other_department.id].total_gross == pytest.approx(second.payroll.bruto_mes)

    def test_department_totals_includes_departments_with_no_records_that_month(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        empty_department = DepartmentRepository(conn).create("Sin nóminas todavía")
        assert empty_department.id is not None
        PayrollRecordRepository(conn).generate(employee_id, 2026, 3)

        totals = {d.department_id: d for d in PayrollRecordRepository(conn).department_totals(2026, 3)}
        assert empty_department.id in totals
        assert totals[empty_department.id].payroll_count == 0
        assert totals[empty_department.id].total_gross == 0.0
        assert totals[empty_department.id].total_employer_cost == 0.0

    def test_department_totals_scoped_to_a_single_department(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other_department = DepartmentRepository(conn).create("Producción")
        assert other_department.id is not None
        other_employee = EmployeeRepository(conn).create(
            make_input(department_id=other_department.id, email="otro@example.com")
        )
        assert other_employee.id is not None
        repo = PayrollRecordRepository(conn)
        repo.generate(employee_id, 2026, 3)
        repo.generate(other_employee.id, 2026, 3)

        scoped = repo.department_totals(2026, 3, department_id=department_id)
        assert [d.department_id for d in scoped] == [department_id]

    def test_department_totals_excludes_other_months(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        repo = PayrollRecordRepository(conn)
        repo.generate(employee_id, 2026, 3)
        april_totals = {d.department_id: d for d in repo.department_totals(2026, 4)}
        assert april_totals[department_id].payroll_count == 0

    def test_list_for_month_returns_generated_records(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        PayrollRecordRepository(conn).generate(employee_id, 2026, 3)
        records = PayrollRecordRepository(conn).list_for_month(2026, 3)
        assert len(records) == 1
        assert records[0].employee_id == employee_id

    def test_list_for_month_excludes_other_months_and_years(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = PayrollRecordRepository(conn)
        repo.generate(employee_id, 2026, 3)
        repo.generate(employee_id, 2026, 4)
        repo.generate(employee_id, 2025, 3)
        assert len(repo.list_for_month(2026, 3)) == 1

    def test_list_for_month_empty_when_nothing_generated(self, conn: sqlite3.Connection) -> None:
        assert PayrollRecordRepository(conn).list_for_month(2026, 3) == []

    def test_list_for_month_scoped_to_department(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other_department = DepartmentRepository(conn).create("Producción")
        assert other_department.id is not None
        other_employee = EmployeeRepository(conn).create(
            make_input(department_id=other_department.id, email="otro@example.com")
        )
        assert other_employee.id is not None
        repo = PayrollRecordRepository(conn)
        repo.generate(employee_id, 2026, 3)
        repo.generate(other_employee.id, 2026, 3)

        scoped = repo.list_for_month(2026, 3, department_id=department_id)
        assert [r.employee_id for r in scoped] == [employee_id]

    def test_list_for_month_ordered_by_employee_name(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        zeta = EmployeeRepository(conn).create(
            make_input(
                department_id=department_id, first_name="Zeta", email="zeta@example.com"
            )
        )
        alfa = EmployeeRepository(conn).create(
            make_input(
                department_id=department_id, first_name="Alfa", email="alfa@example.com"
            )
        )
        assert zeta.id is not None and alfa.id is not None
        repo = PayrollRecordRepository(conn)
        repo.generate(zeta.id, 2026, 3)
        repo.generate(alfa.id, 2026, 3)
        records = repo.list_for_month(2026, 3)
        assert [r.employee_id for r in records] == [alfa.id, zeta.id]


class TestPayrollSupplementRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(make_input(department_id=department_id))
        assert employee.id is not None
        return employee.id

    def test_create_a_plus(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = PayrollSupplementRepository(conn)
        supplement = repo.create(
            employee_id, 2026, 3, "plus", "Plus de idiomas", amount=75.0
        )
        assert supplement.id is not None
        assert supplement.supplement_type == "plus"
        assert supplement.amount == 75.0
        assert supplement.hours is None
        assert supplement.rate_per_hour is None

    def test_create_an_anticipo(self, conn: sqlite3.Connection, employee_id: int) -> None:
        supplement = PayrollSupplementRepository(conn).create(
            employee_id, 2026, 3, "anticipo", "Anticipo por mudanza", amount=400.0
        )
        assert supplement.supplement_type == "anticipo"
        assert supplement.amount == 400.0

    def test_create_horas_extra_computes_amount_from_hours_and_rate(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        supplement = PayrollSupplementRepository(conn).create(
            employee_id, 2026, 3, "horas_extra", "Cierre de mes",
            hours=10.0, rate_per_hour=15.0,
        )
        assert supplement.amount == 150.0
        assert supplement.hours == 10.0
        assert supplement.rate_per_hour == 15.0

    def test_horas_extra_without_hours_or_rate_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            PayrollSupplementRepository(conn).create(
                employee_id, 2026, 3, "horas_extra", "Sin datos"
            )

    def test_plus_with_hours_raises(self, conn: sqlite3.Connection, employee_id: int) -> None:
        with pytest.raises(validation.ValidationError):
            PayrollSupplementRepository(conn).create(
                employee_id, 2026, 3, "plus", "Con horas por error",
                amount=50.0, hours=5.0, rate_per_hour=10.0,
            )

    def test_zero_or_negative_amount_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            PayrollSupplementRepository(conn).create(
                employee_id, 2026, 3, "plus", "Inválido", amount=0.0
            )
        with pytest.raises(validation.ValidationError):
            PayrollSupplementRepository(conn).create(
                employee_id, 2026, 3, "anticipo", "Inválido", amount=-10.0
            )

    def test_invalid_type_rejected(self, conn: sqlite3.Connection, employee_id: int) -> None:
        with pytest.raises(validation.ValidationError):
            PayrollSupplementRepository(conn).create(
                employee_id, 2026, 3, "bono", "Tipo inventado", amount=50.0
            )

    def test_invalid_month_rejected(self, conn: sqlite3.Connection, employee_id: int) -> None:
        with pytest.raises(validation.ValidationError):
            PayrollSupplementRepository(conn).create(
                employee_id, 2026, 13, "plus", "Mes inválido", amount=50.0
            )

    def test_unknown_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            PayrollSupplementRepository(conn).create(999, 2026, 3, "plus", "X", amount=50.0)

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            PayrollSupplementRepository(conn).get(999)

    def test_list_for_employee_month_excludes_other_periods(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = PayrollSupplementRepository(conn)
        repo.create(employee_id, 2026, 3, "plus", "Marzo", amount=50.0)
        repo.create(employee_id, 2026, 4, "plus", "Abril", amount=60.0)
        march = repo.list_for_employee_month(employee_id, 2026, 3)
        assert len(march) == 1
        assert march[0].description == "Marzo"

    def test_list_for_employee_month_excludes_other_employees(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other = EmployeeRepository(conn).create(
            make_input(department_id=department_id, email="otro@example.com")
        )
        assert other.id is not None
        repo = PayrollSupplementRepository(conn)
        repo.create(employee_id, 2026, 3, "plus", "Mío", amount=50.0)
        repo.create(other.id, 2026, 3, "plus", "De otro", amount=60.0)
        assert len(repo.list_for_employee_month(employee_id, 2026, 3)) == 1

    def test_totals_separate_supplements_from_advances(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = PayrollSupplementRepository(conn)
        repo.create(employee_id, 2026, 3, "plus", "Transporte", amount=100.0)
        repo.create(employee_id, 2026, 3, "horas_extra", "Extra", hours=4.0, rate_per_hour=12.5)
        repo.create(employee_id, 2026, 3, "anticipo", "Anticipo", amount=300.0)
        supplements_total, advances_total = repo.totals_for_employee_month(employee_id, 2026, 3)
        assert supplements_total == 150.0  # 100 (plus) + 50 (4h * 12.5)
        assert advances_total == 300.0

    def test_totals_are_zero_with_no_entries(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        assert PayrollSupplementRepository(conn).totals_for_employee_month(
            employee_id, 2026, 3
        ) == (0.0, 0.0)

    def test_delete_removes_the_supplement(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = PayrollSupplementRepository(conn)
        supplement = repo.create(employee_id, 2026, 3, "plus", "X", amount=50.0)
        assert supplement.id is not None
        repo.delete(supplement.id)
        with pytest.raises(NotFoundError):
            repo.get(supplement.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            PayrollSupplementRepository(conn).delete(999)

    def test_deleting_employee_cascades_supplements(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        PayrollSupplementRepository(conn).create(
            employee_id, 2026, 3, "plus", "X", amount=50.0
        )
        EmployeeRepository(conn).delete(employee_id)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM payroll_supplements WHERE employee_id = ?", (employee_id,)
        ).fetchone()[0]
        assert remaining == 0

    def test_list_all_for_employee_spans_every_month_and_excludes_others(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other = EmployeeRepository(conn).create(
            make_input(department_id=department_id, email="otro@example.com")
        )
        assert other.id is not None
        repo = PayrollSupplementRepository(conn)
        repo.create(employee_id, 2026, 4, "plus", "Abril", amount=60.0)
        repo.create(employee_id, 2026, 3, "plus", "Marzo", amount=50.0)
        repo.create(other.id, 2026, 3, "plus", "De otro", amount=60.0)

        results = repo.list_all_for_employee(employee_id)
        assert [s.description for s in results] == ["Marzo", "Abril"]


class TestUserRepository:
    def test_create_and_authenticate_with_correct_password(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        created = repo.create("admin", "admin")
        assert created.id is not None
        assert created.username == "admin"
        authenticated = repo.authenticate("admin", "admin")
        assert authenticated is not None
        assert authenticated.id == created.id

    def test_authenticate_rejects_wrong_password(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        repo.create("admin", "admin")
        assert repo.authenticate("admin", "wrong-password") is None

    def test_authenticate_rejects_unknown_username(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        repo.create("admin", "admin")
        assert repo.authenticate("nobody", "admin") is None

    def test_authenticate_username_is_case_insensitive(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        repo.create("admin", "secret123")
        assert repo.authenticate("ADMIN", "secret123") is not None
        assert repo.authenticate("Admin", "secret123") is not None

    def test_authenticate_password_is_case_sensitive(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        repo.create("admin", "Secret123")
        assert repo.authenticate("admin", "secret123") is None

    def test_password_never_stored_in_plaintext(self, conn: sqlite3.Connection) -> None:
        UserRepository(conn).create("admin", "admin")
        row = conn.execute(
            "SELECT password_hash, salt FROM users WHERE username = 'admin'"
        ).fetchone()
        assert row["password_hash"] != "admin"
        assert "admin" not in row["password_hash"]
        # hex-encoded SHA-256 digest -> 64 hex chars; salt is 16 bytes -> 32 hex chars.
        assert len(row["password_hash"]) == 64
        assert len(row["salt"]) == 32

    def test_each_user_gets_a_distinct_random_salt(self, conn: sqlite3.Connection) -> None:
        UserRepository(conn).create("alice", "same-password")
        UserRepository(conn).create("bob", "same-password")
        rows = conn.execute("SELECT username, password_hash, salt FROM users").fetchall()
        salts = {row["salt"] for row in rows}
        hashes = {row["password_hash"] for row in rows}
        assert len(salts) == 2, "identical passwords must not share a salt"
        assert len(hashes) == 2, "distinct salts must produce distinct hashes"

    def test_create_duplicate_username_rejected(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        repo.create("admin", "admin123")
        with pytest.raises(DuplicateError):
            repo.create("admin", "different-password")

    def test_create_duplicate_username_case_insensitive(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        repo.create("admin", "admin123")
        with pytest.raises(DuplicateError):
            repo.create("ADMIN", "different-password")

    def test_create_rejects_too_short_username(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            UserRepository(conn).create("ab", "admin123")

    def test_create_rejects_too_short_password(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            UserRepository(conn).create("admin", "abc")

    def test_list_all_sorted_by_username(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        repo.create("carol", "password1")
        repo.create("alice", "password2")
        repo.create("bob", "password3")
        assert [u.username for u in repo.list_all()] == ["alice", "bob", "carol"]

    def test_create_defaults_to_admin_with_no_department(
        self, conn: sqlite3.Connection
    ) -> None:
        user = UserRepository(conn).create("admin", "admin123")
        assert user.role == "admin"
        assert user.department_id is None

    def test_create_encargado_requires_a_department(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            UserRepository(conn).create("jefe", "password1", role="encargado")

    def test_create_encargado_with_department(self, conn: sqlite3.Connection) -> None:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        user = UserRepository(conn).create(
            "jefe", "password1", role="encargado", department_id=dept.id
        )
        assert user.role == "encargado"
        assert user.department_id == dept.id

    def test_create_admin_rejects_a_department(self, conn: sqlite3.Connection) -> None:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        with pytest.raises(validation.ValidationError):
            UserRepository(conn).create(
                "admin2", "password1", role="admin", department_id=dept.id
            )

    def test_create_rejects_unknown_role(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            UserRepository(conn).create("x", "password1", role="gerente")

    def test_create_encargado_rejects_nonexistent_department(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(NotFoundError):
            UserRepository(conn).create(
                "jefe", "password1", role="encargado", department_id=999
            )

    def test_list_all_round_trips_role_and_department(self, conn: sqlite3.Connection) -> None:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        UserRepository(conn).create(
            "jefe", "password1", role="encargado", department_id=dept.id
        )
        [fetched] = UserRepository(conn).list_all()
        assert fetched.role == "encargado"
        assert fetched.department_id == dept.id

    def test_delete_removes_user(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        repo.create("admin", "admin123")
        second = repo.create("admin2", "password1")
        repo.delete(second.id)  # type: ignore[arg-type]
        assert [u.username for u in repo.list_all()] == ["admin"]

    def test_delete_unknown_user_raises_not_found(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            UserRepository(conn).delete(999)

    def test_delete_last_admin_rejected(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        only_admin = repo.create("admin", "admin123")
        with pytest.raises(RepositoryError):
            repo.delete(only_admin.id)  # type: ignore[arg-type]
        assert len(repo.list_all()) == 1

    def test_delete_admin_allowed_when_another_admin_exists(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        first = repo.create("admin", "admin123")
        repo.create("admin2", "password1")
        repo.delete(first.id)  # type: ignore[arg-type]
        assert [u.username for u in repo.list_all()] == ["admin2"]

    def test_delete_self_rejected_at_the_repository_layer(
        self, conn: sqlite3.Connection
    ) -> None:
        # Regresión: este guard solo vivía en UserManagerDialog._handle_
        # delete(), no aquí -- a diferencia del guard del último
        # administrador (ver test_delete_last_admin_rejected), que sí
        # estaba blindado a este nivel. Llamar al repositorio directamente
        # con el propio id, sin pasar por el diálogo, tenía éxito.
        repo = UserRepository(conn)
        first = repo.create("admin", "admin123")
        repo.create("admin2", "password1")
        with pytest.raises(RepositoryError):
            repo.delete(first.id, current_user_id=first.id)  # type: ignore[arg-type]
        assert len(repo.list_all()) == 2

    def test_delete_someone_else_still_allowed_with_current_user_id_set(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        first = repo.create("admin", "admin123")
        second = repo.create("admin2", "password1")
        repo.delete(second.id, current_user_id=first.id)  # type: ignore[arg-type]
        assert [u.username for u in repo.list_all()] == ["admin"]

    def test_delete_without_current_user_id_does_not_check_self_delete(
        self, conn: sqlite3.Connection
    ) -> None:
        # current_user_id=None (el valor por defecto) es para llamantes que
        # no conocen la sesión activa -- no debe bloquear nada por sí solo.
        repo = UserRepository(conn)
        only_admin = repo.create("admin", "admin123")
        repo.create("admin2", "password1")
        repo.delete(only_admin.id)  # type: ignore[arg-type]
        assert [u.username for u in repo.list_all()] == ["admin2"]

    def test_delete_encargado_never_blocked_by_admin_rule(
        self, conn: sqlite3.Connection
    ) -> None:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        repo = UserRepository(conn)
        repo.create("admin", "admin123")
        jefe = repo.create("jefe", "password1", role="encargado", department_id=dept.id)
        repo.delete(jefe.id)  # type: ignore[arg-type]
        assert [u.username for u in repo.list_all()] == ["admin"]

    def test_get_returns_the_user(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        created = repo.create("admin", "admin123")
        assert created.id is not None
        fetched = repo.get(created.id)
        assert fetched == created

    def test_get_unknown_user_raises_not_found(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            UserRepository(conn).get(999)

    def test_change_own_password_with_correct_current_password(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "old-password")
        assert user.id is not None
        repo.change_own_password(user.id, "old-password", "new-password")
        assert repo.authenticate("admin", "new-password") is not None
        assert repo.authenticate("admin", "old-password") is None

    def test_change_own_password_rejects_wrong_current_password(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "old-password")
        assert user.id is not None
        with pytest.raises(RepositoryError):
            repo.change_own_password(user.id, "wrong-current", "new-password")
        assert repo.authenticate("admin", "old-password") is not None

    def test_change_own_password_rejects_too_short_new_password(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "old-password")
        assert user.id is not None
        with pytest.raises(validation.ValidationError):
            repo.change_own_password(user.id, "old-password", "abc")

    def test_email_connection_starts_unset(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        assert repo.get_email_connection(user.id) is None
        assert user.email_provider is None
        assert user.email_address is None

    def test_set_and_get_email_connection(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        repo.set_email_connection(user.id, "gmail", "hr@example.com", "app-password-123")
        connection = repo.get_email_connection(user.id)
        assert connection is not None
        assert connection.provider == "gmail"
        assert connection.address == "hr@example.com"
        assert connection.app_password == "app-password-123"
        refreshed = repo.get(user.id)
        assert refreshed.email_provider == "gmail"
        assert refreshed.email_address == "hr@example.com"

    def test_set_email_connection_rejects_unknown_provider(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        with pytest.raises(validation.ValidationError):
            repo.set_email_connection(user.id, "yahoo", "hr@example.com", "secret")

    def test_set_email_connection_rejects_invalid_email(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        with pytest.raises(validation.ValidationError):
            repo.set_email_connection(user.id, "gmail", "not-an-email", "secret")

    def test_clear_email_connection(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        repo.set_email_connection(user.id, "outlook", "hr@example.com", "secret")
        repo.clear_email_connection(user.id)
        assert repo.get_email_connection(user.id) is None

    def test_new_user_defaults_to_not_receiving_crash_reports(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.receive_crash_reports is False

    def test_set_receive_crash_reports_requires_email_connection(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        with pytest.raises(RepositoryError):
            repo.set_receive_crash_reports(user.id, True)

    def test_set_receive_crash_reports_enables_with_email_connected(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        repo.set_email_connection(user.id, "gmail", "hr@example.com", "secret")
        repo.set_receive_crash_reports(user.id, True)
        assert repo.get(user.id).receive_crash_reports is True

    def test_set_receive_crash_reports_can_disable(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        repo.set_email_connection(user.id, "gmail", "hr@example.com", "secret")
        repo.set_receive_crash_reports(user.id, True)
        repo.set_receive_crash_reports(user.id, False)
        assert repo.get(user.id).receive_crash_reports is False

    def test_clear_email_connection_also_disables_crash_reports(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        repo.set_email_connection(user.id, "gmail", "hr@example.com", "secret")
        repo.set_receive_crash_reports(user.id, True)
        repo.clear_email_connection(user.id)
        assert repo.get(user.id).receive_crash_reports is False

    def test_list_crash_report_recipients_empty_by_default(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        repo.create("admin", "admin123")
        assert repo.list_crash_report_recipients() == []

    def test_list_crash_report_recipients_only_includes_opted_in_users(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        subscribed = repo.create("admin1", "admin123")
        connected_only = repo.create("admin2", "admin123")
        assert subscribed.id is not None
        assert connected_only.id is not None
        repo.set_email_connection(subscribed.id, "gmail", "one@example.com", "secret")
        repo.set_receive_crash_reports(subscribed.id, True)
        repo.set_email_connection(connected_only.id, "outlook", "two@example.com", "secret")

        recipients = repo.list_crash_report_recipients()

        assert len(recipients) == 1
        assert recipients[0].address == "one@example.com"
        assert recipients[0].provider == "gmail"

    def test_needs_weekly_digest_false_without_email_connected(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        assert repo.needs_weekly_digest(user.id, date(2026, 7, 24)) is False

    def test_needs_weekly_digest_true_when_never_sent(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        repo.set_email_connection(user.id, "gmail", "hr@example.com", "secret")
        assert repo.needs_weekly_digest(user.id, date(2026, 7, 24)) is True

    def test_needs_weekly_digest_false_within_7_days_of_last_send(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        repo.set_email_connection(user.id, "gmail", "hr@example.com", "secret")
        repo.mark_digest_sent(user.id, datetime(2026, 7, 20, 9, 0))
        assert repo.needs_weekly_digest(user.id, date(2026, 7, 24)) is False

    def test_needs_weekly_digest_true_after_7_days(self, conn: sqlite3.Connection) -> None:
        repo = UserRepository(conn)
        user = repo.create("admin", "admin123")
        assert user.id is not None
        repo.set_email_connection(user.id, "gmail", "hr@example.com", "secret")
        repo.mark_digest_sent(user.id, datetime(2026, 7, 17, 9, 0))
        assert repo.needs_weekly_digest(user.id, date(2026, 7, 24)) is True


class TestAppSettingsRepository:
    def test_get_theme_mode_defaults_to_light(self, conn: sqlite3.Connection) -> None:
        assert AppSettingsRepository(conn).get_theme_mode() == "light"

    def test_set_theme_mode_persists(self, conn: sqlite3.Connection) -> None:
        repo = AppSettingsRepository(conn)
        repo.set_theme_mode("dark")
        assert repo.get_theme_mode() == "dark"

    def test_set_theme_mode_back_to_light(self, conn: sqlite3.Connection) -> None:
        repo = AppSettingsRepository(conn)
        repo.set_theme_mode("dark")
        repo.set_theme_mode("light")
        assert repo.get_theme_mode() == "light"

    def test_set_theme_mode_rejects_invalid_value(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            AppSettingsRepository(conn).set_theme_mode("blue")

    def test_get_annual_vacation_days_defaults_to_22(self, conn: sqlite3.Connection) -> None:
        assert AppSettingsRepository(conn).get_annual_vacation_days() == 22.0

    def test_set_annual_vacation_days_persists(self, conn: sqlite3.Connection) -> None:
        repo = AppSettingsRepository(conn)
        repo.set_annual_vacation_days(30)
        assert repo.get_annual_vacation_days() == 30.0

    def test_set_annual_vacation_days_rejects_negative(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            AppSettingsRepository(conn).set_annual_vacation_days(-5)

    def test_get_data_retention_years_defaults_to_4(self, conn: sqlite3.Connection) -> None:
        assert AppSettingsRepository(conn).get_data_retention_years() == 4

    def test_set_data_retention_years_persists(self, conn: sqlite3.Connection) -> None:
        repo = AppSettingsRepository(conn)
        repo.set_data_retention_years(6)
        assert repo.get_data_retention_years() == 6

    def test_set_data_retention_years_rejects_negative(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            AppSettingsRepository(conn).set_data_retention_years(-1)

    def test_get_company_name_defaults_to_empty(self, conn: sqlite3.Connection) -> None:
        assert AppSettingsRepository(conn).get_company_name() == ""

    def test_set_company_name_persists(self, conn: sqlite3.Connection) -> None:
        repo = AppSettingsRepository(conn)
        repo.set_company_name("Empresa Ficticia S.L.")
        assert repo.get_company_name() == "Empresa Ficticia S.L."

    def test_set_company_name_rejects_too_long(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            AppSettingsRepository(conn).set_company_name("x" * 71)

    def test_get_company_iban_defaults_to_empty(self, conn: sqlite3.Connection) -> None:
        assert AppSettingsRepository(conn).get_company_iban() == ""

    def test_set_company_iban_persists_formatted(self, conn: sqlite3.Connection) -> None:
        repo = AppSettingsRepository(conn)
        repo.set_company_iban("ES9121000418450200051332")
        assert repo.get_company_iban() == "ES91 2100 0418 4502 0005 1332"

    def test_set_company_iban_rejects_invalid_checksum(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            AppSettingsRepository(conn).set_company_iban("ES0021000418450200051332")


class TestCollectiveAgreementRepository:
    def test_create_and_get(self, conn: sqlite3.Connection) -> None:
        repo = CollectiveAgreementRepository(conn)
        created = repo.create("Convenio Estatal de Comercio")
        assert created.id is not None
        assert repo.get(created.id).name == "Convenio Estatal de Comercio"

    def test_create_duplicate_name_rejected_case_insensitive(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = CollectiveAgreementRepository(conn)
        repo.create("Convenio Hostelería")
        with pytest.raises(DuplicateError):
            repo.create("convenio hostelería")

    def test_create_empty_name_rejected(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            CollectiveAgreementRepository(conn).create("   ")

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            CollectiveAgreementRepository(conn).get(999)

    def test_list_all_sorted_by_name(self, conn: sqlite3.Connection) -> None:
        repo = CollectiveAgreementRepository(conn)
        repo.create("Convenio Hostelería")
        repo.create("Convenio Comercio")
        names = [a.name for a in repo.list_all()]
        assert names == ["Convenio Comercio", "Convenio Hostelería"]

    def test_update_renames(self, conn: sqlite3.Connection) -> None:
        repo = CollectiveAgreementRepository(conn)
        created = repo.create("Convenio Antiguo")
        assert created.id is not None
        renamed = repo.update(created.id, "Convenio Renombrado")
        assert renamed.name == "Convenio Renombrado"
        assert repo.get(created.id).name == "Convenio Renombrado"

    def test_update_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            CollectiveAgreementRepository(conn).update(999, "X")

    def test_delete_removes_agreement(self, conn: sqlite3.Connection) -> None:
        repo = CollectiveAgreementRepository(conn)
        created = repo.create("Temporal")
        assert created.id is not None
        repo.delete(created.id)
        with pytest.raises(NotFoundError):
            repo.get(created.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            CollectiveAgreementRepository(conn).delete(999)

    def test_delete_cascades_to_its_categories(self, conn: sqlite3.Connection) -> None:
        # A diferencia de departamentos/turnos (bloqueados explícitamente si
        # tienen referencias activas), un convenio se puede eliminar
        # libremente: sus categorías cuelgan con ON DELETE CASCADE, así que
        # nunca hace falta comprobar nada antes de borrar.
        agreement_repo = CollectiveAgreementRepository(conn)
        category_repo = ProfessionalCategoryRepository(conn)
        agreement = agreement_repo.create("Convenio Comercio")
        assert agreement.id is not None
        category = category_repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement.id, name="Oficial", minimum_salary=18000.0
            )
        )
        assert category.id is not None
        agreement_repo.delete(agreement.id)
        with pytest.raises(NotFoundError):
            category_repo.get(category.id)

    def test_deleting_agreement_clears_employees_professional_category_id(
        self, conn: sqlite3.Connection
    ) -> None:
        agreement_repo = CollectiveAgreementRepository(conn)
        category_repo = ProfessionalCategoryRepository(conn)
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        agreement = agreement_repo.create("Convenio Comercio")
        assert agreement.id is not None
        category = category_repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement.id, name="Oficial", minimum_salary=18000.0
            )
        )
        assert category.id is not None
        emp_repo = EmployeeRepository(conn)
        employee = emp_repo.create(
            make_input(department_id=dept.id, professional_category_id=category.id)
        )
        assert employee.id is not None
        agreement_repo.delete(agreement.id)
        assert emp_repo.get(employee.id).professional_category_id is None


class TestProfessionalCategoryRepository:
    @pytest.fixture()
    def agreement_id(self, conn: sqlite3.Connection) -> int:
        agreement = CollectiveAgreementRepository(conn).create("Convenio Estatal de Comercio")
        assert agreement.id is not None
        return agreement.id

    def test_create_and_get(self, conn: sqlite3.Connection, agreement_id: int) -> None:
        repo = ProfessionalCategoryRepository(conn)
        created = repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement_id, name="Oficial de primera",
                minimum_salary=18000.0,
            )
        )
        assert created.id is not None
        fetched = repo.get(created.id)
        assert fetched.name == "Oficial de primera"
        assert fetched.minimum_salary == 18000.0
        assert fetched.collective_agreement_id == agreement_id

    def test_create_nonexistent_agreement_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            ProfessionalCategoryRepository(conn).create(
                ProfessionalCategoryInput(
                    collective_agreement_id=999, name="X", minimum_salary=15000.0
                )
            )

    def test_create_negative_minimum_salary_rejected(
        self, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError) as exc_info:
            ProfessionalCategoryRepository(conn).create(
                ProfessionalCategoryInput(
                    collective_agreement_id=agreement_id, name="X", minimum_salary=-1.0
                )
            )
        assert exc_info.value.field == "salario_minimo"

    def test_create_empty_name_rejected(
        self, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            ProfessionalCategoryRepository(conn).create(
                ProfessionalCategoryInput(
                    collective_agreement_id=agreement_id, name="  ", minimum_salary=15000.0
                )
            )

    def test_create_duplicate_name_within_same_agreement_rejected(
        self, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repo = ProfessionalCategoryRepository(conn)
        repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement_id, name="Oficial", minimum_salary=18000.0
            )
        )
        with pytest.raises(DuplicateError):
            repo.create(
                ProfessionalCategoryInput(
                    collective_agreement_id=agreement_id, name="oficial", minimum_salary=19000.0
                )
            )

    def test_same_name_allowed_in_a_different_agreement(
        self, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repo = ProfessionalCategoryRepository(conn)
        other_agreement = CollectiveAgreementRepository(conn).create("Convenio Hostelería")
        assert other_agreement.id is not None
        repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement_id, name="Oficial", minimum_salary=18000.0
            )
        )
        second = repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=other_agreement.id, name="Oficial", minimum_salary=16000.0
            )
        )
        assert second.name == "Oficial"

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            ProfessionalCategoryRepository(conn).get(999)

    def test_update_changes_name_and_minimum_salary(
        self, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repo = ProfessionalCategoryRepository(conn)
        created = repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement_id, name="Oficial", minimum_salary=18000.0
            )
        )
        assert created.id is not None
        updated = repo.update(
            created.id,
            ProfessionalCategoryInput(
                collective_agreement_id=agreement_id, name="Oficial de 1ª", minimum_salary=18500.0
            ),
        )
        assert updated.name == "Oficial de 1ª"
        assert updated.minimum_salary == 18500.0

    def test_update_missing_raises(
        self, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        with pytest.raises(NotFoundError):
            ProfessionalCategoryRepository(conn).update(
                999,
                ProfessionalCategoryInput(
                    collective_agreement_id=agreement_id, name="X", minimum_salary=15000.0
                ),
            )

    def test_list_for_agreement_only_returns_that_agreements_categories(
        self, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repo = ProfessionalCategoryRepository(conn)
        other_agreement = CollectiveAgreementRepository(conn).create("Convenio Hostelería")
        assert other_agreement.id is not None
        repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement_id, name="Oficial", minimum_salary=18000.0
            )
        )
        repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=other_agreement.id, name="Camarero", minimum_salary=16000.0
            )
        )
        names = [c.name for c in repo.list_for_agreement(agreement_id)]
        assert names == ["Oficial"]

    def test_list_all_spans_every_agreement(
        self, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repo = ProfessionalCategoryRepository(conn)
        other_agreement = CollectiveAgreementRepository(conn).create("Convenio Hostelería")
        assert other_agreement.id is not None
        repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement_id, name="Oficial", minimum_salary=18000.0
            )
        )
        repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=other_agreement.id, name="Camarero", minimum_salary=16000.0
            )
        )
        names = {c.name for c in repo.list_all()}
        assert names == {"Oficial", "Camarero"}

    def test_delete_removes_category(
        self, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repo = ProfessionalCategoryRepository(conn)
        created = repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement_id, name="Oficial", minimum_salary=18000.0
            )
        )
        assert created.id is not None
        repo.delete(created.id)
        with pytest.raises(NotFoundError):
            repo.get(created.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            ProfessionalCategoryRepository(conn).delete(999)

    def test_delete_in_use_unassigns_employee_instead_of_blocking(
        self, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        # employees.professional_category_id es ON DELETE SET NULL (igual
        # que shift_id), no RESTRICT: a diferencia de un departamento o un
        # turno con asignaciones reales, aquí no hace falta ninguna
        # comprobación previa de "en uso".
        category_repo = ProfessionalCategoryRepository(conn)
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        category = category_repo.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement_id, name="Oficial", minimum_salary=18000.0
            )
        )
        assert category.id is not None
        emp_repo = EmployeeRepository(conn)
        employee = emp_repo.create(
            make_input(department_id=dept.id, professional_category_id=category.id)
        )
        assert employee.id is not None
        category_repo.delete(category.id)
        assert emp_repo.get(employee.id).professional_category_id is None


class TestEmployeeProfessionalCategory:
    """professional_category_id es un tercer campo de clasificación,
    completamente independiente de manager_id/head_of_department_id: sin
    restricción de departamento/actividad/ciclo, solo existencia de la
    categoría (igual que head_of_department_id con su departamento)."""

    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def category_id(self, conn: sqlite3.Connection) -> int:
        agreement = CollectiveAgreementRepository(conn).create("Convenio Estatal de Comercio")
        assert agreement.id is not None
        category = ProfessionalCategoryRepository(conn).create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement.id, name="Oficial de primera",
                minimum_salary=18000.0,
            )
        )
        assert category.id is not None
        return category.id

    def test_create_with_professional_category_persists_and_round_trips(
        self, conn: sqlite3.Connection, department_id: int, category_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(
            make_input(department_id=department_id, professional_category_id=category_id)
        )
        assert employee.professional_category_id == category_id
        assert employee.id is not None
        assert repo.get(employee.id).professional_category_id == category_id

    def test_defaults_to_none(self, conn: sqlite3.Connection, department_id: int) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id))
        assert employee.professional_category_id is None

    def test_search_also_returns_professional_category_id(
        self, conn: sqlite3.Connection, department_id: int, category_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.create(
            make_input(department_id=department_id, professional_category_id=category_id)
        )
        [found] = repo.search(department_id=department_id)
        assert found.professional_category_id == category_id

    def test_update_can_assign_and_clear_it(
        self, conn: sqlite3.Connection, department_id: int, category_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        employee = repo.create(make_input(department_id=department_id))
        assert employee.id is not None

        assigned = repo.update(
            employee.id,
            make_input(department_id=department_id, professional_category_id=category_id),
        )
        assert assigned.professional_category_id == category_id

        cleared = repo.update(
            employee.id,
            make_input(department_id=department_id, professional_category_id=None),
        )
        assert cleared.professional_category_id is None

    def test_nonexistent_category_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        with pytest.raises(NotFoundError):
            repo.create(
                make_input(department_id=department_id, professional_category_id=999)
            )

    def test_category_from_a_different_agreement_than_department_has_no_restriction(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # A diferencia de manager_id, la categoría profesional no tiene
        # ninguna relación con el departamento del empleado -- puede venir
        # de cualquier convenio, sin restricción de coincidencia.
        agreement = CollectiveAgreementRepository(conn).create("Convenio Hostelería")
        assert agreement.id is not None
        category = ProfessionalCategoryRepository(conn).create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement.id, name="Camarero", minimum_salary=16000.0
            )
        )
        assert category.id is not None
        repo = EmployeeRepository(conn)
        employee = repo.create(
            make_input(department_id=department_id, professional_category_id=category.id)
        )
        assert employee.professional_category_id == category.id


class TestEmployeeSelfServicePin:
    """PIN de 4-6 dígitos para el autoservicio ligero (punto 17): ni el
    hash ni la sal salen nunca del propio EmployeeRepository -- Employee
    (el modelo) no los expone en absoluto, igual que User.password_hash/
    salt nunca salen de UserRepository."""

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        employee = EmployeeRepository(conn).create(
            make_input(department_id=dept.id, email="ana@example.com")
        )
        assert employee.id is not None
        return employee.id

    def test_no_pin_by_default(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = EmployeeRepository(conn)
        assert repo.has_self_service_pin(employee_id) is False
        assert repo.authenticate_self_service("ana@example.com", "1234") is None

    def test_set_pin_then_authenticate_succeeds(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.set_self_service_pin(employee_id, "4321")
        assert repo.has_self_service_pin(employee_id) is True
        authenticated = repo.authenticate_self_service("ana@example.com", "4321")
        assert authenticated is not None
        assert authenticated.id == employee_id

    def test_authenticate_email_is_case_insensitive(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.set_self_service_pin(employee_id, "4321")
        assert repo.authenticate_self_service("ANA@EXAMPLE.COM", "4321") is not None

    def test_authenticate_wrong_pin_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.set_self_service_pin(employee_id, "4321")
        assert repo.authenticate_self_service("ana@example.com", "0000") is None

    def test_authenticate_wrong_email_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.set_self_service_pin(employee_id, "4321")
        assert repo.authenticate_self_service("nadie@example.com", "4321") is None

    @pytest.mark.parametrize("bad_pin", ["123", "1234567", "abcd", "", "12 34", "12.34"])
    def test_set_pin_rejects_invalid_formats(
        self, conn: sqlite3.Connection, employee_id: int, bad_pin: str
    ) -> None:
        with pytest.raises(validation.ValidationError) as exc_info:
            EmployeeRepository(conn).set_self_service_pin(employee_id, bad_pin)
        assert exc_info.value.field == "pin"

    def test_clear_pin_revokes_access(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = EmployeeRepository(conn)
        repo.set_self_service_pin(employee_id, "4321")
        repo.clear_self_service_pin(employee_id)
        assert repo.has_self_service_pin(employee_id) is False
        assert repo.authenticate_self_service("ana@example.com", "4321") is None

    def test_inactive_employee_cannot_authenticate(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.set_self_service_pin(employee_id, "4321")
        repo.terminate(employee_id, "2026-06-01", "Baja voluntaria")
        assert repo.authenticate_self_service("ana@example.com", "4321") is None

    def test_set_pin_on_nonexistent_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeRepository(conn).set_self_service_pin(999, "1234")

    def test_has_pin_on_nonexistent_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeRepository(conn).has_self_service_pin(999)

    def test_clear_pin_on_nonexistent_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeRepository(conn).clear_self_service_pin(999)

    def test_employee_model_never_exposes_pin_hash_or_salt(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.set_self_service_pin(employee_id, "4321")
        employee = repo.get(employee_id)
        assert not hasattr(employee, "self_service_pin_hash")
        assert not hasattr(employee, "self_service_pin_salt")

    def test_replacing_a_pin_invalidates_the_old_one(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = EmployeeRepository(conn)
        repo.set_self_service_pin(employee_id, "1111")
        repo.set_self_service_pin(employee_id, "2222")
        assert repo.authenticate_self_service("ana@example.com", "1111") is None
        assert repo.authenticate_self_service("ana@example.com", "2222") is not None


class TestObjectiveRepository:
    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        employee = EmployeeRepository(conn).create(make_input(department_id=dept.id))
        assert employee.id is not None
        return employee.id

    def test_create_defaults_to_pendiente(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = ObjectiveRepository(conn)
        objective = repo.create(employee_id, "Aumentar ventas", date(2026, 12, 31))
        assert objective.status == "pendiente"
        assert objective.id is not None
        assert repo.get(objective.id).status == "pendiente"

    def test_create_accepts_a_target_date_in_the_past(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        # Backfill de un objetivo con fecha ya pasada es un caso legítimo
        # (ver Objective's docstring) -- el repositorio no lo rechaza.
        repo = ObjectiveRepository(conn)
        objective = repo.create(employee_id, "Objetivo antiguo", date(2020, 1, 1))
        assert objective.target_date == date(2020, 1, 1)

    def test_create_empty_title_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            ObjectiveRepository(conn).create(employee_id, "   ", date(2026, 12, 31))

    def test_create_nonexistent_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            ObjectiveRepository(conn).create(999, "X", date(2026, 12, 31))

    def test_update_status_persists(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = ObjectiveRepository(conn)
        objective = repo.create(employee_id, "Objetivo", date(2026, 12, 31))
        assert objective.id is not None
        updated = repo.update_status(objective.id, "cumplido")
        assert updated.status == "cumplido"
        assert repo.get(objective.id).status == "cumplido"

    def test_update_status_rejects_invalid_value(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = ObjectiveRepository(conn)
        objective = repo.create(employee_id, "Objetivo", date(2026, 12, 31))
        assert objective.id is not None
        with pytest.raises(validation.ValidationError) as exc_info:
            repo.update_status(objective.id, "en_progreso")
        assert exc_info.value.field == "estado"

    def test_update_status_nonexistent_objective_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            ObjectiveRepository(conn).update_status(999, "cumplido")

    def test_list_for_employee_orders_by_target_date_descending(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = ObjectiveRepository(conn)
        repo.create(employee_id, "Primero cronológicamente", date(2026, 1, 1))
        repo.create(employee_id, "Último cronológicamente", date(2026, 12, 31))
        titles = [o.title for o in repo.list_for_employee(employee_id)]
        assert titles == ["Último cronológicamente", "Primero cronológicamente"]

    def test_list_for_employee_excludes_other_employees(self, conn: sqlite3.Connection) -> None:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        emp_repo = EmployeeRepository(conn)
        ana = emp_repo.create(make_input(department_id=dept.id, email="ana@x.com"))
        bob = emp_repo.create(make_input(department_id=dept.id, email="bob@x.com"))
        assert ana.id is not None and bob.id is not None
        repo = ObjectiveRepository(conn)
        repo.create(ana.id, "Objetivo de Ana", date(2026, 6, 1))
        repo.create(bob.id, "Objetivo de Bob", date(2026, 6, 1))
        assert [o.title for o in repo.list_for_employee(ana.id)] == ["Objetivo de Ana"]

    def test_delete_removes_objective(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = ObjectiveRepository(conn)
        objective = repo.create(employee_id, "Objetivo", date(2026, 12, 31))
        assert objective.id is not None
        repo.delete(objective.id)
        with pytest.raises(NotFoundError):
            repo.get(objective.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            ObjectiveRepository(conn).delete(999)

    def test_deleting_employee_cascades_objectives(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = ObjectiveRepository(conn)
        objective = repo.create(employee_id, "Objetivo", date(2026, 12, 31))
        assert objective.id is not None
        EmployeeRepository(conn).delete(employee_id)
        with pytest.raises(NotFoundError):
            repo.get(objective.id)


class TestPerformanceReviewRepository:
    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        employee = EmployeeRepository(conn).create(make_input(department_id=dept.id))
        assert employee.id is not None
        return employee.id

    def test_create_and_get(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = PerformanceReviewRepository(conn)
        review = repo.create(employee_id, date(2026, 6, 15), "Buen trimestre.")
        assert review.id is not None
        assert repo.get(review.id).comments == "Buen trimestre."

    def test_create_empty_comments_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            PerformanceReviewRepository(conn).create(employee_id, date(2026, 6, 15), "   ")

    def test_create_nonexistent_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            PerformanceReviewRepository(conn).create(999, date(2026, 6, 15), "X")

    def test_list_for_employee_orders_by_review_date_descending(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = PerformanceReviewRepository(conn)
        repo.create(employee_id, date(2026, 1, 1), "Primera")
        repo.create(employee_id, date(2026, 6, 1), "Segunda")
        comments = [r.comments for r in repo.list_for_employee(employee_id)]
        assert comments == ["Segunda", "Primera"]

    def test_list_for_employee_excludes_other_employees(self, conn: sqlite3.Connection) -> None:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        emp_repo = EmployeeRepository(conn)
        ana = emp_repo.create(make_input(department_id=dept.id, email="ana@x.com"))
        bob = emp_repo.create(make_input(department_id=dept.id, email="bob@x.com"))
        assert ana.id is not None and bob.id is not None
        repo = PerformanceReviewRepository(conn)
        repo.create(ana.id, date(2026, 6, 1), "Nota de Ana")
        repo.create(bob.id, date(2026, 6, 1), "Nota de Bob")
        assert [r.comments for r in repo.list_for_employee(ana.id)] == ["Nota de Ana"]

    def test_delete_removes_review(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = PerformanceReviewRepository(conn)
        review = repo.create(employee_id, date(2026, 6, 15), "Nota")
        assert review.id is not None
        repo.delete(review.id)
        with pytest.raises(NotFoundError):
            repo.get(review.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            PerformanceReviewRepository(conn).delete(999)

    def test_deleting_employee_cascades_reviews(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = PerformanceReviewRepository(conn)
        review = repo.create(employee_id, date(2026, 6, 15), "Nota")
        assert review.id is not None
        EmployeeRepository(conn).delete(employee_id)
        with pytest.raises(NotFoundError):
            repo.get(review.id)


class TestAssignedEquipmentRepository:
    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        employee = EmployeeRepository(conn).create(make_input(department_id=dept.id))
        assert employee.id is not None
        return employee.id

    def test_create_and_get(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = AssignedEquipmentRepository(conn)
        equipment = repo.create(employee_id, "Portatil Dell XPS", date(2024, 1, 10))
        assert equipment.id is not None
        assert equipment.returned_date is None
        assert repo.get(equipment.id).description == "Portatil Dell XPS"

    def test_create_empty_description_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            AssignedEquipmentRepository(conn).create(employee_id, "   ", date(2024, 1, 10))

    def test_create_nonexistent_employee_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            AssignedEquipmentRepository(conn).create(999, "Portatil", date(2024, 1, 10))

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            AssignedEquipmentRepository(conn).get(999)

    def test_list_for_employee_orders_by_assigned_date_descending(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = AssignedEquipmentRepository(conn)
        repo.create(employee_id, "Primero cronológicamente", date(2024, 1, 1))
        repo.create(employee_id, "Último cronológicamente", date(2024, 12, 31))
        descriptions = [e.description for e in repo.list_for_employee(employee_id)]
        assert descriptions == ["Último cronológicamente", "Primero cronológicamente"]

    def test_list_for_employee_excludes_other_employees(self, conn: sqlite3.Connection) -> None:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        emp_repo = EmployeeRepository(conn)
        ana = emp_repo.create(make_input(department_id=dept.id, email="ana@x.com"))
        bob = emp_repo.create(make_input(department_id=dept.id, email="bob@x.com"))
        assert ana.id is not None and bob.id is not None
        repo = AssignedEquipmentRepository(conn)
        repo.create(ana.id, "Portatil de Ana", date(2024, 6, 1))
        repo.create(bob.id, "Portatil de Bob", date(2024, 6, 1))
        assert [e.description for e in repo.list_for_employee(ana.id)] == ["Portatil de Ana"]

    def test_mark_returned_persists(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = AssignedEquipmentRepository(conn)
        equipment = repo.create(employee_id, "Portatil", date(2024, 1, 10))
        assert equipment.id is not None
        updated = repo.mark_returned(equipment.id, date(2024, 2, 1))
        assert updated.returned_date == date(2024, 2, 1)
        assert repo.get(equipment.id).returned_date == date(2024, 2, 1)

    def test_mark_returned_already_returned_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = AssignedEquipmentRepository(conn)
        equipment = repo.create(employee_id, "Portatil", date(2024, 1, 10))
        assert equipment.id is not None
        repo.mark_returned(equipment.id, date(2024, 2, 1))
        with pytest.raises(RepositoryError):
            repo.mark_returned(equipment.id, date(2024, 2, 5))

    def test_mark_returned_before_assigned_date_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = AssignedEquipmentRepository(conn)
        equipment = repo.create(employee_id, "Portatil", date(2024, 1, 10))
        assert equipment.id is not None
        with pytest.raises(validation.ValidationError):
            repo.mark_returned(equipment.id, date(2024, 1, 1))

    def test_mark_returned_nonexistent_equipment_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            AssignedEquipmentRepository(conn).mark_returned(999, date(2024, 1, 1))

    def test_delete_removes_equipment(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = AssignedEquipmentRepository(conn)
        equipment = repo.create(employee_id, "Portatil", date(2024, 1, 10))
        assert equipment.id is not None
        repo.delete(equipment.id)
        with pytest.raises(NotFoundError):
            repo.get(equipment.id)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            AssignedEquipmentRepository(conn).delete(999)

    def test_deleting_employee_cascades_equipment(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = AssignedEquipmentRepository(conn)
        equipment = repo.create(employee_id, "Portatil", date(2024, 1, 10))
        assert equipment.id is not None
        EmployeeRepository(conn).delete(employee_id)
        with pytest.raises(NotFoundError):
            repo.get(equipment.id)
