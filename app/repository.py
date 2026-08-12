from __future__ import annotations

import calendar
import hashlib
import hmac
import secrets
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app import validation
from app.alerts import (
    Alert,
    DEFAULT_ALERT_WINDOW_DAYS,
    all_alerts,
    professional_category_minimum_salary_alerts,
    retention_review_alerts,
    training_expiry_alerts,
)
from app.database import DEFAULT_SS_EMPLOYEE_PCT, DEFAULT_SS_EMPLOYER_PCT, transaction
from app.db_engine import DbConnection
from app.document_templates import build_placeholder_values, render_document_template
from app.models import (
    AssignedEquipment,
    AuditLogEntry,
    Candidate,
    CollectiveAgreement,
    DailyShiftAssignment,
    DayType,
    Department,
    DepartmentClosure,
    DocumentTemplate,
    EmailConnection,
    Employee,
    EmployeeAbsence,
    DepartmentCostSummary,
    EmployeeDocument,
    EmployeeHistoryEntry,
    EmployeeDocumentSummary,
    EmployeeTraining,
    HolidayApplyResult,
    HolidayTemplate,
    HolidayTemplateDate,
    ITEpisode,
    MonthlyCostSummary,
    Objective,
    OnboardingChecklistStatus,
    OnboardingTask,
    PayrollRecord,
    PayrollSettings,
    PayrollSupplement,
    PerformanceReview,
    ProfessionalCategory,
    SeveranceSettlement,
    Shift,
    TimeClockEntry,
    User,
    WorkAccident,
)
from app.payroll import MonthlyPayroll, calculate_monthly_payroll
from app.severance import SeveranceCalculation


class RepositoryError(Exception):
    pass


class NotFoundError(RepositoryError):
    pass


class DuplicateError(RepositoryError):
    pass


class ReferenceInUseError(RepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class EmployeeInput:
    first_name: str
    last_name: str
    email: str
    phone: str
    position: str
    department_id: int
    salary: float
    hire_date: str
    shift_id: int | None = None
    bank_account: str = ""
    dependent_children: int = 0
    active: bool = True
    dni_nie: str = ""
    ss_number: str = ""
    contract_type: str = "Indefinido"
    contract_end_date: str = ""
    birth_date: str = ""
    next_medical_checkup_date: str = ""
    prl_training_date: str = ""
    manager_id: int | None = None
    head_of_department_id: int | None = None
    professional_category_id: int | None = None


@dataclass(frozen=True, slots=True)
class CandidateInput:
    first_name: str
    last_name: str
    email: str
    phone: str
    position: str
    department_id: int
    phase: str
    notes: str = ""


@dataclass(frozen=True, slots=True)
class _ValidatedCandidate:
    first_name: str
    last_name: str
    email: str
    phone: str
    position: str
    phase: str
    notes: str


@dataclass(frozen=True, slots=True)
class ShiftInput:
    department_id: int
    name: str
    start_time: str
    end_time: str
    days_of_week: frozenset[int]
    start_time_2: str | None = None
    end_time_2: str | None = None


@dataclass(frozen=True, slots=True)
class ProfessionalCategoryInput:
    collective_agreement_id: int
    name: str
    minimum_salary: float


@dataclass(frozen=True, slots=True)
class _ValidatedProfessionalCategory:
    name: str
    minimum_salary: float


@dataclass(frozen=True, slots=True)
class MarkRangeResult:
    marked: int
    skipped: int


@dataclass(frozen=True, slots=True)
class PayrollBulkGenerateResult:
    generated: int
    skipped: int


@dataclass(frozen=True, slots=True)
class _ValidatedEmployee:
    first_name: str
    last_name: str
    email: str
    phone: str
    position: str
    salary: float
    hire_date: date
    shift_id: int | None
    bank_account: str
    dependent_children: int
    dni_nie: str
    ss_number: str
    contract_type: str
    contract_end_date: date | None
    birth_date: date | None
    next_medical_checkup_date: date | None
    prl_training_date: date | None
    manager_id: int | None
    head_of_department_id: int | None
    professional_category_id: int | None


_DEFAULT_WORKING_WEEKDAYS = frozenset({1, 2, 3, 4, 5})

_EMPLOYEE_SUMMARY_COLUMNS = (
    "id, first_name, last_name, email, phone, position, department_id, "
    "shift_id, salary, hire_date, active, bank_account, dependent_children, "
    "dni_nie, ss_number, contract_type, contract_end_date, "
    "birth_date, next_medical_checkup_date, termination_date, termination_reason, "
    "anonymized, prl_training_date, manager_id, head_of_department_id, "
    "professional_category_id, NULL AS photo"
)


def _row_to_department(row: sqlite3.Row) -> Department:
    return Department(id=row["id"], name=row["name"])


def _row_to_collective_agreement(row: sqlite3.Row) -> CollectiveAgreement:
    return CollectiveAgreement(id=row["id"], name=row["name"])


def _row_to_professional_category(row: sqlite3.Row) -> ProfessionalCategory:
    return ProfessionalCategory(
        id=row["id"],
        collective_agreement_id=row["collective_agreement_id"],
        name=row["name"],
        minimum_salary=row["minimum_salary"],
    )


def _row_to_employee(row: sqlite3.Row) -> Employee:
    return Employee(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        email=row["email"],
        phone=row["phone"],
        position=row["position"],
        department_id=row["department_id"],
        shift_id=row["shift_id"],
        salary=row["salary"],
        hire_date=date.fromisoformat(row["hire_date"]),
        active=bool(row["active"]),
        bank_account=row["bank_account"],
        photo=row["photo"],
        dependent_children=row["dependent_children"],
        dni_nie=row["dni_nie"],
        ss_number=row["ss_number"],
        contract_type=row["contract_type"],
        contract_end_date=(
            date.fromisoformat(row["contract_end_date"])
            if row["contract_end_date"] is not None
            else None
        ),
        birth_date=(
            date.fromisoformat(row["birth_date"]) if row["birth_date"] is not None else None
        ),
        next_medical_checkup_date=(
            date.fromisoformat(row["next_medical_checkup_date"])
            if row["next_medical_checkup_date"] is not None
            else None
        ),
        termination_date=(
            date.fromisoformat(row["termination_date"])
            if row["termination_date"] is not None
            else None
        ),
        termination_reason=row["termination_reason"],
        anonymized=bool(row["anonymized"]),
        prl_training_date=(
            date.fromisoformat(row["prl_training_date"])
            if row["prl_training_date"] is not None
            else None
        ),
        manager_id=row["manager_id"],
        head_of_department_id=row["head_of_department_id"],
        professional_category_id=row["professional_category_id"],
    )


def _row_to_employee_history(row: sqlite3.Row) -> EmployeeHistoryEntry:
    return EmployeeHistoryEntry(
        id=row["id"],
        employee_id=row["employee_id"],
        position=row["position"],
        salary=row["salary"],
        effective_date=date.fromisoformat(row["effective_date"]),
        note=row["note"],
    )


def _record_employee_history(
    conn: DbConnection,
    employee_id: int,
    position: str,
    salary: float,
    effective_date: date,
    note: str,
) -> None:
    # Deliberately a plain execute(), not wrapped in its own transaction()
    # context: this always runs from inside EmployeeRepository.create()/
    # update()'s own transaction block, and nesting a second commit/rollback
    # boundary on the same connection would prematurely commit (or wrongly
    # scope a rollback for) the caller's still-in-progress transaction.
    conn.execute(
        "INSERT INTO employee_history (employee_id, position, salary, effective_date, note) "
        "VALUES (?, ?, ?, ?, ?)",
        (employee_id, position, salary, effective_date.isoformat(), note),
    )


def _row_to_shift(row: sqlite3.Row) -> Shift:
    return Shift(
        id=row["id"],
        department_id=row["department_id"],
        name=row["name"],
        start_time=row["start_time"],
        end_time=row["end_time"],
        days_of_week=_parse_days_of_week(row["days_of_week"]),
        start_time_2=row["start_time_2"],
        end_time_2=row["end_time_2"],
    )


def _row_to_daily_assignment(row: sqlite3.Row) -> DailyShiftAssignment:
    return DailyShiftAssignment(
        id=row["id"],
        employee_id=row["employee_id"],
        assignment_date=date.fromisoformat(row["assignment_date"]),
        shift_id=row["shift_id"],
    )


def _row_to_day_type(row: sqlite3.Row) -> DayType:
    return DayType(
        id=row["id"],
        name=row["name"],
        color=row["color"],
        is_vacation=bool(row["is_vacation"]),
    )


def _row_to_department_closure(row: sqlite3.Row) -> DepartmentClosure:
    return DepartmentClosure(
        id=row["id"],
        department_id=row["department_id"],
        closure_date=date.fromisoformat(row["closure_date"]),
        day_type_id=row["day_type_id"],
        note=row["note"],
    )


def _row_to_holiday_template(row: sqlite3.Row) -> HolidayTemplate:
    return HolidayTemplate(
        id=row["id"], name=row["name"], created_at=date.fromisoformat(row["created_at"])
    )


def _row_to_holiday_template_date(row: sqlite3.Row) -> HolidayTemplateDate:
    return HolidayTemplateDate(
        id=row["id"],
        template_id=row["template_id"],
        holiday_date=date.fromisoformat(row["holiday_date"]),
        label=row["label"],
    )


def _row_to_employee_absence(row: sqlite3.Row) -> EmployeeAbsence:
    return EmployeeAbsence(
        id=row["id"],
        employee_id=row["employee_id"],
        absence_date=date.fromisoformat(row["absence_date"]),
        day_type_id=row["day_type_id"],
        note=row["note"],
        status=row["status"],
    )


def _format_days_of_week(days: frozenset[int]) -> str:
    return ",".join(str(day) for day in sorted(days))


def _parse_days_of_week(raw: str) -> frozenset[int]:
    return frozenset(int(part) for part in raw.split(",") if part)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


class DepartmentRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(self, name: str) -> Department:
        clean_name = validation.validate_required_text(name, "departamento")
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    "INSERT INTO departments (name) VALUES (?)", (clean_name,)
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"ya existe un departamento llamado '{clean_name}'") from exc
        return Department(id=cursor.lastrowid, name=clean_name)

    def get(self, department_id: int) -> Department:
        row = self._conn.execute(
            "SELECT id, name FROM departments WHERE id = ?", (department_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el departamento con id {department_id}")
        return _row_to_department(row)

    def list_all(self) -> list[Department]:
        rows = self._conn.execute("SELECT id, name FROM departments ORDER BY name").fetchall()
        return [_row_to_department(row) for row in rows]

    def delete(self, department_id: int) -> None:
        # Comprobado explícitamente ANTES de intentar borrar (en vez de solo
        # atrapar el IntegrityError genérico de la FK) porque, desde que
        # candidates también referencia department_id con ON DELETE
        # RESTRICT, "FOREIGN KEY constraint failed" por sí solo ya no dice
        # si el bloqueo es por empleados, por candidatos, o ambos -- SQLite
        # no incluye la tabla/columna en ese mensaje (verificado
        # directamente, no asumido), así que un mensaje genérico aquí
        # habría podido acusar de "empleados asignados" a un departamento
        # que en realidad solo tiene candidatos en proceso.
        has_employees = (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE department_id = ? LIMIT 1", (department_id,)
            ).fetchone()
            is not None
        )
        has_candidates = (
            self._conn.execute(
                "SELECT 1 FROM candidates WHERE department_id = ? LIMIT 1", (department_id,)
            ).fetchone()
            is not None
        )
        # users.department_id es ON DELETE SET NULL, no RESTRICT (un usuario
        # no debe desaparecer solo porque se reorganice su departamento) --
        # pero eso significa que el IntegrityError genérico de más abajo
        # NUNCA salta para este caso: hay que comprobarlo explícitamente
        # aquí, igual que empleados/candidatos, o un encargado se queda con
        # department_id=NULL tras el borrado -- el mismo valor que usa un
        # administrador para "sin restricción" (ver MainWindow.__init__),
        # concediéndole sin querer acceso a todos los departamentos.
        has_users = (
            self._conn.execute(
                "SELECT 1 FROM users WHERE department_id = ? LIMIT 1", (department_id,)
            ).fetchone()
            is not None
        )
        blockers: list[str] = []
        if has_employees:
            blockers.append("empleados")
        if has_candidates:
            blockers.append("candidatos")
        if has_users:
            blockers.append("usuarios (encargados)")
        if blockers:
            if len(blockers) == 1:
                blockers_text = blockers[0]
            else:
                blockers_text = f"{', '.join(blockers[:-1])} y {blockers[-1]}"
            raise ReferenceInUseError(
                f"no se puede eliminar: hay {blockers_text} asignados a este departamento"
            )
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    "DELETE FROM departments WHERE id = ?", (department_id,)
                )
        except sqlite3.IntegrityError as exc:
            # Red de seguridad por si en el futuro se añade otra referencia
            # RESTRICT a departments sin actualizar las comprobaciones de
            # arriba: no se pierde la protección, solo el detalle del
            # mensaje.
            raise ReferenceInUseError(
                "no se puede eliminar: hay datos que todavía hacen referencia a este departamento"
            ) from exc
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el departamento con id {department_id}")


class CollectiveAgreementRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(self, name: str) -> CollectiveAgreement:
        clean_name = validation.validate_required_text(name, "convenio")
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    "INSERT INTO collective_agreements (name) VALUES (?)", (clean_name,)
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"ya existe un convenio llamado '{clean_name}'") from exc
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def update(self, agreement_id: int, name: str) -> CollectiveAgreement:
        self.get(agreement_id)
        clean_name = validation.validate_required_text(name, "convenio")
        try:
            with transaction(self._conn):
                self._conn.execute(
                    "UPDATE collective_agreements SET name = ? WHERE id = ?",
                    (clean_name, agreement_id),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"ya existe un convenio llamado '{clean_name}'") from exc
        return self.get(agreement_id)

    def get(self, agreement_id: int) -> CollectiveAgreement:
        row = self._conn.execute(
            "SELECT id, name FROM collective_agreements WHERE id = ?", (agreement_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el convenio con id {agreement_id}")
        return _row_to_collective_agreement(row)

    def list_all(self) -> list[CollectiveAgreement]:
        rows = self._conn.execute(
            "SELECT id, name FROM collective_agreements ORDER BY name"
        ).fetchall()
        return [_row_to_collective_agreement(row) for row in rows]

    def delete(self, agreement_id: int) -> None:
        # A diferencia de departments/shifts (bloqueados explícitamente si
        # tienen empleados/turnos en uso), aquí no hace falta ninguna
        # comprobación previa: professional_categories cuelga de este
        # convenio con ON DELETE CASCADE, y a su vez employees.
        # professional_category_id es ON DELETE SET NULL sobre esas
        # categorías -- el mismo encadenamiento CASCADE -> SET NULL que
        # employees.shift_id, verificado empíricamente antes de escribir
        # este método. Nada aquí puede lanzar IntegrityError.
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM collective_agreements WHERE id = ?", (agreement_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el convenio con id {agreement_id}")


class ProfessionalCategoryRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def _validate(self, data: ProfessionalCategoryInput) -> _ValidatedProfessionalCategory:
        name = validation.validate_required_text(data.name, "categoria")
        minimum_salary = validation.validate_minimum_salary(data.minimum_salary)
        agreement_exists = self._conn.execute(
            "SELECT 1 FROM collective_agreements WHERE id = ?",
            (data.collective_agreement_id,),
        ).fetchone()
        if agreement_exists is None:
            raise NotFoundError(
                f"no existe el convenio con id {data.collective_agreement_id}"
            )
        return _ValidatedProfessionalCategory(name=name, minimum_salary=minimum_salary)

    def create(self, data: ProfessionalCategoryInput) -> ProfessionalCategory:
        v = self._validate(data)
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    "INSERT INTO professional_categories "
                    "(collective_agreement_id, name, minimum_salary) VALUES (?, ?, ?)",
                    (data.collective_agreement_id, v.name, v.minimum_salary),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(
                f"ya existe una categoría llamada '{v.name}' en este convenio"
            ) from exc
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def update(self, category_id: int, data: ProfessionalCategoryInput) -> ProfessionalCategory:
        self.get(category_id)
        v = self._validate(data)
        try:
            with transaction(self._conn):
                self._conn.execute(
                    "UPDATE professional_categories "
                    "SET collective_agreement_id = ?, name = ?, minimum_salary = ? WHERE id = ?",
                    (data.collective_agreement_id, v.name, v.minimum_salary, category_id),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(
                f"ya existe una categoría llamada '{v.name}' en este convenio"
            ) from exc
        return self.get(category_id)

    def get(self, category_id: int) -> ProfessionalCategory:
        row = self._conn.execute(
            "SELECT * FROM professional_categories WHERE id = ?", (category_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe la categoría profesional con id {category_id}")
        return _row_to_professional_category(row)

    def list_all(self) -> list[ProfessionalCategory]:
        rows = self._conn.execute("SELECT * FROM professional_categories ORDER BY name").fetchall()
        return [_row_to_professional_category(row) for row in rows]

    def list_for_agreement(self, collective_agreement_id: int) -> list[ProfessionalCategory]:
        rows = self._conn.execute(
            "SELECT * FROM professional_categories WHERE collective_agreement_id = ? ORDER BY name",
            (collective_agreement_id,),
        ).fetchall()
        return [_row_to_professional_category(row) for row in rows]

    def delete(self, category_id: int) -> None:
        # employees.professional_category_id es ON DELETE SET NULL (igual
        # que employees.shift_id): borrar una categoría en uso nunca lanza
        # IntegrityError, simplemente desasigna a quien la tuviera.
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM professional_categories WHERE id = ?", (category_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe la categoría profesional con id {category_id}")


class EmployeeRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def _validate(
        self, data: EmployeeInput, *, employee_id: int | None = None
    ) -> _ValidatedEmployee:
        first_name = validation.validate_required_text(data.first_name, "nombre")
        last_name = validation.validate_required_text(data.last_name, "apellido")
        email = validation.validate_email(data.email)
        phone = validation.validate_phone(data.phone)
        position = validation.validate_required_text(data.position, "puesto")
        salary = validation.validate_salary(data.salary)
        hire_date = validation.validate_hire_date(data.hire_date)
        bank_account = validation.validate_iban(data.bank_account)
        dependent_children = validation.validate_dependent_children(data.dependent_children)
        dni_nie = validation.validate_dni_nie(data.dni_nie)
        ss_number = validation.validate_ss_number(data.ss_number)
        contract_type = validation.validate_contract_type(data.contract_type)
        contract_end_date = validation.validate_contract_end_date(
            data.contract_end_date, contract_type, hire_date
        )
        birth_date = validation.validate_birth_date(data.birth_date, hire_date)
        next_medical_checkup_date = validation.validate_next_medical_checkup_date(
            data.next_medical_checkup_date
        )
        prl_training_date = validation.validate_prl_training_date(
            data.prl_training_date, hire_date
        )
        department_exists = self._conn.execute(
            "SELECT 1 FROM departments WHERE id = ?", (data.department_id,)
        ).fetchone()
        if department_exists is None:
            raise NotFoundError(f"no existe el departamento con id {data.department_id}")

        shift_id = data.shift_id
        if shift_id is not None:
            shift_row = self._conn.execute(
                "SELECT department_id FROM shifts WHERE id = ?", (shift_id,)
            ).fetchone()
            if shift_row is None:
                raise NotFoundError(f"no existe el turno con id {shift_id}")
            if shift_row["department_id"] != data.department_id:
                raise validation.ValidationError(
                    "turno", "el turno seleccionado no pertenece al departamento elegido"
                )

        manager_id = data.manager_id
        if manager_id is not None:
            manager_row = self._conn.execute(
                "SELECT department_id, active FROM employees WHERE id = ?", (manager_id,)
            ).fetchone()
            if manager_row is None:
                raise NotFoundError(f"no existe el empleado con id {manager_id}")
            if manager_row["department_id"] != data.department_id:
                raise validation.ValidationError(
                    "supervisor", "el supervisor directo debe pertenecer al mismo departamento"
                )
            if not bool(manager_row["active"]):
                raise validation.ValidationError(
                    "supervisor", "no se puede asignar como supervisor a un empleado de baja"
                )
            if employee_id is not None and self._would_create_management_cycle(
                employee_id, manager_id
            ):
                raise validation.ValidationError(
                    "supervisor", "esa asignación crearía un ciclo en la jerarquía de supervisión"
                )

        head_of_department_id = data.head_of_department_id
        if head_of_department_id is not None:
            head_department_exists = self._conn.execute(
                "SELECT 1 FROM departments WHERE id = ?", (head_of_department_id,)
            ).fetchone()
            if head_department_exists is None:
                raise NotFoundError(
                    f"no existe el departamento con id {head_of_department_id}"
                )

        professional_category_id = data.professional_category_id
        if professional_category_id is not None:
            category_exists = self._conn.execute(
                "SELECT 1 FROM professional_categories WHERE id = ?",
                (professional_category_id,),
            ).fetchone()
            if category_exists is None:
                raise NotFoundError(
                    f"no existe la categoría profesional con id {professional_category_id}"
                )

        return _ValidatedEmployee(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            position=position,
            salary=salary,
            hire_date=hire_date,
            shift_id=shift_id,
            bank_account=bank_account,
            dependent_children=dependent_children,
            dni_nie=dni_nie,
            ss_number=ss_number,
            contract_type=contract_type,
            contract_end_date=contract_end_date,
            birth_date=birth_date,
            next_medical_checkup_date=next_medical_checkup_date,
            prl_training_date=prl_training_date,
            manager_id=manager_id,
            head_of_department_id=head_of_department_id,
            professional_category_id=professional_category_id,
        )

    def _would_create_management_cycle(self, employee_id: int, proposed_manager_id: int) -> bool:
        """True si asignar `proposed_manager_id` como supervisor de
        `employee_id` cerraría un ciclo -- directo (se auto-asigna) o
        indirecto (a través de una cadena de supervisores ya existente:
        A supervisa a B, se intenta hacer que B supervise a A). Recorre
        hacia arriba desde el manager propuesto usando la jerarquía YA
        guardada; `visited` corta el recorrido si alguna vez hubiera un
        ciclo previo en los datos, para no arriesgar un bucle infinito por
        un caso que esta misma comprobación debería impedir que ocurra."""
        manager_by_id = {
            row["id"]: row["manager_id"]
            for row in self._conn.execute("SELECT id, manager_id FROM employees").fetchall()
        }
        current: int | None = proposed_manager_id
        visited: set[int] = set()
        while current is not None:
            if current == employee_id:
                return True
            if current in visited:
                break
            visited.add(current)
            current = manager_by_id.get(current)
        return False

    def _duplicate_error(self, exc: sqlite3.IntegrityError, v: _ValidatedEmployee) -> DuplicateError:
        if "dni_nie" in str(exc):
            return DuplicateError(f"ya existe un empleado con el DNI/NIE '{v.dni_nie}'")
        if "ss_number" in str(exc):
            return DuplicateError(
                f"ya existe un empleado con el número de Seguridad Social '{v.ss_number}'"
            )
        return DuplicateError(f"ya existe un empleado con el email '{v.email}'")

    def create(self, data: EmployeeInput) -> Employee:
        v = self._validate(data)
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    """
                    INSERT INTO employees
                        (first_name, last_name, email, phone, position, department_id,
                         shift_id, salary, hire_date, active, bank_account, dependent_children,
                         dni_nie, ss_number, contract_type, contract_end_date,
                         birth_date, next_medical_checkup_date, prl_training_date, manager_id,
                         head_of_department_id, professional_category_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        v.first_name,
                        v.last_name,
                        v.email,
                        v.phone,
                        v.position,
                        data.department_id,
                        v.shift_id,
                        v.salary,
                        v.hire_date.isoformat(),
                        int(data.active),
                        v.bank_account,
                        v.dependent_children,
                        v.dni_nie or None,
                        v.ss_number or None,
                        v.contract_type,
                        v.contract_end_date.isoformat() if v.contract_end_date else None,
                        v.birth_date.isoformat() if v.birth_date else None,
                        v.next_medical_checkup_date.isoformat()
                        if v.next_medical_checkup_date
                        else None,
                        v.prl_training_date.isoformat() if v.prl_training_date else None,
                        v.manager_id,
                        v.head_of_department_id,
                        v.professional_category_id,
                    ),
                )
                employee_id = cursor.lastrowid
                assert employee_id is not None
                _record_employee_history(
                    self._conn, employee_id, v.position, v.salary, v.hire_date, "Alta inicial"
                )
        except sqlite3.IntegrityError as exc:
            raise self._duplicate_error(exc, v) from exc
        return self.get(employee_id)

    def update(self, employee_id: int, data: EmployeeInput) -> Employee:
        existing = self.get(employee_id)
        if existing.anonymized:
            # Sin este guard, "Guardar cambios" podía rellenar de nuevo
            # nombre/email/DNI/IBAN/etc. sobre un empleado ya anonimizado,
            # restaurando en la práctica todo lo que anonymize() acababa de
            # borrar -- mientras el campo `anonymized` se quedaba en True,
            # dando una falsa sensación de cumplimiento. anonymize() es
            # deliberadamente irreversible (ver su propio docstring); esto
            # cierra el único camino que lo deshacía sin querer.
            raise RepositoryError(
                "no se pueden modificar los datos de un empleado ya anonimizado"
            )
        v = self._validate(data, employee_id=employee_id)
        try:
            with transaction(self._conn):
                self._conn.execute(
                    """
                    UPDATE employees
                    SET first_name = ?, last_name = ?, email = ?, phone = ?, position = ?,
                        department_id = ?, shift_id = ?, salary = ?, hire_date = ?, active = ?,
                        bank_account = ?, dependent_children = ?, dni_nie = ?, ss_number = ?,
                        contract_type = ?, contract_end_date = ?, birth_date = ?,
                        next_medical_checkup_date = ?, prl_training_date = ?, manager_id = ?,
                        head_of_department_id = ?, professional_category_id = ?
                    WHERE id = ?
                    """,
                    (
                        v.first_name,
                        v.last_name,
                        v.email,
                        v.phone,
                        v.position,
                        data.department_id,
                        v.shift_id,
                        v.salary,
                        v.hire_date.isoformat(),
                        int(data.active),
                        v.bank_account,
                        v.dependent_children,
                        v.dni_nie or None,
                        v.ss_number or None,
                        v.contract_type,
                        v.contract_end_date.isoformat() if v.contract_end_date else None,
                        v.birth_date.isoformat() if v.birth_date else None,
                        v.next_medical_checkup_date.isoformat()
                        if v.next_medical_checkup_date
                        else None,
                        v.prl_training_date.isoformat() if v.prl_training_date else None,
                        v.manager_id,
                        v.head_of_department_id,
                        v.professional_category_id,
                        employee_id,
                    ),
                )
                if v.position != existing.position or v.salary != existing.salary:
                    _record_employee_history(
                        self._conn, employee_id, v.position, v.salary, date.today(), ""
                    )
        except sqlite3.IntegrityError as exc:
            raise self._duplicate_error(exc, v) from exc
        return self.get(employee_id)

    def set_photo(self, employee_id: int, photo: bytes | None) -> None:
        existing = self.get(employee_id)
        if existing.anonymized:
            raise RepositoryError(
                "no se pueden modificar los datos de un empleado ya anonimizado"
            )
        with transaction(self._conn):
            cursor = self._conn.execute(
                "UPDATE employees SET photo = ? WHERE id = ?", (photo, employee_id)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el empleado con id {employee_id}")

    def terminate(self, employee_id: int, termination_date: str, termination_reason: str) -> Employee:
        """Da de baja al empleado: motivo y fecha son obligatorios (a
        diferencia de `active` en EmployeeInput/update(), que sigue
        pudiendo cambiarse sin ellos para no romper compatibilidad hacia
        atrás) -- es el único camino que la ficha usa para pasar a inactivo,
        precisamente para que "inactivo" nunca quede sin fecha ni motivo
        registrados. Método dedicado, no una rama más de update(), por la
        misma razón que set_photo() es aparte: una mutación específica con
        sus propias reglas, no un campo más del formulario general."""
        existing = self.get(employee_id)
        if not existing.active:
            raise RepositoryError("el empleado ya está de baja")
        reason = validation.validate_termination_reason(termination_reason)
        parsed_date = validation.validate_termination_date(termination_date, existing.hire_date)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE employees SET active = 0, termination_date = ?, termination_reason = ? "
                "WHERE id = ?",
                (parsed_date.isoformat(), reason, employee_id),
            )
        return self.get(employee_id)

    def reactivate(self, employee_id: int) -> Employee:
        existing = self.get(employee_id)
        if existing.active:
            raise RepositoryError("el empleado ya está activo")
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE employees SET active = 1, termination_date = NULL, "
                "termination_reason = NULL WHERE id = ?",
                (employee_id,),
            )
        return self.get(employee_id)

    def anonymize(self, employee_id: int) -> Employee:
        """Anonimiza los datos identificativos de un empleado dado de baja,
        conservando el esqueleto estructural/financiero (puesto, departamento,
        salario, fechas laborales, tipo de contrato) que la normativa
        fiscal/laboral obliga a conservar durante varios años -- ver
        AppSettingsRepository.get_data_retention_years(). No es un borrado: es
        la vía del art. 17.3 RGPD para cuando el derecho de supresión choca
        con esa obligación de conservación. delete() sigue existiendo aparte
        para los casos sin esa obligación (p. ej. un alta duplicada por
        error). birth_date y next_medical_checkup_date también se borran (a
        diferencia de hire_date/termination_date/salary, no hay obligación
        legal de conservar el cumpleaños exacto ni una cita médica futura de
        alguien que ya no trabaja aquí, y combinado con puesto/departamento
        en una empresa pequeña podría reidentificar a la persona)."""
        existing = self.get(employee_id)
        if existing.active:
            raise RepositoryError(
                "el empleado debe estar de baja antes de anonimizar sus datos"
            )
        if existing.anonymized:
            raise RepositoryError("los datos de este empleado ya están anonimizados")
        with transaction(self._conn):
            self._conn.execute(
                """
                UPDATE employees SET
                    first_name = 'Anonimizado', last_name = ?, email = ?,
                    phone = '', bank_account = '', photo = NULL,
                    dni_nie = NULL, ss_number = NULL,
                    birth_date = NULL, next_medical_checkup_date = NULL,
                    anonymized = 1
                WHERE id = ?
                """,
                (f"#{employee_id}", f"anonimizado-{employee_id}@baja.local", employee_id),
            )
            self._conn.execute(
                "DELETE FROM employee_documents WHERE employee_id = ?", (employee_id,)
            )
        return self.get(employee_id)

    def get(self, employee_id: int) -> Employee:
        row = self._conn.execute(
            "SELECT * FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        return _row_to_employee(row)

    def delete(self, employee_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el empleado con id {employee_id}")

    def has_self_service_pin(self, employee_id: int) -> bool:
        row = self._conn.execute(
            "SELECT self_service_pin_hash FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        return row["self_service_pin_hash"] is not None

    def set_self_service_pin(self, employee_id: int, pin: str) -> None:
        self.get(employee_id)
        clean_pin = validation.validate_access_pin(pin)
        salt = secrets.token_bytes(16)
        pin_hash = _hash_password(clean_pin, salt)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE employees SET self_service_pin_hash = ?, self_service_pin_salt = ? "
                "WHERE id = ?",
                (pin_hash.hex(), salt.hex(), employee_id),
            )

    def clear_self_service_pin(self, employee_id: int) -> None:
        self.get(employee_id)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE employees SET self_service_pin_hash = NULL, self_service_pin_salt = NULL "
                "WHERE id = ?",
                (employee_id,),
            )

    def authenticate_self_service(self, email: str, pin: str) -> Employee | None:
        """Ni el email ni el PIN se validan con validate_email/
        validate_access_pin aquí -- igual que UserRepository.authenticate(),
        un intento de acceso es una comparación contra datos existentes, no
        una creación: cualquier entrada simplemente no encuentra
        coincidencia en vez de lanzar un error distinto que revele por qué
        falló. Solo empleados ACTIVOS con un PIN ya establecido pueden
        autenticarse: alguien de baja no debe poder seguir consultando sus
        propios datos indefinidamente, y sin self_service_pin_hash guardado
        (el valor por defecto -- nadie lo ha establecido todavía) no hay
        nada contra lo que comparar."""
        # Sin COLLATE NOCASE aquí a propósito: employees.email ya es
        # case-insensitive a nivel de esquema (COLLATE NOCASE en SQLite,
        # CITEXT en Postgres, ver database.py) -- repetirlo en la consulta
        # es redundante en SQLite e inválido en Postgres (no existe una
        # colación "nocase" ahí).
        row = self._conn.execute(
            "SELECT * FROM employees WHERE email = ? AND active = 1",
            (email.strip(),),
        ).fetchone()
        if row is None or row["self_service_pin_hash"] is None:
            return None
        expected_hash = bytes.fromhex(row["self_service_pin_hash"])
        salt = bytes.fromhex(row["self_service_pin_salt"])
        actual_hash = _hash_password(pin, salt)
        if not hmac.compare_digest(actual_hash, expected_hash):
            return None
        return _row_to_employee(row)

    def search(
        self,
        query: str = "",
        department_id: int | None = None,
        active_only: bool | None = None,
    ) -> list[Employee]:
        clauses: list[str] = []
        params: list[object] = []

        clean_query = query.strip()
        if clean_query:
            # LOWER() en ambos lados: LIKE es case-insensitive por defecto en
            # SQLite pero case-sensitive en PostgreSQL -- sin esto, la
            # búsqueda devolvería menos resultados contra un servidor
            # PostgreSQL que contra SQLite. LOWER() no toca '%'/'_'/'\\', así
            # que no interfiere con el escapado de _escape_like().
            clauses.append(
                "(LOWER(first_name || ' ' || last_name) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(email) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(position) LIKE LOWER(?) ESCAPE '\\')"
            )
            like_pattern = f"%{_escape_like(clean_query)}%"
            params.extend([like_pattern, like_pattern, like_pattern])

        if department_id is not None:
            clauses.append("department_id = ?")
            params.append(department_id)

        if active_only is not None:
            clauses.append("active = ?")
            params.append(int(active_only))

        # Deliberately excludes the (potentially large) photo BLOB: list/search
        # results are for the Treeview, which never renders photos. Fetching every
        # employee's photo bytes on each keystroke would be slow and pointless —
        # use get(employee_id) to load the full record, photo included, for one employee.
        sql = f"SELECT {_EMPLOYEE_SUMMARY_COLUMNS} FROM employees"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY last_name, first_name"

        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_employee(row) for row in rows]

    def list_all(self) -> list[Employee]:
        return self.search()


class EmployeeHistoryRepository:
    """Solo lectura desde fuera: las entradas se registran automáticamente
    desde EmployeeRepository.create()/update() (vía _record_employee_history,
    en la misma transacción), no hay un create()/update() público aquí --
    el historial es un efecto secundario de editar al empleado, no una
    acción independiente que alguien deba recordar hacer aparte."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def list_for_employee(self, employee_id: int) -> list[EmployeeHistoryEntry]:
        rows = self._conn.execute(
            "SELECT * FROM employee_history WHERE employee_id = ? "
            "ORDER BY effective_date DESC, id DESC",
            (employee_id,),
        ).fetchall()
        return [_row_to_employee_history(row) for row in rows]


def _row_to_severance_settlement(row: sqlite3.Row) -> SeveranceSettlement:
    return SeveranceSettlement(
        id=row["id"],
        employee_id=row["employee_id"],
        termination_date=date.fromisoformat(row["termination_date"]),
        termination_reason=row["termination_reason"],
        hire_date=date.fromisoformat(row["hire_date"]),
        annual_gross_salary=row["annual_gross_salary"],
        annual_vacation_days=row["annual_vacation_days"],
        vacation_days_used_this_year=row["vacation_days_used_this_year"],
        vacation_days_pending=row["vacation_days_pending"],
        vacation_amount=row["vacation_amount"],
        extra_payment_months_accrued=row["extra_payment_months_accrued"],
        extra_payment_amount=row["extra_payment_amount"],
        total_amount=row["total_amount"],
        generated_at=datetime.fromisoformat(row["generated_at"]),
    )


class SeveranceSettlementRepository:
    """Registro histórico del finiquito calculado al dar de baja a un
    empleado -- solo inserta, nunca actualiza ni sustituye una fila ya
    guardada (mismo criterio que EmployeeHistoryRepository, no el de
    PayrollRecordRepository.generate(), que sí sustituye: una baja no es
    un hecho recurrente y corregible mes a mes como una nómina, así que no
    hay un "regenerar" que tenga sentido aquí -- una corrección se guarda
    como una entrada nueva, dejando constancia de ambas)."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(
        self,
        employee_id: int,
        termination_date: date,
        termination_reason: str,
        hire_date: date,
        annual_gross_salary: float,
        annual_vacation_days: float,
        vacation_days_used_this_year: int,
        calculation: SeveranceCalculation,
    ) -> SeveranceSettlement:
        generated_at = datetime.now().replace(microsecond=0)
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO severance_settlements (
                    employee_id, termination_date, termination_reason, hire_date,
                    annual_gross_salary, annual_vacation_days, vacation_days_used_this_year,
                    vacation_days_pending, vacation_amount, extra_payment_months_accrued,
                    extra_payment_amount, total_amount, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    termination_date.isoformat(),
                    termination_reason,
                    hire_date.isoformat(),
                    annual_gross_salary,
                    annual_vacation_days,
                    vacation_days_used_this_year,
                    calculation.vacation_days_pending,
                    calculation.vacation_amount,
                    calculation.extra_payment_months_accrued,
                    calculation.extra_payment_amount,
                    calculation.total_amount,
                    generated_at.isoformat(timespec="seconds"),
                ),
            )
        settlement_id = cursor.lastrowid
        assert settlement_id is not None
        return self.get(settlement_id)

    def get(self, settlement_id: int) -> SeveranceSettlement:
        row = self._conn.execute(
            "SELECT * FROM severance_settlements WHERE id = ?", (settlement_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el finiquito con id {settlement_id}")
        return _row_to_severance_settlement(row)

    def list_for_employee(self, employee_id: int) -> list[SeveranceSettlement]:
        rows = self._conn.execute(
            "SELECT * FROM severance_settlements WHERE employee_id = ? "
            "ORDER BY generated_at DESC, id DESC",
            (employee_id,),
        ).fetchall()
        return [_row_to_severance_settlement(row) for row in rows]


def _row_to_work_accident(row: sqlite3.Row) -> WorkAccident:
    return WorkAccident(
        id=row["id"],
        employee_id=row["employee_id"],
        accident_date=date.fromisoformat(row["accident_date"]),
        severity=row["severity"],
        description=row["description"],
        caused_leave=bool(row["caused_leave"]),
        reported_to_authority=bool(row["reported_to_authority"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class WorkAccidentRepository:
    """El registro mínimo de accidentes de trabajo que exige la normativa de
    PRL -- no evaluación de riesgos (eso lo lleva normalmente un servicio de
    prevención externo), solo constancia de que un accidente ocurrió y de si
    se han cumplido los pasos básicos (baja médica, notificación a la
    autoridad laboral). Permite crear y eliminar (una entrada mal
    introducida por error), pero no editar en el sitio -- igual que
    EmployeeDocumentRepository/PayrollSupplementRepository, no como
    SeveranceSettlementRepository/EmployeeHistoryRepository, que son
    estrictamente de solo-inserción: un accidente es un hecho registrado
    por un humano que puede necesitar corregirse, no un cálculo derivado."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(
        self,
        employee_id: int,
        accident_date: date,
        severity: str,
        description: str,
        caused_leave: bool,
        reported_to_authority: bool,
    ) -> WorkAccident:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        created_at = datetime.now().replace(microsecond=0)
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO work_accidents (
                    employee_id, accident_date, severity, description,
                    caused_leave, reported_to_authority, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    accident_date.isoformat(),
                    severity,
                    description,
                    int(caused_leave),
                    int(reported_to_authority),
                    created_at.isoformat(timespec="seconds"),
                ),
            )
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def get(self, accident_id: int) -> WorkAccident:
        row = self._conn.execute(
            "SELECT * FROM work_accidents WHERE id = ?", (accident_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el accidente con id {accident_id}")
        return _row_to_work_accident(row)

    def list_for_employee(self, employee_id: int) -> list[WorkAccident]:
        rows = self._conn.execute(
            "SELECT * FROM work_accidents WHERE employee_id = ? ORDER BY accident_date DESC, id DESC",
            (employee_id,),
        ).fetchall()
        return [_row_to_work_accident(row) for row in rows]

    def delete(self, accident_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM work_accidents WHERE id = ?", (accident_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el accidente con id {accident_id}")


def _row_to_employee_training(row: sqlite3.Row) -> EmployeeTraining:
    return EmployeeTraining(
        id=row["id"],
        employee_id=row["employee_id"],
        name=row["name"],
        completion_date=date.fromisoformat(row["completion_date"]),
        expiration_date=(
            date.fromisoformat(row["expiration_date"])
            if row["expiration_date"] is not None
            else None
        ),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class EmployeeTrainingRepository:
    """Cursos de formación y certificaciones -- solo creación/eliminación,
    igual que WorkAccidentRepository (un hecho registrado por un humano
    que puede necesitar corregirse, no un cálculo derivado ni un
    histórico de solo-inserción)."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(
        self,
        employee_id: int,
        name: str,
        completion_date: date,
        expiration_date: date | None,
    ) -> EmployeeTraining:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        clean_name = validation.validate_required_text(name, "nombre")
        if expiration_date is not None and expiration_date <= completion_date:
            raise validation.ValidationError(
                "fecha_caducidad", "debe ser posterior a la fecha de finalización"
            )
        created_at = datetime.now().replace(microsecond=0)
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO employee_trainings
                    (employee_id, name, completion_date, expiration_date, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    clean_name,
                    completion_date.isoformat(),
                    expiration_date.isoformat() if expiration_date is not None else None,
                    created_at.isoformat(timespec="seconds"),
                ),
            )
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def get(self, training_id: int) -> EmployeeTraining:
        row = self._conn.execute(
            "SELECT * FROM employee_trainings WHERE id = ?", (training_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el registro de formación con id {training_id}")
        return _row_to_employee_training(row)

    def list_for_employee(self, employee_id: int) -> list[EmployeeTraining]:
        rows = self._conn.execute(
            "SELECT * FROM employee_trainings WHERE employee_id = ? "
            "ORDER BY completion_date DESC, id DESC",
            (employee_id,),
        ).fetchall()
        return [_row_to_employee_training(row) for row in rows]

    def list_all(self) -> list[EmployeeTraining]:
        """Sin acotar por empleado ni departamento -- pensado para
        training_expiry_alerts(), que necesita cada certificación con
        fecha de caducidad de toda la empresa a la vez; el propio
        `employees` que recibe esa función ya viene acotado por rol/
        departamento desde el llamante, así que una certificación de un
        empleado fuera de ese conjunto sencillamente no encuentra
        coincidencia y no genera alerta."""
        rows = self._conn.execute("SELECT * FROM employee_trainings").fetchall()
        return [_row_to_employee_training(row) for row in rows]

    def delete(self, training_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM employee_trainings WHERE id = ?", (training_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el registro de formación con id {training_id}")


def _row_to_objective(row: sqlite3.Row) -> Objective:
    return Objective(
        id=row["id"],
        employee_id=row["employee_id"],
        title=row["title"],
        target_date=date.fromisoformat(row["target_date"]),
        status=row["status"],
        notes=row["notes"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class ObjectiveRepository:
    """Objetivos de desempeño por empleado -- crear/eliminar (una entrada
    mal introducida por error) más una acción propia para cambiar el
    estado, `update_status()`, en vez de un update() genérico: título y
    fecha objetivo no se editan en el sitio (si están mal, se elimina y se
    crea de nuevo, igual que WorkAccident/EmployeeTraining), pero el
    estado SÍ cambia con el tiempo según avanza el objetivo -- eso no es
    una corrección, es su ciclo de vida normal."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(
        self, employee_id: int, title: str, target_date: date, notes: str = ""
    ) -> Objective:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        clean_title = validation.validate_required_text(title, "titulo")
        clean_notes = validation.validate_note(notes)
        created_at = datetime.now().replace(microsecond=0)
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO employee_objectives
                    (employee_id, title, target_date, status, notes, created_at)
                VALUES (?, ?, ?, 'pendiente', ?, ?)
                """,
                (
                    employee_id,
                    clean_title,
                    target_date.isoformat(),
                    clean_notes,
                    created_at.isoformat(timespec="seconds"),
                ),
            )
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def get(self, objective_id: int) -> Objective:
        row = self._conn.execute(
            "SELECT * FROM employee_objectives WHERE id = ?", (objective_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el objetivo con id {objective_id}")
        return _row_to_objective(row)

    def list_for_employee(self, employee_id: int) -> list[Objective]:
        rows = self._conn.execute(
            "SELECT * FROM employee_objectives WHERE employee_id = ? "
            "ORDER BY target_date DESC, id DESC",
            (employee_id,),
        ).fetchall()
        return [_row_to_objective(row) for row in rows]

    def update_status(self, objective_id: int, status: str) -> Objective:
        self.get(objective_id)
        clean_status = validation.validate_objective_status(status)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE employee_objectives SET status = ? WHERE id = ?",
                (clean_status, objective_id),
            )
        return self.get(objective_id)

    def delete(self, objective_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM employee_objectives WHERE id = ?", (objective_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el objetivo con id {objective_id}")


def _row_to_performance_review(row: sqlite3.Row) -> PerformanceReview:
    return PerformanceReview(
        id=row["id"],
        employee_id=row["employee_id"],
        review_date=date.fromisoformat(row["review_date"]),
        comments=row["comments"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class PerformanceReviewRepository:
    """Notas de seguimiento/evaluación de desempeño -- crear/eliminar
    únicamente, igual que WorkAccident: un hecho registrado por un humano
    (una conversación, una evaluación) que puede necesitar borrarse si se
    introdujo por error, pero no una plantilla de campos que tenga sentido
    editar en el sitio."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(self, employee_id: int, review_date: date, comments: str) -> PerformanceReview:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        clean_comments = validation.validate_required_text(comments, "comentarios")
        created_at = datetime.now().replace(microsecond=0)
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO performance_reviews (employee_id, review_date, comments, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    employee_id,
                    review_date.isoformat(),
                    clean_comments,
                    created_at.isoformat(timespec="seconds"),
                ),
            )
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def get(self, review_id: int) -> PerformanceReview:
        row = self._conn.execute(
            "SELECT * FROM performance_reviews WHERE id = ?", (review_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe la evaluación con id {review_id}")
        return _row_to_performance_review(row)

    def list_for_employee(self, employee_id: int) -> list[PerformanceReview]:
        rows = self._conn.execute(
            "SELECT * FROM performance_reviews WHERE employee_id = ? "
            "ORDER BY review_date DESC, id DESC",
            (employee_id,),
        ).fetchall()
        return [_row_to_performance_review(row) for row in rows]

    def delete(self, review_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM performance_reviews WHERE id = ?", (review_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe la evaluación con id {review_id}")


def _row_to_assigned_equipment(row: sqlite3.Row) -> AssignedEquipment:
    return AssignedEquipment(
        id=row["id"],
        employee_id=row["employee_id"],
        description=row["description"],
        assigned_date=date.fromisoformat(row["assigned_date"]),
        returned_date=(
            date.fromisoformat(row["returned_date"])
            if row["returned_date"] is not None
            else None
        ),
        notes=row["notes"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class AssignedEquipmentRepository:
    """Inventario ligero de material entregado a un empleado -- crear/
    eliminar (un registro mal introducido por error) más una acción propia
    para marcarlo devuelto, `mark_returned()`, en vez de un update()
    genérico: la descripción y fecha de entrega no se editan en el sitio
    (si están mal, se elimina y se crea de nuevo, igual que WorkAccident/
    Objective), pero pasar de "en manos del empleado" a "devuelto" sí es
    una transición de estado normal, no una corrección."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(
        self, employee_id: int, description: str, assigned_date: date, notes: str = ""
    ) -> AssignedEquipment:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        clean_description = validation.validate_required_text(description, "descripcion")
        clean_notes = validation.validate_note(notes)
        created_at = datetime.now().replace(microsecond=0)
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO assigned_equipment
                    (employee_id, description, assigned_date, notes, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    clean_description,
                    assigned_date.isoformat(),
                    clean_notes,
                    created_at.isoformat(timespec="seconds"),
                ),
            )
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def get(self, equipment_id: int) -> AssignedEquipment:
        row = self._conn.execute(
            "SELECT * FROM assigned_equipment WHERE id = ?", (equipment_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el registro de equipo con id {equipment_id}")
        return _row_to_assigned_equipment(row)

    def list_for_employee(self, employee_id: int) -> list[AssignedEquipment]:
        rows = self._conn.execute(
            "SELECT * FROM assigned_equipment WHERE employee_id = ? "
            "ORDER BY assigned_date DESC, id DESC",
            (employee_id,),
        ).fetchall()
        return [_row_to_assigned_equipment(row) for row in rows]

    def mark_returned(self, equipment_id: int, returned_date: date) -> AssignedEquipment:
        existing = self.get(equipment_id)
        if existing.returned_date is not None:
            raise RepositoryError("este material ya está marcado como devuelto")
        if returned_date < existing.assigned_date:
            raise validation.ValidationError(
                "fecha_devolucion", "no puede ser anterior a la fecha de entrega"
            )
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE assigned_equipment SET returned_date = ? WHERE id = ?",
                (returned_date.isoformat(), equipment_id),
            )
        return self.get(equipment_id)

    def delete(self, equipment_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM assigned_equipment WHERE id = ?", (equipment_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el registro de equipo con id {equipment_id}")


def _row_to_it_episode(row: sqlite3.Row) -> ITEpisode:
    return ITEpisode(
        id=row["id"],
        employee_id=row["employee_id"],
        contingency=row["contingency"],
        leave_date=date.fromisoformat(row["leave_date"]),
        last_confirmation_date=(
            date.fromisoformat(row["last_confirmation_date"])
            if row["last_confirmation_date"] is not None
            else None
        ),
        return_date=(
            date.fromisoformat(row["return_date"]) if row["return_date"] is not None else None
        ),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class ITEpisodeRepository:
    """Un episodio de incapacidad temporal como entidad propia -- parte de
    baja, confirmación, alta -- en vez de solo un día marcado "Enfermedad"
    en el calendario (que sigue existiendo aparte, sin cambios, para el
    propio cuadrante visual; ver app/incapacidad_temporal.py para el
    cálculo de quién paga qué parte del salario según la contingencia)."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(self, employee_id: int, contingency: str, leave_date: date) -> ITEpisode:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        if self.get_open_episode_for_employee(employee_id) is not None:
            raise RepositoryError(
                "el empleado ya tiene un episodio de IT abierto -- dele el alta antes de "
                "registrar uno nuevo"
            )
        created_at = datetime.now().replace(microsecond=0)
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO it_episodes (employee_id, contingency, leave_date, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (employee_id, contingency, leave_date.isoformat(), created_at.isoformat(timespec="seconds")),
            )
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def get(self, episode_id: int) -> ITEpisode:
        row = self._conn.execute(
            "SELECT * FROM it_episodes WHERE id = ?", (episode_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el episodio de IT con id {episode_id}")
        return _row_to_it_episode(row)

    def list_for_employee(self, employee_id: int) -> list[ITEpisode]:
        rows = self._conn.execute(
            "SELECT * FROM it_episodes WHERE employee_id = ? ORDER BY leave_date DESC, id DESC",
            (employee_id,),
        ).fetchall()
        return [_row_to_it_episode(row) for row in rows]

    def get_open_episode_for_employee(self, employee_id: int) -> ITEpisode | None:
        row = self._conn.execute(
            "SELECT * FROM it_episodes WHERE employee_id = ? AND return_date IS NULL "
            "ORDER BY leave_date DESC LIMIT 1",
            (employee_id,),
        ).fetchone()
        return _row_to_it_episode(row) if row is not None else None

    def set_confirmation(self, episode_id: int, confirmation_date: date) -> ITEpisode:
        existing = self.get(episode_id)
        if not existing.is_open:
            raise RepositoryError("este episodio de IT ya tiene alta, no admite confirmaciones")
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE it_episodes SET last_confirmation_date = ? WHERE id = ?",
                (confirmation_date.isoformat(), episode_id),
            )
        return self.get(episode_id)

    def close(self, episode_id: int, return_date: date) -> ITEpisode:
        existing = self.get(episode_id)
        if not existing.is_open:
            raise RepositoryError("este episodio de IT ya tiene alta")
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE it_episodes SET return_date = ? WHERE id = ?",
                (return_date.isoformat(), episode_id),
            )
        return self.get(episode_id)

    def delete(self, episode_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute("DELETE FROM it_episodes WHERE id = ?", (episode_id,))
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el episodio de IT con id {episode_id}")


# Códigos de acción del registro de auditoría -- constantes en vez de strings
# repetidos en cada punto de la UI que audita algo, para que un typo se note
# en tiempo de desarrollo (autocompletado/mypy) en vez de en producción, y
# porque el propio CHECK de la tabla audit_log usa exactamente esta lista.
AUDIT_LOGIN_SUCCESS = "login_success"
AUDIT_LOGIN_FAILURE = "login_failure"
AUDIT_USER_CREATED = "user_created"
AUDIT_USER_DELETED = "user_deleted"
AUDIT_DEPARTMENT_CREATED = "department_created"
AUDIT_DEPARTMENT_DELETED = "department_deleted"
AUDIT_EMPLOYEE_CREATED = "employee_created"
AUDIT_EMPLOYEE_DELETED = "employee_deleted"
AUDIT_EMPLOYEE_TERMINATED = "employee_terminated"
AUDIT_EMPLOYEE_REACTIVATED = "employee_reactivated"
AUDIT_DOCUMENT_DELETED = "document_deleted"
AUDIT_ABSENCE_APPROVED = "absence_approved"
AUDIT_ABSENCE_REJECTED = "absence_rejected"
AUDIT_BACKUP_RESTORED = "backup_restored"
AUDIT_EMPLOYEE_ANONYMIZED = "employee_anonymized"
AUDIT_DATA_EXPORTED = "data_exported"
AUDIT_WORK_ACCIDENT_DELETED = "work_accident_deleted"
AUDIT_IT_EPISODE_DELETED = "it_episode_deleted"
AUDIT_TRAINING_DELETED = "training_deleted"
AUDIT_SELF_SERVICE_PIN_SET = "self_service_pin_set"
AUDIT_SELF_SERVICE_PIN_CLEARED = "self_service_pin_cleared"
AUDIT_OBJECTIVE_DELETED = "objective_deleted"
AUDIT_PERFORMANCE_REVIEW_DELETED = "performance_review_deleted"
AUDIT_EQUIPMENT_DELETED = "equipment_deleted"


def _row_to_audit_log_entry(row: sqlite3.Row) -> AuditLogEntry:
    return AuditLogEntry(
        id=row["id"],
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        user_id=row["user_id"],
        username=row["username"],
        action=row["action"],
        details=row["details"],
    )


class AuditLogRepository:
    """Quién hizo qué y cuándo, para las acciones administrativas/sensibles
    de la app (ver las constantes AUDIT_* arriba para la lista completa).
    Deliberadamente NO registra cada edición rutinaria de un campo (cambiar
    un teléfono, por ejemplo) -- eso generaría demasiado ruido para que el
    registro siga siendo útil de un vistazo; el historial de puesto/salario
    (EmployeeHistoryRepository) ya cubre aparte esos dos campos concretos.

    Mantiene el usuario actualmente autenticado como estado propio
    (set_current_user(), fijado una vez por main.py justo tras el login) en
    vez de exigir que cada punto de la UI que llama a record() tenga que
    pasar el usuario -- MainWindow y cada página/diálogo ya reciben `repos`
    en su constructor, así que esto evita añadir un parámetro `current_user`
    a decenas de constructores solo para poder auditar."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn
        self._current_user: User | None = None

    def set_current_user(self, user: User | None) -> None:
        self._current_user = user

    def record(self, action: str, details: str = "") -> AuditLogEntry:
        user_id = self._current_user.id if self._current_user is not None else None
        username = self._current_user.username if self._current_user is not None else "?"
        return self._insert(user_id, username, action, details)

    def record_login_attempt(
        self, username: str, success: bool, user_id: int | None
    ) -> AuditLogEntry:
        action = AUDIT_LOGIN_SUCCESS if success else AUDIT_LOGIN_FAILURE
        return self._insert(user_id, username, action, "")

    def _insert(
        self, user_id: int | None, username: str, action: str, details: str
    ) -> AuditLogEntry:
        occurred_at = datetime.now().replace(microsecond=0)
        with transaction(self._conn):
            cursor = self._conn.execute(
                "INSERT INTO audit_log (occurred_at, user_id, username, action, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (occurred_at.isoformat(timespec="seconds"), user_id, username, action, details),
            )
        entry_id = cursor.lastrowid
        assert entry_id is not None
        return self.get(entry_id)

    def get(self, entry_id: int) -> AuditLogEntry:
        row = self._conn.execute(
            "SELECT * FROM audit_log WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe la entrada de auditoría con id {entry_id}")
        return _row_to_audit_log_entry(row)

    def list_all(self, limit: int = 500) -> list[AuditLogEntry]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log ORDER BY occurred_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_audit_log_entry(row) for row in rows]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_to_employee_document(row: sqlite3.Row) -> EmployeeDocument:
    return EmployeeDocument(
        id=row["id"],
        employee_id=row["employee_id"],
        filename=row["filename"],
        category=row["category"],
        content=row["content"],
        size_bytes=row["size_bytes"],
        uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
    )


def _row_to_employee_document_summary(row: sqlite3.Row) -> EmployeeDocumentSummary:
    return EmployeeDocumentSummary(
        id=row["id"],
        employee_id=row["employee_id"],
        filename=row["filename"],
        category=row["category"],
        size_bytes=row["size_bytes"],
        uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
    )


class EmployeeDocumentRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def upload(
        self, employee_id: int, filename: str, category: str, content: bytes
    ) -> EmployeeDocument:
        employee_row = self._conn.execute(
            "SELECT anonymized FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
        if employee_row is None:
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        if employee_row["anonymized"]:
            # Mismo guard que EmployeeRepository.update()/set_photo(): sin
            # esto, se podía adjuntar un documento nuevo (con datos reales
            # en el propio archivo) a un empleado cuyos datos ya se habían
            # anonimizado, socavando el propósito de esa anonimización.
            raise RepositoryError(
                "no se pueden modificar los datos de un empleado ya anonimizado"
            )
        clean_filename = validation.validate_document_filename(filename)
        clean_category = validation.validate_document_category(category)
        clean_content = validation.validate_document_content(content)
        uploaded_at = datetime.now().replace(microsecond=0)
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO employee_documents
                    (employee_id, filename, category, content, size_bytes, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    clean_filename,
                    clean_category,
                    clean_content,
                    len(clean_content),
                    uploaded_at.isoformat(timespec="seconds"),
                ),
            )
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def get(self, document_id: int) -> EmployeeDocument:
        row = self._conn.execute(
            "SELECT * FROM employee_documents WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el documento con id {document_id}")
        return _row_to_employee_document(row)

    def list_for_employee(self, employee_id: int) -> list[EmployeeDocumentSummary]:
        rows = self._conn.execute(
            """
            SELECT id, employee_id, filename, category, size_bytes, uploaded_at
            FROM employee_documents WHERE employee_id = ? ORDER BY uploaded_at DESC
            """,
            (employee_id,),
        ).fetchall()
        return [_row_to_employee_document_summary(row) for row in rows]

    def delete(self, document_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM employee_documents WHERE id = ?", (document_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el documento con id {document_id}")


def _row_to_document_template(row: sqlite3.Row) -> DocumentTemplate:
    return DocumentTemplate(
        id=row["id"],
        name=row["name"],
        body=row["body"],
        created_at=date.fromisoformat(row["created_at"]),
    )


class DocumentTemplateRepository:
    """Plantillas reutilizables de documentos (oferta, contrato, carta de
    baja...) con marcadores {campo} -- ver app/document_templates.py para
    la sustitución pura. Generar un documento a partir de una plantilla NO
    crea ningún registro propio: produce texto que la interfaz puede
    mostrar, copiar o guardar como un documento adjunto normal
    (EmployeeDocumentRepository), indistinguible después de uno subido a
    mano -- evita duplicar el almacenamiento/descarga/eliminación ya
    existentes para documentos."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(self, name: str, body: str) -> DocumentTemplate:
        clean_name = validation.validate_required_text(name, "plantilla_documento")
        clean_body = validation.validate_document_template_body(body)
        created_at = date.today()
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    "INSERT INTO document_templates (name, body, created_at) VALUES (?, ?, ?)",
                    (clean_name, clean_body, created_at.isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(
                f"ya existe una plantilla de documento llamada '{clean_name}'"
            ) from exc
        return DocumentTemplate(
            id=cursor.lastrowid, name=clean_name, body=clean_body, created_at=created_at
        )

    def update(self, template_id: int, name: str, body: str) -> DocumentTemplate:
        existing = self.get(template_id)
        clean_name = validation.validate_required_text(name, "plantilla_documento")
        clean_body = validation.validate_document_template_body(body)
        try:
            with transaction(self._conn):
                self._conn.execute(
                    "UPDATE document_templates SET name = ?, body = ? WHERE id = ?",
                    (clean_name, clean_body, template_id),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(
                f"ya existe una plantilla de documento llamada '{clean_name}'"
            ) from exc
        return DocumentTemplate(
            id=existing.id, name=clean_name, body=clean_body, created_at=existing.created_at
        )

    def get(self, template_id: int) -> DocumentTemplate:
        row = self._conn.execute(
            "SELECT * FROM document_templates WHERE id = ?", (template_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe la plantilla de documento con id {template_id}")
        return _row_to_document_template(row)

    def list_all(self) -> list[DocumentTemplate]:
        rows = self._conn.execute("SELECT * FROM document_templates ORDER BY name").fetchall()
        return [_row_to_document_template(row) for row in rows]

    def delete(self, template_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM document_templates WHERE id = ?", (template_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe la plantilla de documento con id {template_id}")

    def render_for_employee(self, template_id: int, employee_id: int) -> str:
        template = self.get(template_id)
        employee_row = self._conn.execute(
            "SELECT * FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
        if employee_row is None:
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        employee = _row_to_employee(employee_row)
        department_row = self._conn.execute(
            "SELECT name FROM departments WHERE id = ?", (employee.department_id,)
        ).fetchone()
        department_name = department_row["name"] if department_row is not None else ""
        values = build_placeholder_values(employee, department_name)
        return render_document_template(template.body, values)


def _row_to_onboarding_task(row: sqlite3.Row) -> OnboardingTask:
    return OnboardingTask(id=row["id"], name=row["name"])


class OnboardingTaskRepository:
    """Catálogo compartido de tareas de incorporación (contrato firmado,
    alta en Seguridad Social, equipo entregado, accesos creados...) más el
    estado -- hecha/pendiente -- de cada una para un empleado concreto.
    Deliberadamente sin materializar una fila por tarea al crear un
    empleado: checklist_for_employee() calcula el estado al vuelo con un
    LEFT JOIN, así que una tarea añadida al catálogo más tarde aparece de
    inmediato como pendiente para TODOS los empleados, incluidos los ya
    existentes, sin ningún proceso de relleno retroactivo. Solo existe una
    fila en onboarding_checklist_items para lo que de verdad está marcado
    como hecho -- desmarcar una tarea borra la fila en vez de guardar un
    booleano a False."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(self, name: str) -> OnboardingTask:
        clean_name = validation.validate_required_text(name, "tarea_incorporacion")
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    "INSERT INTO onboarding_tasks (name) VALUES (?)", (clean_name,)
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(
                f"ya existe una tarea de incorporación llamada '{clean_name}'"
            ) from exc
        return OnboardingTask(id=cursor.lastrowid, name=clean_name)

    def update(self, task_id: int, name: str) -> OnboardingTask:
        self.get(task_id)
        clean_name = validation.validate_required_text(name, "tarea_incorporacion")
        try:
            with transaction(self._conn):
                self._conn.execute(
                    "UPDATE onboarding_tasks SET name = ? WHERE id = ?", (clean_name, task_id)
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(
                f"ya existe una tarea de incorporación llamada '{clean_name}'"
            ) from exc
        return OnboardingTask(id=task_id, name=clean_name)

    def get(self, task_id: int) -> OnboardingTask:
        row = self._conn.execute(
            "SELECT * FROM onboarding_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe la tarea de incorporación con id {task_id}")
        return _row_to_onboarding_task(row)

    def list_all(self) -> list[OnboardingTask]:
        rows = self._conn.execute("SELECT * FROM onboarding_tasks ORDER BY name").fetchall()
        return [_row_to_onboarding_task(row) for row in rows]

    def delete(self, task_id: int) -> None:
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    "DELETE FROM onboarding_tasks WHERE id = ?", (task_id,)
                )
        except sqlite3.IntegrityError as exc:
            raise ReferenceInUseError(
                "no se puede eliminar: hay empleados con esta tarea ya marcada como hecha"
            ) from exc
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe la tarea de incorporación con id {task_id}")

    def checklist_for_employee(self, employee_id: int) -> list[OnboardingChecklistStatus]:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        rows = self._conn.execute(
            """
            SELECT t.id AS task_id, t.name AS task_name, oci.completed_at AS completed_at
            FROM onboarding_tasks t
            LEFT JOIN onboarding_checklist_items oci
                ON oci.task_id = t.id AND oci.employee_id = ?
            ORDER BY t.name
            """,
            (employee_id,),
        ).fetchall()
        return [
            OnboardingChecklistStatus(
                task=OnboardingTask(id=row["task_id"], name=row["task_name"]),
                completed_at=(
                    date.fromisoformat(row["completed_at"])
                    if row["completed_at"] is not None
                    else None
                ),
            )
            for row in rows
        ]

    def mark_complete(self, employee_id: int, task_id: int, completed_at: date) -> None:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        self.get(task_id)
        with transaction(self._conn):
            self._conn.execute(
                """
                INSERT INTO onboarding_checklist_items (employee_id, task_id, completed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(employee_id, task_id) DO UPDATE SET completed_at = excluded.completed_at
                """,
                (employee_id, task_id, completed_at.isoformat()),
            )

    def mark_incomplete(self, employee_id: int, task_id: int) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "DELETE FROM onboarding_checklist_items WHERE employee_id = ? AND task_id = ?",
                (employee_id, task_id),
            )


@dataclass(frozen=True, slots=True)
class _ValidatedShift:
    name: str
    start_time: str
    end_time: str
    days_of_week: frozenset[int]
    start_time_2: str | None
    end_time_2: str | None


class ShiftRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def _validate(self, data: ShiftInput) -> _ValidatedShift:
        name = validation.validate_required_text(data.name, "turno")
        start_time = validation.validate_time_hhmm(data.start_time, "hora_inicio")
        end_time = validation.validate_time_hhmm(data.end_time, "hora_fin")
        validation.validate_time_order(start_time, end_time, allow_overnight=True)
        days = validation.validate_days_of_week(data.days_of_week)
        split = validation.validate_split_shift_times(
            data.start_time_2, data.end_time_2, end_time
        )
        department_exists = self._conn.execute(
            "SELECT 1 FROM departments WHERE id = ?", (data.department_id,)
        ).fetchone()
        if department_exists is None:
            raise NotFoundError(f"no existe el departamento con id {data.department_id}")
        return _ValidatedShift(
            name=name,
            start_time=start_time,
            end_time=end_time,
            days_of_week=days,
            start_time_2=split[0] if split else None,
            end_time_2=split[1] if split else None,
        )

    def create(self, data: ShiftInput) -> Shift:
        v = self._validate(data)
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    """
                    INSERT INTO shifts
                        (department_id, name, start_time, end_time,
                         days_of_week, start_time_2, end_time_2)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data.department_id,
                        v.name,
                        v.start_time,
                        v.end_time,
                        _format_days_of_week(v.days_of_week),
                        v.start_time_2,
                        v.end_time_2,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(
                f"ya existe un turno llamado '{v.name}' en este departamento"
            ) from exc
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def update(self, shift_id: int, data: ShiftInput) -> Shift:
        self.get(shift_id)
        v = self._validate(data)
        try:
            with transaction(self._conn):
                self._conn.execute(
                    """
                    UPDATE shifts
                    SET department_id = ?, name = ?, start_time = ?, end_time = ?,
                        days_of_week = ?, start_time_2 = ?, end_time_2 = ?
                    WHERE id = ?
                    """,
                    (
                        data.department_id,
                        v.name,
                        v.start_time,
                        v.end_time,
                        _format_days_of_week(v.days_of_week),
                        v.start_time_2,
                        v.end_time_2,
                        shift_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(
                f"ya existe un turno llamado '{v.name}' en este departamento"
            ) from exc
        return self.get(shift_id)

    def get(self, shift_id: int) -> Shift:
        row = self._conn.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el turno con id {shift_id}")
        return _row_to_shift(row)

    def delete(self, shift_id: int) -> None:
        try:
            with transaction(self._conn):
                cursor = self._conn.execute("DELETE FROM shifts WHERE id = ?", (shift_id,))
        except sqlite3.IntegrityError as exc:
            raise ReferenceInUseError(
                "no se puede eliminar: hay días asignados a este turno en el calendario"
            ) from exc
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el turno con id {shift_id}")

    def list_for_department(self, department_id: int) -> list[Shift]:
        rows = self._conn.execute(
            "SELECT * FROM shifts WHERE department_id = ? ORDER BY name", (department_id,)
        ).fetchall()
        return [_row_to_shift(row) for row in rows]


class DayTypeRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(self, name: str, color: str, is_vacation: bool = False) -> DayType:
        clean_name = validation.validate_required_text(name, "tipo_de_dia")
        clean_color = validation.validate_color_hex(color)
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    "INSERT INTO day_types (name, color, is_vacation) VALUES (?, ?, ?)",
                    (clean_name, clean_color, int(is_vacation)),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"ya existe un tipo de día llamado '{clean_name}'") from exc
        return DayType(
            id=cursor.lastrowid, name=clean_name, color=clean_color, is_vacation=is_vacation
        )

    def update(self, day_type_id: int, name: str, color: str, is_vacation: bool) -> DayType:
        self.get(day_type_id)
        clean_name = validation.validate_required_text(name, "tipo_de_dia")
        clean_color = validation.validate_color_hex(color)
        try:
            with transaction(self._conn):
                self._conn.execute(
                    "UPDATE day_types SET name = ?, color = ?, is_vacation = ? WHERE id = ?",
                    (clean_name, clean_color, int(is_vacation), day_type_id),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"ya existe un tipo de día llamado '{clean_name}'") from exc
        return self.get(day_type_id)

    def get(self, day_type_id: int) -> DayType:
        row = self._conn.execute(
            "SELECT * FROM day_types WHERE id = ?", (day_type_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el tipo de día con id {day_type_id}")
        return _row_to_day_type(row)

    def list_all(self) -> list[DayType]:
        rows = self._conn.execute("SELECT * FROM day_types ORDER BY name").fetchall()
        return [_row_to_day_type(row) for row in rows]

    def delete(self, day_type_id: int) -> None:
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    "DELETE FROM day_types WHERE id = ?", (day_type_id,)
                )
        except sqlite3.IntegrityError as exc:
            raise ReferenceInUseError(
                "no se puede eliminar: hay días marcados con este tipo"
            ) from exc
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el tipo de día con id {day_type_id}")


class DepartmentClosureRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def _ensure_department_and_day_type(self, department_id: int, day_type_id: int) -> None:
        if (
            self._conn.execute(
                "SELECT 1 FROM departments WHERE id = ?", (department_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el departamento con id {department_id}")
        if (
            self._conn.execute(
                "SELECT 1 FROM day_types WHERE id = ?", (day_type_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el tipo de día con id {day_type_id}")

    def set_day(
        self, department_id: int, day: date, day_type_id: int | None, note: str = ""
    ) -> None:
        with transaction(self._conn):
            if day_type_id is None:
                self._conn.execute(
                    "DELETE FROM department_closures "
                    "WHERE department_id = ? AND closure_date = ?",
                    (department_id, day.isoformat()),
                )
                return
            self._ensure_department_and_day_type(department_id, day_type_id)
            clean_note = validation.validate_note(note)
            self._conn.execute(
                """
                INSERT INTO department_closures
                    (department_id, closure_date, day_type_id, note)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(department_id, closure_date) DO UPDATE SET
                    day_type_id = excluded.day_type_id,
                    note = excluded.note
                """,
                (department_id, day.isoformat(), day_type_id, clean_note),
            )

    def mark_range(
        self, department_id: int, day_type_id: int, start: date, end: date, note: str = ""
    ) -> int:
        validation.validate_date_range(start, end)
        self._ensure_department_and_day_type(department_id, day_type_id)
        clean_note = validation.validate_note(note)
        count = 0
        with transaction(self._conn):
            current = start
            while current <= end:
                self._conn.execute(
                    """
                    INSERT INTO department_closures
                        (department_id, closure_date, day_type_id, note)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(department_id, closure_date) DO UPDATE SET
                        day_type_id = excluded.day_type_id,
                        note = excluded.note
                    """,
                    (department_id, current.isoformat(), day_type_id, clean_note),
                )
                count += 1
                current += timedelta(days=1)
        return count

    def get_for_month(
        self, department_id: int, year: int, month: int
    ) -> dict[date, DepartmentClosure]:
        start, end = _month_bounds(year, month)
        rows = self._conn.execute(
            """
            SELECT * FROM department_closures
            WHERE department_id = ? AND closure_date BETWEEN ? AND ?
            """,
            (department_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        items = [_row_to_department_closure(row) for row in rows]
        return {item.closure_date: item for item in items}

    def list_for_date(self, day: date) -> list[DepartmentClosure]:
        rows = self._conn.execute(
            "SELECT * FROM department_closures WHERE closure_date = ?", (day.isoformat(),)
        ).fetchall()
        return [_row_to_department_closure(row) for row in rows]

    def list_dates_for_department(self, department_id: int) -> frozenset[date]:
        """Todas las fechas con cierre ya registrado para este departamento,
        sin acotar por mes/año -- pensado para que el selector de fecha
        (calendar_widget.CalendarPopup/DateEntry) pueda resaltarlas
        mientras el usuario navega entre meses, sin tener que volver a
        consultar la base de datos en cada clic de "<"/">"."""
        rows = self._conn.execute(
            "SELECT closure_date FROM department_closures WHERE department_id = ?",
            (department_id,),
        ).fetchall()
        return frozenset(date.fromisoformat(row["closure_date"]) for row in rows)


class HolidayTemplateRepository:
    """Plantillas de festivos reutilizables (nacional/autonómico/local) --
    se rellenan una vez pegando una lista de fechas (ver
    validation.parse_holiday_import_text) y se aplican en bloque a uno o
    varios departamentos como cierres (department_closures), en vez de
    marcar cada fecha a mano departamento por departamento cada enero.
    Aplicar es no destructivo: una fecha que ya tenía un cierre registrado
    para ese departamento (por el motivo que fuera) se deja como estaba en
    vez de sobrescribirla -- ver apply_to_departments()."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(self, name: str) -> HolidayTemplate:
        clean_name = validation.validate_required_text(name, "plantilla_festivos")
        created_at = date.today()
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    "INSERT INTO holiday_templates (name, created_at) VALUES (?, ?)",
                    (clean_name, created_at.isoformat()),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(
                f"ya existe una plantilla de festivos llamada '{clean_name}'"
            ) from exc
        return HolidayTemplate(id=cursor.lastrowid, name=clean_name, created_at=created_at)

    def get(self, template_id: int) -> HolidayTemplate:
        row = self._conn.execute(
            "SELECT * FROM holiday_templates WHERE id = ?", (template_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe la plantilla de festivos con id {template_id}")
        return _row_to_holiday_template(row)

    def list_all(self) -> list[HolidayTemplate]:
        rows = self._conn.execute("SELECT * FROM holiday_templates ORDER BY name").fetchall()
        return [_row_to_holiday_template(row) for row in rows]

    def delete(self, template_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM holiday_templates WHERE id = ?", (template_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe la plantilla de festivos con id {template_id}")

    def list_dates(self, template_id: int) -> list[HolidayTemplateDate]:
        self.get(template_id)
        rows = self._conn.execute(
            "SELECT * FROM holiday_template_dates WHERE template_id = ? ORDER BY holiday_date",
            (template_id,),
        ).fetchall()
        return [_row_to_holiday_template_date(row) for row in rows]

    def import_dates(self, template_id: int, text: str) -> int:
        """Añade (o actualiza la etiqueta de) las fechas de `text` a una
        plantilla existente -- ver validation.parse_holiday_import_text.
        Devuelve cuántas fechas se han importado."""
        self.get(template_id)
        parsed = validation.parse_holiday_import_text(text)
        with transaction(self._conn):
            for holiday_date, label in parsed:
                self._conn.execute(
                    """
                    INSERT INTO holiday_template_dates (template_id, holiday_date, label)
                    VALUES (?, ?, ?)
                    ON CONFLICT(template_id, holiday_date) DO UPDATE SET label = excluded.label
                    """,
                    (template_id, holiday_date.isoformat(), label),
                )
        return len(parsed)

    def delete_date(self, template_date_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM holiday_template_dates WHERE id = ?", (template_date_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe esa fecha de la plantilla (id {template_date_id})")

    def apply_to_departments(
        self, template_id: int, department_ids: list[int], day_type_id: int
    ) -> HolidayApplyResult:
        dates = self.list_dates(template_id)
        if not dates:
            raise RepositoryError("esta plantilla todavía no tiene ninguna fecha")
        if not department_ids:
            raise RepositoryError("seleccione al menos un departamento")
        if (
            self._conn.execute(
                "SELECT 1 FROM day_types WHERE id = ?", (day_type_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el tipo de día con id {day_type_id}")
        created = 0
        skipped = 0
        with transaction(self._conn):
            for department_id in department_ids:
                if (
                    self._conn.execute(
                        "SELECT 1 FROM departments WHERE id = ?", (department_id,)
                    ).fetchone()
                    is None
                ):
                    raise NotFoundError(f"no existe el departamento con id {department_id}")
                for entry in dates:
                    cursor = self._conn.execute(
                        """
                        INSERT INTO department_closures
                            (department_id, closure_date, day_type_id, note)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(department_id, closure_date) DO NOTHING
                        """,
                        (department_id, entry.holiday_date.isoformat(), day_type_id, entry.label),
                    )
                    if cursor.rowcount > 0:
                        created += 1
                    else:
                        skipped += 1
        return HolidayApplyResult(
            departments_applied=len(department_ids),
            closures_created=created,
            closures_skipped=skipped,
        )


class EmployeeAbsenceRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def _ensure_employee_and_day_type(self, employee_id: int, day_type_id: int) -> None:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        if (
            self._conn.execute(
                "SELECT 1 FROM day_types WHERE id = ?", (day_type_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el tipo de día con id {day_type_id}")

    def _working_weekdays(self, employee_id: int) -> frozenset[int]:
        row = self._conn.execute(
            """
            SELECT shifts.days_of_week AS days_of_week
            FROM employees
            LEFT JOIN shifts ON shifts.id = employees.shift_id
            WHERE employees.id = ?
            """,
            (employee_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        if row["days_of_week"] is None:
            return _DEFAULT_WORKING_WEEKDAYS
        return _parse_days_of_week(row["days_of_week"])

    def _previous_state_for_upsert(
        self, employee_id: int, day: date
    ) -> tuple[int | None, str | None]:
        """Antes de sobrescribir la fila de un día con una nueva solicitud
        (request()/request_range()), calcula qué guardar en
        previous_day_type_id/previous_note para poder restaurarlo si esa
        solicitud se rechaza después: si el día ya estaba 'aprobada', se
        captura ESE estado; si ya había una solicitud 'pendiente' sin
        decidir (se pide otro cambio antes de que se apruebe/rechace la
        anterior), se conserva el snapshot que YA se había capturado la
        primera vez, sin pisarlo con nada (la fila ya no está 'aprobada',
        así que aquí no habría nada real que capturar de nuevo); en
        cualquier otro caso (no existía fila, o estaba 'rechazada') no hay
        nada que preservar."""
        row = self._conn.execute(
            "SELECT day_type_id, note, status, previous_day_type_id, previous_note "
            "FROM employee_absences WHERE employee_id = ? AND absence_date = ?",
            (employee_id, day.isoformat()),
        ).fetchone()
        if row is None:
            return None, None
        if row["status"] == "aprobada":
            return row["day_type_id"], row["note"]
        if row["status"] == "pendiente":
            return row["previous_day_type_id"], row["previous_note"]
        return None, None

    def set_day(
        self, employee_id: int, day: date, day_type_id: int | None, note: str = ""
    ) -> None:
        with transaction(self._conn):
            if day_type_id is None:
                self._conn.execute(
                    "DELETE FROM employee_absences WHERE employee_id = ? AND absence_date = ?",
                    (employee_id, day.isoformat()),
                )
                return
            self._ensure_employee_and_day_type(employee_id, day_type_id)
            clean_note = validation.validate_note(note)
            self._conn.execute(
                """
                INSERT INTO employee_absences
                    (employee_id, absence_date, day_type_id, note, status,
                     previous_day_type_id, previous_note)
                VALUES (?, ?, ?, ?, 'aprobada', NULL, NULL)
                ON CONFLICT(employee_id, absence_date) DO UPDATE SET
                    day_type_id = excluded.day_type_id,
                    note = excluded.note,
                    status = 'aprobada',
                    previous_day_type_id = NULL,
                    previous_note = NULL
                """,
                (employee_id, day.isoformat(), day_type_id, clean_note),
            )

    def mark_range(
        self, employee_id: int, day_type_id: int, start: date, end: date, note: str = ""
    ) -> MarkRangeResult:
        validation.validate_date_range(start, end)
        self._ensure_employee_and_day_type(employee_id, day_type_id)
        working_weekdays = self._working_weekdays(employee_id)
        clean_note = validation.validate_note(note)
        marked = 0
        skipped = 0
        with transaction(self._conn):
            current = start
            while current <= end:
                if current.isoweekday() in working_weekdays:
                    self._conn.execute(
                        """
                        INSERT INTO employee_absences
                            (employee_id, absence_date, day_type_id, note, status,
                             previous_day_type_id, previous_note)
                        VALUES (?, ?, ?, ?, 'aprobada', NULL, NULL)
                        ON CONFLICT(employee_id, absence_date) DO UPDATE SET
                            day_type_id = excluded.day_type_id,
                            note = excluded.note,
                            status = 'aprobada',
                            previous_day_type_id = NULL,
                            previous_note = NULL
                        """,
                        (employee_id, current.isoformat(), day_type_id, clean_note),
                    )
                    marked += 1
                else:
                    skipped += 1
                current += timedelta(days=1)
        return MarkRangeResult(marked=marked, skipped=skipped)

    def request(
        self, employee_id: int, day_type_id: int, day: date, note: str = ""
    ) -> EmployeeAbsence:
        """Como set_day(), pero deja el día en estado 'pendiente' en vez de
        confirmarlo directamente -- para que un empleado/encargado pueda
        pedir un día concreto y quede a la espera de aprobación. Si el día
        ya tenía una ausencia 'aprobada', ese estado se guarda en
        previous_day_type_id/previous_note (ver _previous_state_for_upsert())
        para que reject() pueda restaurarlo en vez de dejar el día vacío si
        esta nueva solicitud se rechaza."""
        self._ensure_employee_and_day_type(employee_id, day_type_id)
        clean_note = validation.validate_note(note)
        with transaction(self._conn):
            previous_day_type_id, previous_note = self._previous_state_for_upsert(
                employee_id, day
            )
            self._conn.execute(
                """
                INSERT INTO employee_absences
                    (employee_id, absence_date, day_type_id, note, status,
                     previous_day_type_id, previous_note)
                VALUES (?, ?, ?, ?, 'pendiente', ?, ?)
                ON CONFLICT(employee_id, absence_date) DO UPDATE SET
                    day_type_id = excluded.day_type_id,
                    note = excluded.note,
                    status = 'pendiente',
                    previous_day_type_id = excluded.previous_day_type_id,
                    previous_note = excluded.previous_note
                """,
                (
                    employee_id,
                    day.isoformat(),
                    day_type_id,
                    clean_note,
                    previous_day_type_id,
                    previous_note,
                ),
            )
        row = self._conn.execute(
            "SELECT * FROM employee_absences WHERE employee_id = ? AND absence_date = ?",
            (employee_id, day.isoformat()),
        ).fetchone()
        assert row is not None  # just inserted/updated above
        return _row_to_employee_absence(row)

    def request_range(
        self, employee_id: int, day_type_id: int, start: date, end: date, note: str = ""
    ) -> MarkRangeResult:
        """Como mark_range(), pero cada día queda 'pendiente' de aprobación
        en vez de confirmado al instante."""
        validation.validate_date_range(start, end)
        self._ensure_employee_and_day_type(employee_id, day_type_id)
        working_weekdays = self._working_weekdays(employee_id)
        clean_note = validation.validate_note(note)
        marked = 0
        skipped = 0
        with transaction(self._conn):
            current = start
            while current <= end:
                if current.isoweekday() in working_weekdays:
                    previous_day_type_id, previous_note = self._previous_state_for_upsert(
                        employee_id, current
                    )
                    self._conn.execute(
                        """
                        INSERT INTO employee_absences
                            (employee_id, absence_date, day_type_id, note, status,
                             previous_day_type_id, previous_note)
                        VALUES (?, ?, ?, ?, 'pendiente', ?, ?)
                        ON CONFLICT(employee_id, absence_date) DO UPDATE SET
                            day_type_id = excluded.day_type_id,
                            note = excluded.note,
                            status = 'pendiente',
                            previous_day_type_id = excluded.previous_day_type_id,
                            previous_note = excluded.previous_note
                        """,
                        (
                            employee_id,
                            current.isoformat(),
                            day_type_id,
                            clean_note,
                            previous_day_type_id,
                            previous_note,
                        ),
                    )
                    marked += 1
                else:
                    skipped += 1
                current += timedelta(days=1)
        return MarkRangeResult(marked=marked, skipped=skipped)

    def get(self, absence_id: int) -> EmployeeAbsence:
        row = self._conn.execute(
            "SELECT * FROM employee_absences WHERE id = ?", (absence_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe la ausencia con id {absence_id}")
        return _row_to_employee_absence(row)

    def approve(self, absence_id: int) -> EmployeeAbsence:
        self.get(absence_id)
        with transaction(self._conn):
            # La nueva solicitud ya aprobada es la que cuenta a partir de
            # ahora -- el snapshot de lo que hubiera antes (si lo había)
            # queda superado, no hace falta conservarlo.
            self._conn.execute(
                "UPDATE employee_absences SET status = 'aprobada', "
                "previous_day_type_id = NULL, previous_note = NULL WHERE id = ?",
                (absence_id,),
            )
        return self.get(absence_id)

    def reject(self, absence_id: int) -> EmployeeAbsence:
        """Si esta solicitud había sobrescrito una ausencia ya aprobada
        (ver request()/request_range() y _previous_state_for_upsert()), el
        rechazo RESTAURA ese estado anterior en vez de dejar el día en
        'rechazada' con los datos de la solicitud descartada -- de lo
        contrario, la aprobación original desaparecía sin dejar rastro en
        el mismo instante en que se pedía el cambio, antes incluso de que
        nadie decidiera nada sobre la nueva solicitud."""
        self.get(absence_id)
        with transaction(self._conn):
            row = self._conn.execute(
                "SELECT previous_day_type_id, previous_note FROM employee_absences WHERE id = ?",
                (absence_id,),
            ).fetchone()
            assert row is not None
            if row["previous_day_type_id"] is not None:
                self._conn.execute(
                    """
                    UPDATE employee_absences
                    SET day_type_id = ?, note = ?, status = 'aprobada',
                        previous_day_type_id = NULL, previous_note = NULL
                    WHERE id = ?
                    """,
                    (row["previous_day_type_id"], row["previous_note"] or "", absence_id),
                )
            else:
                self._conn.execute(
                    "UPDATE employee_absences SET status = 'rechazada' WHERE id = ?",
                    (absence_id,),
                )
        return self.get(absence_id)

    def list_pending(self) -> list[EmployeeAbsence]:
        rows = self._conn.execute(
            "SELECT * FROM employee_absences WHERE status = 'pendiente' ORDER BY absence_date"
        ).fetchall()
        return [_row_to_employee_absence(row) for row in rows]

    def list_pending_for_department(self, department_id: int) -> list[EmployeeAbsence]:
        rows = self._conn.execute(
            """
            SELECT employee_absences.*
            FROM employee_absences
            JOIN employees ON employees.id = employee_absences.employee_id
            WHERE employees.department_id = ? AND employee_absences.status = 'pendiente'
            ORDER BY employee_absences.absence_date
            """,
            (department_id,),
        ).fetchall()
        return [_row_to_employee_absence(row) for row in rows]

    def get_for_month(
        self, employee_id: int, year: int, month: int
    ) -> dict[date, EmployeeAbsence]:
        # Only approved absences resolve the calendar's confirmed state --
        # a pending request must not silently show up as a real day off,
        # and mark_range()/set_day() (direct admin marking) always write
        # 'aprobada' anyway, so this excludes nothing for the pre-existing
        # direct-marking flow.
        start, end = _month_bounds(year, month)
        rows = self._conn.execute(
            """
            SELECT * FROM employee_absences
            WHERE employee_id = ? AND absence_date BETWEEN ? AND ? AND status = 'aprobada'
            """,
            (employee_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        items = [_row_to_employee_absence(row) for row in rows]
        return {item.absence_date: item for item in items}

    def list_for_department_month(
        self, department_id: int, year: int, month: int
    ) -> list[EmployeeAbsence]:
        start, end = _month_bounds(year, month)
        rows = self._conn.execute(
            """
            SELECT employee_absences.*
            FROM employee_absences
            JOIN employees ON employees.id = employee_absences.employee_id
            WHERE employees.department_id = ?
              AND employee_absences.absence_date BETWEEN ? AND ?
              AND employee_absences.status = 'aprobada'
            """,
            (department_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        return [_row_to_employee_absence(row) for row in rows]

    def list_for_date(self, day: date) -> list[EmployeeAbsence]:
        rows = self._conn.execute(
            "SELECT * FROM employee_absences WHERE absence_date = ? AND status = 'aprobada'",
            (day.isoformat(),),
        ).fetchall()
        return [_row_to_employee_absence(row) for row in rows]

    def count_vacation_days_for_year(self, employee_id: int, year: int) -> int:
        # Joins against day_types.is_vacation rather than matching the
        # "Vacaciones" name directly -- the flag survives a rename, the
        # hardcoded name wouldn't. Only approved days count as "used".
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM employee_absences
            JOIN day_types ON day_types.id = employee_absences.day_type_id
            WHERE employee_absences.employee_id = ? AND day_types.is_vacation = 1
              AND employee_absences.status = 'aprobada'
              AND employee_absences.absence_date BETWEEN ? AND ?
            """,
            (employee_id, date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()),
        ).fetchone()
        return int(row["cnt"])

    def list_all_for_employee(self, employee_id: int) -> list[EmployeeAbsence]:
        # Para exportación RGPD: todo el historial sin filtrar por estado ni
        # rango de fechas, a diferencia de get_for_month/list_for_date que
        # solo muestran ausencias aprobadas de un periodo concreto.
        rows = self._conn.execute(
            "SELECT * FROM employee_absences WHERE employee_id = ? ORDER BY absence_date",
            (employee_id,),
        ).fetchall()
        return [_row_to_employee_absence(row) for row in rows]


def _row_to_candidate(row: sqlite3.Row) -> Candidate:
    return Candidate(
        id=row["id"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        email=row["email"],
        phone=row["phone"],
        position=row["position"],
        department_id=row["department_id"],
        phase=row["phase"],
        notes=row["notes"],
        created_at=date.fromisoformat(row["created_at"]),
    )


class CandidateRepository:
    """Seguimiento ligero de candidatos antes de contratar -- deliberadamente
    sin un selector de vacantes propio: `position` es texto libre, igual
    que Employee.position, y `department_id` sirve tanto para agrupar "por
    vacante" como para el alcance por rol de un encargado. A diferencia de
    Employee.email, el email de un candidato NO es único: la misma persona
    puede volver a presentarse a otra vacante, o a la misma más adelante."""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def _validate(self, data: CandidateInput) -> _ValidatedCandidate:
        first_name = validation.validate_required_text(data.first_name, "nombre")
        last_name = validation.validate_required_text(data.last_name, "apellido")
        email = validation.validate_email(data.email)
        phone = validation.validate_phone(data.phone)
        position = validation.validate_required_text(data.position, "puesto")
        phase = validation.validate_candidate_phase(data.phase)
        notes = validation.validate_note(data.notes)
        if (
            self._conn.execute(
                "SELECT 1 FROM departments WHERE id = ?", (data.department_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el departamento con id {data.department_id}")
        return _ValidatedCandidate(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            position=position,
            phase=phase,
            notes=notes,
        )

    def create(self, data: CandidateInput) -> Candidate:
        v = self._validate(data)
        created_at = date.today()
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO candidates
                    (first_name, last_name, email, phone, position, department_id,
                     phase, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    v.first_name,
                    v.last_name,
                    v.email,
                    v.phone,
                    v.position,
                    data.department_id,
                    v.phase,
                    v.notes,
                    created_at.isoformat(),
                ),
            )
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def update(self, candidate_id: int, data: CandidateInput) -> Candidate:
        self.get(candidate_id)
        v = self._validate(data)
        with transaction(self._conn):
            self._conn.execute(
                """
                UPDATE candidates SET
                    first_name = ?, last_name = ?, email = ?, phone = ?, position = ?,
                    department_id = ?, phase = ?, notes = ?
                WHERE id = ?
                """,
                (
                    v.first_name,
                    v.last_name,
                    v.email,
                    v.phone,
                    v.position,
                    data.department_id,
                    v.phase,
                    v.notes,
                    candidate_id,
                ),
            )
        return self.get(candidate_id)

    def get(self, candidate_id: int) -> Candidate:
        row = self._conn.execute(
            "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el candidato con id {candidate_id}")
        return _row_to_candidate(row)

    def list_all(
        self, department_id: int | None = None, phase: str | None = None
    ) -> list[Candidate]:
        conditions = []
        params: list[object] = []
        if department_id is not None:
            conditions.append("department_id = ?")
            params.append(department_id)
        if phase is not None:
            conditions.append("phase = ?")
            params.append(phase)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._conn.execute(
            f"SELECT * FROM candidates {where} ORDER BY created_at DESC, id DESC", params
        ).fetchall()
        return [_row_to_candidate(row) for row in rows]

    def delete(self, candidate_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute("DELETE FROM candidates WHERE id = ?", (candidate_id,))
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el candidato con id {candidate_id}")


def working_weekdays_for_shift(shift: Shift | None) -> frozenset[int]:
    return shift.days_of_week if shift is not None else _DEFAULT_WORKING_WEEKDAYS


class DailyAssignmentRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def _ensure_employee_and_shift(self, employee_id: int, shift_id: int) -> None:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        if self._conn.execute("SELECT 1 FROM shifts WHERE id = ?", (shift_id,)).fetchone() is None:
            raise NotFoundError(f"no existe el turno con id {shift_id}")

    def set_day(self, employee_id: int, day: date, shift_id: int | None) -> None:
        with transaction(self._conn):
            if shift_id is None:
                self._conn.execute(
                    "DELETE FROM daily_shift_assignments "
                    "WHERE employee_id = ? AND assignment_date = ?",
                    (employee_id, day.isoformat()),
                )
                return
            self._ensure_employee_and_shift(employee_id, shift_id)
            self._conn.execute(
                """
                INSERT INTO daily_shift_assignments (employee_id, assignment_date, shift_id)
                VALUES (?, ?, ?)
                ON CONFLICT(employee_id, assignment_date) DO UPDATE SET
                    shift_id = excluded.shift_id
                """,
                (employee_id, day.isoformat(), shift_id),
            )

    def apply_shift_to_range(
        self, employee_id: int, shift_id: int, start: date, end: date
    ) -> MarkRangeResult:
        """Rellena [start, end] con `shift_id` en los días que coincidan con el
        patrón semanal propio del turno (shift.days_of_week); el resto se omite."""
        validation.validate_date_range(start, end)
        self._ensure_employee_and_shift(employee_id, shift_id)
        shift_row = self._conn.execute(
            "SELECT days_of_week FROM shifts WHERE id = ?", (shift_id,)
        ).fetchone()
        assert shift_row is not None  # just checked by _ensure_employee_and_shift
        weekdays = _parse_days_of_week(shift_row["days_of_week"])

        marked = 0
        skipped = 0
        with transaction(self._conn):
            current = start
            while current <= end:
                if current.isoweekday() in weekdays:
                    self._conn.execute(
                        """
                        INSERT INTO daily_shift_assignments
                            (employee_id, assignment_date, shift_id)
                        VALUES (?, ?, ?)
                        ON CONFLICT(employee_id, assignment_date) DO UPDATE SET
                            shift_id = excluded.shift_id
                        """,
                        (employee_id, current.isoformat(), shift_id),
                    )
                    marked += 1
                else:
                    skipped += 1
                current += timedelta(days=1)
        return MarkRangeResult(marked=marked, skipped=skipped)

    def apply_rotation_to_range(
        self, employee_id: int, pattern: Sequence[int | None], start: date, end: date
    ) -> MarkRangeResult:
        """Cicla `pattern` (turnos, o None para descanso) día a día desde
        `start` hasta `end` -- p. ej. [mañana, tarde, noche, None] cubre un
        patrón 3-turnos-1-descanso que se repite ('envuelve') tantas veces
        como haga falta para llenar el rango. A diferencia de
        apply_shift_to_range() (UN turno respetando SU propio days_of_week),
        aquí es la posición dentro de `pattern` la que decide qué toca cada
        día, sin mirar el days_of_week de nada; no se guarda el patrón en
        ningún sitio, solo su resultado día a día (ver Objective #20 en el
        roadmap: no hace falta una entidad "plantilla" reutilizable)."""
        validation.validate_date_range(start, end)
        if not pattern:
            raise validation.ValidationError("patron", "debe contener al menos un turno")
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        distinct_shift_ids = {shift_id for shift_id in pattern if shift_id is not None}
        for sid in distinct_shift_ids:
            if self._conn.execute("SELECT 1 FROM shifts WHERE id = ?", (sid,)).fetchone() is None:
                raise NotFoundError(f"no existe el turno con id {sid}")

        marked = 0
        skipped = 0
        with transaction(self._conn):
            current = start
            i = 0
            while current <= end:
                shift_id = pattern[i % len(pattern)]
                if shift_id is None:
                    self._conn.execute(
                        "DELETE FROM daily_shift_assignments "
                        "WHERE employee_id = ? AND assignment_date = ?",
                        (employee_id, current.isoformat()),
                    )
                    skipped += 1
                else:
                    self._conn.execute(
                        """
                        INSERT INTO daily_shift_assignments
                            (employee_id, assignment_date, shift_id)
                        VALUES (?, ?, ?)
                        ON CONFLICT(employee_id, assignment_date) DO UPDATE SET
                            shift_id = excluded.shift_id
                        """,
                        (employee_id, current.isoformat(), shift_id),
                    )
                    marked += 1
                current += timedelta(days=1)
                i += 1
        return MarkRangeResult(marked=marked, skipped=skipped)

    def get_for_month(
        self, employee_id: int, year: int, month: int
    ) -> dict[date, DailyShiftAssignment]:
        start, end = _month_bounds(year, month)
        rows = self._conn.execute(
            """
            SELECT * FROM daily_shift_assignments
            WHERE employee_id = ? AND assignment_date BETWEEN ? AND ?
            """,
            (employee_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        items = [_row_to_daily_assignment(row) for row in rows]
        return {item.assignment_date: item for item in items}

    def get_for_department_month(
        self, department_id: int, year: int, month: int
    ) -> list[DailyShiftAssignment]:
        start, end = _month_bounds(year, month)
        rows = self._conn.execute(
            """
            SELECT daily_shift_assignments.*
            FROM daily_shift_assignments
            JOIN employees ON employees.id = daily_shift_assignments.employee_id
            WHERE employees.department_id = ?
              AND daily_shift_assignments.assignment_date BETWEEN ? AND ?
            """,
            (department_id, start.isoformat(), end.isoformat()),
        ).fetchall()
        return [_row_to_daily_assignment(row) for row in rows]

    def list_all_for_employee(self, employee_id: int) -> list[DailyShiftAssignment]:
        rows = self._conn.execute(
            "SELECT * FROM daily_shift_assignments WHERE employee_id = ? "
            "ORDER BY assignment_date",
            (employee_id,),
        ).fetchall()
        return [_row_to_daily_assignment(row) for row in rows]


class PayrollSettingsRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def get(self) -> PayrollSettings:
        row = self._conn.execute(
            "SELECT ss_employee_pct, ss_employer_pct FROM payroll_settings WHERE id = 1"
        ).fetchone()
        if row is None:
            # init_db() always seeds this row; only reachable if called against a
            # connection that skipped init_db(), which is a programming error.
            return PayrollSettings(
                ss_employee_pct=DEFAULT_SS_EMPLOYEE_PCT,
                ss_employer_pct=DEFAULT_SS_EMPLOYER_PCT,
            )
        return PayrollSettings(
            ss_employee_pct=row["ss_employee_pct"], ss_employer_pct=row["ss_employer_pct"]
        )

    def update(self, ss_employee_pct: float, ss_employer_pct: float) -> PayrollSettings:
        clean_employee_pct = validation.validate_percentage(ss_employee_pct, "ss_trabajador")
        clean_employer_pct = validation.validate_percentage(ss_employer_pct, "ss_empresa")
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE payroll_settings SET ss_employee_pct = ?, ss_employer_pct = ? "
                "WHERE id = 1",
                (clean_employee_pct, clean_employer_pct),
            )
        return PayrollSettings(
            ss_employee_pct=clean_employee_pct, ss_employer_pct=clean_employer_pct
        )


def _row_to_payroll_record(row: sqlite3.Row) -> PayrollRecord:
    payroll = MonthlyPayroll(
        month=row["month"],
        year=row["year"],
        paga_ordinaria=row["paga_ordinaria"],
        paga_extra=row["paga_extra"],
        supplements_total=row["supplements_total"],
        exempt_supplements_total=row["exempt_supplements_total"],
        bruto_mes=row["bruto_mes"],
        irpf_pct=row["irpf_pct"],
        irpf_importe=row["irpf_importe"],
        ss_employee_pct=row["ss_employee_pct"],
        ss_employee_importe=row["ss_employee_importe"],
        advances_total=row["advances_total"],
        neto=row["neto"],
        ss_employer_pct=row["ss_employer_pct"],
        ss_employer_importe=row["ss_employer_importe"],
        coste_total_empresa=row["coste_total_empresa"],
    )
    return PayrollRecord(
        id=row["id"],
        employee_id=row["employee_id"],
        generated_at=datetime.fromisoformat(row["generated_at"]),
        annual_gross_salary_snapshot=row["annual_gross_salary_snapshot"],
        dependent_children_snapshot=row["dependent_children_snapshot"],
        payroll=payroll,
    )


class PayrollRecordRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def generate(
        self,
        employee_id: int,
        year: int,
        month: int,
        irpf_pct_override: float | None = None,
    ) -> PayrollRecord:
        """Calcula la nómina con el salario/hijos a cargo/% SS VIGENTES del
        empleado y los complementos/anticipos YA REGISTRADOS para ese
        empleado/mes, y la persiste como snapshot histórico. Si ya existía un
        registro para ese empleado/año/mes, lo sustituye (regenerar tras una
        corrección, o tras añadir un complemento a posteriori, es un caso de
        uso válido, no un error) -- un complemento añadido DESPUÉS de generar
        no altera silenciosamente el registro ya congelado, igual que un
        cambio de salario tampoco lo hace.

        irpf_pct_override, si se da, sustituye la estimación automática de
        IRPF por un valor real (p. ej. el que ya ha calculado una gestoría) --
        ver calculate_monthly_payroll() para el porqué. Validado con techo
        100%, no el 47% de MAX_TIPO_RETENCION_PCT (ese tope es solo de la
        estimación interna)."""
        employee_row = self._conn.execute(
            "SELECT salary, dependent_children FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
        if employee_row is None:
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        if irpf_pct_override is not None:
            irpf_pct_override = validation.validate_percentage(irpf_pct_override, "irpf")
        settings_row = self._conn.execute(
            "SELECT ss_employee_pct, ss_employer_pct FROM payroll_settings WHERE id = 1"
        ).fetchone()
        ss_employee_pct = (
            settings_row["ss_employee_pct"] if settings_row else DEFAULT_SS_EMPLOYEE_PCT
        )
        ss_employer_pct = (
            settings_row["ss_employer_pct"] if settings_row else DEFAULT_SS_EMPLOYER_PCT
        )
        supplements_total, exempt_supplements_total, advances_total = PayrollSupplementRepository(
            self._conn
        ).totals_for_employee_month(employee_id, year, month)

        payroll = calculate_monthly_payroll(
            annual_gross_salary=employee_row["salary"],
            dependent_children=employee_row["dependent_children"],
            ss_employee_pct=ss_employee_pct,
            ss_employer_pct=ss_employer_pct,
            month=month,
            year=year,
            supplements_total=supplements_total,
            exempt_supplements_total=exempt_supplements_total,
            advances_total=advances_total,
            irpf_pct_override=irpf_pct_override,
        )
        generated_at = datetime.now().replace(microsecond=0)
        with transaction(self._conn):
            self._conn.execute(
                """
                INSERT INTO payroll_records (
                    employee_id, year, month, generated_at,
                    annual_gross_salary_snapshot, dependent_children_snapshot,
                    paga_ordinaria, paga_extra, supplements_total, exempt_supplements_total,
                    bruto_mes, irpf_pct,
                    irpf_importe, ss_employee_pct, ss_employee_importe, advances_total, neto,
                    ss_employer_pct, ss_employer_importe, coste_total_empresa
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_id, year, month) DO UPDATE SET
                    generated_at = excluded.generated_at,
                    annual_gross_salary_snapshot = excluded.annual_gross_salary_snapshot,
                    dependent_children_snapshot = excluded.dependent_children_snapshot,
                    paga_ordinaria = excluded.paga_ordinaria,
                    paga_extra = excluded.paga_extra,
                    supplements_total = excluded.supplements_total,
                    exempt_supplements_total = excluded.exempt_supplements_total,
                    bruto_mes = excluded.bruto_mes,
                    irpf_pct = excluded.irpf_pct,
                    irpf_importe = excluded.irpf_importe,
                    ss_employee_pct = excluded.ss_employee_pct,
                    ss_employee_importe = excluded.ss_employee_importe,
                    advances_total = excluded.advances_total,
                    neto = excluded.neto,
                    ss_employer_pct = excluded.ss_employer_pct,
                    ss_employer_importe = excluded.ss_employer_importe,
                    coste_total_empresa = excluded.coste_total_empresa
                """,
                (
                    employee_id,
                    year,
                    month,
                    generated_at.isoformat(timespec="seconds"),
                    employee_row["salary"],
                    employee_row["dependent_children"],
                    payroll.paga_ordinaria,
                    payroll.paga_extra,
                    payroll.supplements_total,
                    payroll.exempt_supplements_total,
                    payroll.bruto_mes,
                    payroll.irpf_pct,
                    payroll.irpf_importe,
                    payroll.ss_employee_pct,
                    payroll.ss_employee_importe,
                    payroll.advances_total,
                    payroll.neto,
                    payroll.ss_employer_pct,
                    payroll.ss_employer_importe,
                    payroll.coste_total_empresa,
                ),
            )
        found = self.get(employee_id, year, month)
        assert found is not None  # just inserted/updated above
        return found

    def get(self, employee_id: int, year: int, month: int) -> PayrollRecord | None:
        row = self._conn.execute(
            "SELECT * FROM payroll_records WHERE employee_id = ? AND year = ? AND month = ?",
            (employee_id, year, month),
        ).fetchone()
        return _row_to_payroll_record(row) if row is not None else None

    def generate_for_employees(
        self, employee_ids: Sequence[int], year: int, month: int
    ) -> PayrollBulkGenerateResult:
        """Genera la nómina automática (sin irpf_pct_override) de year/month
        para cada id de employee_ids que TODAVÍA no tenga una ya generada
        para ese mes; si ya existe, se omite sin tocarla -- puede tener un %
        de IRPF puesto a mano por GeneratePayrollDialog que no debe
        descartarse en silencio.

        Cada empleado se procesa de forma independiente -- generate() hace
        su propio commit por dentro, así que envolver este bucle en un with
        transaction() exterior no daría atomicidad real (nada que deshacer,
        ya se ha comprometido) y un fallo a mitad de la lista no afecta a lo
        ya generado para los anteriores. Un id que ya no exista (borrado por
        otra sesión desde que se leyó la lista mostrada en pantalla -- mismo
        escenario que ya contempla reload_departments()) cuenta como
        omitido, no como error."""
        generated = 0
        skipped = 0
        for employee_id in employee_ids:
            if self.get(employee_id, year, month) is not None:
                skipped += 1
                continue
            try:
                self.generate(employee_id, year, month)
            except NotFoundError:
                skipped += 1
                continue
            generated += 1
        return PayrollBulkGenerateResult(generated=generated, skipped=skipped)

    def list_for_employee(self, employee_id: int) -> list[PayrollRecord]:
        rows = self._conn.execute(
            "SELECT * FROM payroll_records WHERE employee_id = ? ORDER BY year, month",
            (employee_id,),
        ).fetchall()
        return [_row_to_payroll_record(row) for row in rows]

    def delete(self, employee_id: int, year: int, month: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM payroll_records WHERE employee_id = ? AND year = ? AND month = ?",
                (employee_id, year, month),
            )
        if cursor.rowcount == 0:
            raise NotFoundError("no existe una nómina generada para ese empleado/año/mes")

    def list_for_month(
        self, year: int, month: int, department_id: int | None = None
    ) -> list[PayrollRecord]:
        """Todas las nóminas YA GENERADAS de un año/mes concreto, sin
        importar el empleado -- pensado para una vista agregada de todo el
        mes (ej. la exportación SEPA de pago de nóminas), a diferencia de
        list_for_employee() que mira a un único empleado a lo largo del
        tiempo. Mismo criterio que monthly_totals()/department_totals():
        solo nóminas generadas, nunca una estimación en vivo."""
        params: list[object] = [year, month]
        department_filter = ""
        if department_id is not None:
            department_filter = "AND e.department_id = ?"
            params.append(department_id)
        rows = self._conn.execute(
            f"""
            SELECT pr.* FROM payroll_records pr
            JOIN employees e ON e.id = pr.employee_id
            WHERE pr.year = ? AND pr.month = ? {department_filter}
            ORDER BY e.first_name, e.last_name
            """,
            params,
        ).fetchall()
        return [_row_to_payroll_record(row) for row in rows]

    def monthly_totals(
        self, year: int, department_id: int | None = None
    ) -> list[MonthlyCostSummary]:
        """Coste de personal agregado mes a mes (12 filas, enero-diciembre)
        para `year`, a partir de las nóminas ya generadas -- ver docstring
        de MonthlyCostSummary. Siempre devuelve los 12 meses, con ceros en
        los que no tengan ninguna nómina generada, para que un hueco se vea
        como un hueco en vez de faltar la fila entera."""
        params: list[object] = [year]
        department_filter = ""
        if department_id is not None:
            department_filter = "AND e.department_id = ?"
            params.append(department_id)
        rows = self._conn.execute(
            f"""
            SELECT pr.month AS month,
                   COALESCE(SUM(pr.bruto_mes), 0) AS total_gross,
                   COALESCE(SUM(pr.coste_total_empresa), 0) AS total_employer_cost,
                   COUNT(*) AS payroll_count
            FROM payroll_records pr
            JOIN employees e ON e.id = pr.employee_id
            WHERE pr.year = ? {department_filter}
            GROUP BY pr.month
            """,
            params,
        ).fetchall()
        by_month = {row["month"]: row for row in rows}
        return [
            MonthlyCostSummary(
                year=year,
                month=month,
                total_gross=(
                    float(by_month[month]["total_gross"]) if month in by_month else 0.0
                ),
                total_employer_cost=(
                    float(by_month[month]["total_employer_cost"])
                    if month in by_month
                    else 0.0
                ),
                payroll_count=by_month[month]["payroll_count"] if month in by_month else 0,
            )
            for month in range(1, 13)
        ]

    def department_totals(
        self, year: int, month: int, department_id: int | None = None
    ) -> list[DepartmentCostSummary]:
        """Coste de personal agregado por departamento para un año/mes
        concretos -- ver docstring de DepartmentCostSummary sobre la
        limitación del departamento actual frente al histórico. LEFT JOIN
        desde departments para que uno sin ninguna nómina generada ese mes
        siga apareciendo con ceros, en vez de desaparecer de la lista."""
        params: list[object] = [year, month]
        department_where = ""
        if department_id is not None:
            department_where = "WHERE d.id = ?"
            params.append(department_id)
        rows = self._conn.execute(
            f"""
            SELECT d.id AS department_id, d.name AS department_name,
                   COALESCE(SUM(pr.bruto_mes), 0) AS total_gross,
                   COALESCE(SUM(pr.coste_total_empresa), 0) AS total_employer_cost,
                   COUNT(pr.id) AS payroll_count
            FROM departments d
            LEFT JOIN employees e ON e.department_id = d.id
            LEFT JOIN payroll_records pr
                ON pr.employee_id = e.id AND pr.year = ? AND pr.month = ?
            {department_where}
            GROUP BY d.id, d.name
            ORDER BY d.name
            """,
            params,
        ).fetchall()
        return [
            DepartmentCostSummary(
                department_id=row["department_id"],
                department_name=row["department_name"],
                total_gross=float(row["total_gross"]),
                total_employer_cost=float(row["total_employer_cost"]),
                payroll_count=row["payroll_count"],
            )
            for row in rows
        ]


def _row_to_payroll_supplement(row: sqlite3.Row) -> PayrollSupplement:
    return PayrollSupplement(
        id=row["id"],
        employee_id=row["employee_id"],
        year=row["year"],
        month=row["month"],
        supplement_type=row["supplement_type"],
        description=row["description"],
        amount=row["amount"],
        hours=row["hours"],
        rate_per_hour=row["rate_per_hour"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class PayrollSupplementRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(
        self,
        employee_id: int,
        year: int,
        month: int,
        supplement_type: str,
        description: str,
        amount: float = 0.0,
        hours: float | None = None,
        rate_per_hour: float | None = None,
    ) -> PayrollSupplement:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")
        if not 1 <= month <= 12:
            raise validation.ValidationError("mes", "fuera de rango (1-12)")
        clean_type = validation.validate_supplement_type(supplement_type)
        clean_description = validation.validate_required_text(description, "descripción")

        if clean_type == "horas_extra":
            if hours is None or rate_per_hour is None:
                raise validation.ValidationError(
                    "horas", "las horas extra requieren horas y precio por hora"
                )
            clean_hours, clean_rate = validation.validate_overtime_hours_and_rate(
                hours, rate_per_hour
            )
            clean_amount = round(clean_hours * clean_rate, 2)
        else:
            if hours is not None or rate_per_hour is not None:
                raise validation.ValidationError(
                    "horas", "solo las horas extra llevan horas/precio por hora"
                )
            clean_hours, clean_rate = None, None
            clean_amount = validation.validate_supplement_amount(amount)

        created_at = datetime.now().replace(microsecond=0)
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO payroll_supplements
                    (employee_id, year, month, supplement_type, description, amount,
                     hours, rate_per_hour, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    year,
                    month,
                    clean_type,
                    clean_description,
                    clean_amount,
                    clean_hours,
                    clean_rate,
                    created_at.isoformat(timespec="seconds"),
                ),
            )
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def get(self, supplement_id: int) -> PayrollSupplement:
        row = self._conn.execute(
            "SELECT * FROM payroll_supplements WHERE id = ?", (supplement_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el complemento con id {supplement_id}")
        return _row_to_payroll_supplement(row)

    def list_for_employee_month(
        self, employee_id: int, year: int, month: int
    ) -> list[PayrollSupplement]:
        rows = self._conn.execute(
            """
            SELECT * FROM payroll_supplements
            WHERE employee_id = ? AND year = ? AND month = ?
            ORDER BY created_at
            """,
            (employee_id, year, month),
        ).fetchall()
        return [_row_to_payroll_supplement(row) for row in rows]

    def totals_for_employee_month(
        self, employee_id: int, year: int, month: int
    ) -> tuple[float, float, float]:
        """(supplements_total, exempt_supplements_total, advances_total):
        pluses+horas_extra+bonos (sujetos a IRPF/SS) aparte de las dietas
        (no sujetas -- ver el docstring de calculate_monthly_payroll()) y
        aparte de los anticipos, listos para pasar directamente a
        calculate_monthly_payroll()."""
        entries = self.list_for_employee_month(employee_id, year, month)
        supplements = sum(
            e.amount for e in entries if e.supplement_type in ("plus", "horas_extra", "bonos")
        )
        exempt_supplements = sum(e.amount for e in entries if e.supplement_type == "dietas")
        advances = sum(e.amount for e in entries if e.supplement_type == "anticipo")
        return round(supplements, 2), round(exempt_supplements, 2), round(advances, 2)

    def list_all_for_employee(self, employee_id: int) -> list[PayrollSupplement]:
        rows = self._conn.execute(
            "SELECT * FROM payroll_supplements WHERE employee_id = ? ORDER BY created_at",
            (employee_id,),
        ).fetchall()
        return [_row_to_payroll_supplement(row) for row in rows]

    def delete(self, supplement_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM payroll_supplements WHERE id = ?", (supplement_id,)
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el complemento con id {supplement_id}")


# PBKDF2-HMAC-SHA256 with a per-user random salt: no external dependency
# (bcrypt/argon2 would need one), constant-time comparison on verify, and a
# modern iteration count (~50ms/hash on this machine -- see _hash_password).
_PBKDF2_ITERATIONS = 260_000


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        created_at=date.fromisoformat(row["created_at"]),
        role=row["role"],
        department_id=row["department_id"],
        email_provider=row["email_provider"],
        email_address=row["email_address"],
        last_digest_sent_at=(
            datetime.fromisoformat(row["last_digest_sent_at"])
            if row["last_digest_sent_at"] is not None
            else None
        ),
        receive_crash_reports=bool(row["receive_crash_reports"]),
    )


def _row_to_time_entry(row: sqlite3.Row) -> TimeClockEntry:
    return TimeClockEntry(
        id=row["id"],
        employee_id=row["employee_id"],
        entry_type=row["entry_type"],
        entry_timestamp=datetime.fromisoformat(row["entry_timestamp"]),
        note=row["note"],
    )


class UserRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def create(
        self,
        username: str,
        password: str,
        role: str = "admin",
        department_id: int | None = None,
    ) -> User:
        clean_username = validation.validate_username(username)
        clean_password = validation.validate_password(password)
        clean_role, clean_department_id = validation.validate_user_role_and_department(
            role, department_id
        )
        if clean_department_id is not None and (
            self._conn.execute(
                "SELECT 1 FROM departments WHERE id = ?", (clean_department_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el departamento con id {clean_department_id}")
        salt = secrets.token_bytes(16)
        password_hash = _hash_password(clean_password, salt)
        try:
            with transaction(self._conn):
                cursor = self._conn.execute(
                    """
                    INSERT INTO users
                        (username, password_hash, salt, created_at, role, department_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_username,
                        password_hash.hex(),
                        salt.hex(),
                        date.today().isoformat(),
                        clean_role,
                        clean_department_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateError(f"ya existe un usuario llamado '{clean_username}'") from exc
        return User(
            id=cursor.lastrowid,
            username=clean_username,
            created_at=date.today(),
            role=clean_role,
            department_id=clean_department_id,
            email_provider=None,
            email_address=None,
            last_digest_sent_at=None,
            receive_crash_reports=False,
        )

    def list_all(self) -> list[User]:
        rows = self._conn.execute(
            "SELECT * FROM users ORDER BY username"
        ).fetchall()
        return [_row_to_user(row) for row in rows]

    def delete(self, user_id: int, current_user_id: int | None = None) -> None:
        # El guard de "no borrarte a ti mismo" vivía solo en
        # UserManagerDialog, no aquí -- a diferencia del guard del "último
        # administrador", que sí estaba blindado a este nivel. Hoy no hay
        # otra ruta en el código que llegue aquí sin pasar por ese diálogo,
        # pero es el mismo patrón de riesgo que dejó pasar el hallazgo del
        # borrado de departamentos: una protección que solo vive en la UI.
        # current_user_id=None (valor por defecto) deja pasar cualquier
        # borrado sin comprobar esto -- solo lo comprueban los llamantes
        # que de verdad conocen la sesión activa (la UI).
        if current_user_id is not None and user_id == current_user_id:
            raise RepositoryError("no puedes eliminar tu propio usuario")
        row = self._conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el usuario con id {user_id}")
        if row["role"] == "admin":
            admin_count = self._conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin'"
            ).fetchone()[0]
            if admin_count <= 1:
                raise RepositoryError(
                    "no se puede eliminar: debe quedar al menos un administrador"
                )
        with transaction(self._conn):
            self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    def authenticate(self, username: str, password: str) -> User | None:
        """Ni el usuario ni la contraseña se validan con validate_username/
        validate_password aquí: un intento de acceso es una comparación
        contra datos existentes, no una creación, así que cualquier entrada
        (incluida una con formato inválido) simplemente no encuentra
        coincidencia en vez de lanzar un error distinto que revele por qué."""
        # Sin COLLATE NOCASE aquí a propósito: users.username ya es
        # case-insensitive a nivel de esquema (COLLATE NOCASE en SQLite,
        # CITEXT en Postgres, ver database.py) -- repetirlo en la consulta
        # es redundante en SQLite e inválido en Postgres (no existe una
        # colación "nocase" ahí).
        row = self._conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username.strip(),),
        ).fetchone()
        if row is None:
            return None
        expected_hash = bytes.fromhex(row["password_hash"])
        salt = bytes.fromhex(row["salt"])
        actual_hash = _hash_password(password, salt)
        if not hmac.compare_digest(actual_hash, expected_hash):
            return None
        return _row_to_user(row)

    def change_own_password(
        self, user_id: int, current_password: str, new_password: str
    ) -> None:
        """Autoservicio: exige la contraseña actual (no una acción que un
        admin pueda hacerle a otro usuario sin conocerla -- para eso está
        borrar y crear de nuevo, ya existente), igual que cambiar la
        contraseña en cualquier cuenta real."""
        row = self._conn.execute(
            "SELECT password_hash, salt FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el usuario con id {user_id}")
        expected_hash = bytes.fromhex(row["password_hash"])
        salt = bytes.fromhex(row["salt"])
        if not hmac.compare_digest(_hash_password(current_password, salt), expected_hash):
            raise RepositoryError("la contraseña actual no es correcta")
        clean_password = validation.validate_password(new_password)
        new_salt = secrets.token_bytes(16)
        new_hash = _hash_password(clean_password, new_salt)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                (new_hash.hex(), new_salt.hex(), user_id),
            )

    def set_email_connection(
        self, user_id: int, provider: str, address: str, app_password: str
    ) -> None:
        clean_provider = validation.validate_email_provider(provider)
        clean_address = validation.validate_email(address)
        clean_password = validation.validate_app_password(app_password)
        with transaction(self._conn):
            cursor = self._conn.execute(
                "UPDATE users SET email_provider = ?, email_address = ?, "
                "email_app_password = ? WHERE id = ?",
                (clean_provider, clean_address, clean_password, user_id),
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el usuario con id {user_id}")

    def get_email_connection(self, user_id: int) -> EmailConnection | None:
        row = self._conn.execute(
            "SELECT email_provider, email_address, email_app_password FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el usuario con id {user_id}")
        if row["email_provider"] is None:
            return None
        return EmailConnection(
            provider=row["email_provider"],
            address=row["email_address"],
            app_password=row["email_app_password"],
        )

    def clear_email_connection(self, user_id: int) -> None:
        # receive_crash_reports también se resetea aquí: dejarlo en 1 sin
        # correo conectado sería un estado a medias (el aviso de fallo no
        # tiene a dónde enviarse) que además confundiría a quien vuelva a
        # "Mi cuenta..." más tarde y encuentre la casilla marcada sin saber
        # por qué ya no le llega nada.
        with transaction(self._conn):
            cursor = self._conn.execute(
                "UPDATE users SET email_provider = NULL, email_address = NULL, "
                "email_app_password = NULL, receive_crash_reports = 0 WHERE id = ?",
                (user_id,),
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el usuario con id {user_id}")

    def set_receive_crash_reports(self, user_id: int, enabled: bool) -> None:
        """Suscripción independiente del resumen semanal: activarla exige
        tener ya un correo conectado (reutiliza esa misma conexión para
        enviar el aviso), pero tener el resumen activado no activa esto
        automáticamente ni viceversa."""
        if enabled:
            row = self._conn.execute(
                "SELECT email_provider FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(f"no existe el usuario con id {user_id}")
            if row["email_provider"] is None:
                raise RepositoryError(
                    'conecta un correo en "Mi cuenta..." antes de activar '
                    "los avisos de fallo"
                )
        with transaction(self._conn):
            cursor = self._conn.execute(
                "UPDATE users SET receive_crash_reports = ? WHERE id = ?",
                (1 if enabled else 0, user_id),
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el usuario con id {user_id}")

    def list_crash_report_recipients(self) -> list[EmailConnection]:
        rows = self._conn.execute(
            "SELECT email_provider, email_address, email_app_password FROM users "
            "WHERE receive_crash_reports = 1 AND email_provider IS NOT NULL"
        ).fetchall()
        return [
            EmailConnection(
                provider=row["email_provider"],
                address=row["email_address"],
                app_password=row["email_app_password"],
            )
            for row in rows
        ]

    def mark_digest_sent(self, user_id: int, sent_at: datetime) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "UPDATE users SET last_digest_sent_at = ? WHERE id = ?",
                (sent_at.isoformat(timespec="seconds"), user_id),
            )
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el usuario con id {user_id}")

    def needs_weekly_digest(self, user_id: int, today: date) -> bool:
        """Un usuario "necesita" su resumen semanal si tiene correo
        conectado y no se le ha enviado ninguno en los últimos 7 días --
        mismo criterio de cadencia que has_backup_today() usa para las
        copias de seguridad, solo que semanal en vez de diario."""
        user = self.get(user_id)
        if user.email_provider is None:
            return False
        if user.last_digest_sent_at is None:
            return True
        return (today - user.last_digest_sent_at.date()).days >= 7

    def get(self, user_id: int) -> User:
        row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el usuario con id {user_id}")
        return _row_to_user(row)


class TimeEntryRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def _ensure_employee(self, employee_id: int) -> None:
        if (
            self._conn.execute(
                "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
            ).fetchone()
            is None
        ):
            raise NotFoundError(f"no existe el empleado con id {employee_id}")

    def _validate_alternation(
        self,
        employee_id: int,
        entry_type: str,
        timestamp: datetime,
        exclude_entry_id: int | None = None,
    ) -> None:
        """Los fichajes de un mismo empleado deben alternar estrictamente
        entrada/salida/entrada/... a lo largo de toda su línea temporal (no
        solo el último), para que una corrección manual insertada entre dos
        fichajes existentes no rompa la alternancia -- y para que un turno
        nocturno que cruza medianoche siga funcionando sin casos especiales
        por día. Se construye la lista hipotética completa (con el fichaje
        nuevo/editado ya insertado) y se recorre una vez comprobando que
        siempre empieza en 'entrada' y alterna sin repetir tipo."""
        rows = self._conn.execute(
            "SELECT id, entry_type, entry_timestamp FROM time_entries WHERE employee_id = ?",
            (employee_id,),
        ).fetchall()
        existing = [
            (row["entry_timestamp"], row["entry_type"])
            for row in rows
            if row["id"] != exclude_entry_id
        ]
        existing.append((timestamp.isoformat(timespec="seconds"), entry_type))
        existing.sort(key=lambda item: item[0])

        expected = "entrada"
        for _timestamp, actual_type in existing:
            if actual_type != expected:
                raise validation.ValidationError(
                    "fichaje",
                    "los fichajes deben alternar entrada/salida; "
                    "esta fecha/hora rompe el orden con otro fichaje ya registrado",
                )
            expected = "salida" if expected == "entrada" else "entrada"

    def clock(self, employee_id: int, entry_type: str, note: str = "") -> TimeClockEntry:
        """Ficha AHORA (entrada o salida) para un empleado -- uso tipo
        kiosko: el momento se captura aquí, no se recibe como parámetro."""
        self._ensure_employee(employee_id)
        clean_type = validation.validate_time_entry_type(entry_type)
        clean_note = validation.validate_note(note)
        timestamp = datetime.now().replace(microsecond=0)
        self._validate_alternation(employee_id, clean_type, timestamp)
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO time_entries (employee_id, entry_type, entry_timestamp, note)
                VALUES (?, ?, ?, ?)
                """,
                (employee_id, clean_type, timestamp.isoformat(timespec="seconds"), clean_note),
            )
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def create_manual(
        self, employee_id: int, entry_type: str, timestamp: datetime, note: str = ""
    ) -> TimeClockEntry:
        """Para correcciones administrativas: un fichaje con fecha/hora
        concretas en vez de 'ahora' (ej. alguien olvidó fichar)."""
        self._ensure_employee(employee_id)
        clean_type = validation.validate_time_entry_type(entry_type)
        clean_timestamp = validation.validate_time_entry_timestamp(timestamp)
        clean_note = validation.validate_note(note)
        self._validate_alternation(employee_id, clean_type, clean_timestamp)
        with transaction(self._conn):
            cursor = self._conn.execute(
                """
                INSERT INTO time_entries (employee_id, entry_type, entry_timestamp, note)
                VALUES (?, ?, ?, ?)
                """,
                (
                    employee_id,
                    clean_type,
                    clean_timestamp.isoformat(timespec="seconds"),
                    clean_note,
                ),
            )
        return self.get(cursor.lastrowid)  # type: ignore[arg-type]

    def update(
        self, entry_id: int, entry_type: str, timestamp: datetime, note: str = ""
    ) -> TimeClockEntry:
        existing = self.get(entry_id)
        clean_type = validation.validate_time_entry_type(entry_type)
        clean_timestamp = validation.validate_time_entry_timestamp(timestamp)
        clean_note = validation.validate_note(note)
        self._validate_alternation(
            existing.employee_id, clean_type, clean_timestamp, exclude_entry_id=entry_id
        )
        with transaction(self._conn):
            self._conn.execute(
                """
                UPDATE time_entries SET entry_type = ?, entry_timestamp = ?, note = ?
                WHERE id = ?
                """,
                (
                    clean_type,
                    clean_timestamp.isoformat(timespec="seconds"),
                    clean_note,
                    entry_id,
                ),
            )
        return self.get(entry_id)

    def delete(self, entry_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute("DELETE FROM time_entries WHERE id = ?", (entry_id,))
        if cursor.rowcount == 0:
            raise NotFoundError(f"no existe el fichaje con id {entry_id}")

    def get(self, entry_id: int) -> TimeClockEntry:
        row = self._conn.execute(
            "SELECT * FROM time_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"no existe el fichaje con id {entry_id}")
        return _row_to_time_entry(row)

    def last_entry_for_employee(self, employee_id: int) -> TimeClockEntry | None:
        """Último fichaje de un empleado por fecha/hora -- indica si está
        actualmente fichado (tipo 'entrada') o no (tipo 'salida' o ninguno)."""
        row = self._conn.execute(
            """
            SELECT * FROM time_entries WHERE employee_id = ?
            ORDER BY entry_timestamp DESC LIMIT 1
            """,
            (employee_id,),
        ).fetchone()
        return _row_to_time_entry(row) if row is not None else None

    def list_for_month(self, employee_id: int, year: int, month: int) -> list[TimeClockEntry]:
        start, end = _month_bounds(year, month)
        start_ts = datetime.combine(start, datetime.min.time()).isoformat(timespec="seconds")
        end_ts = datetime.combine(end, datetime.max.time()).isoformat(timespec="seconds")
        rows = self._conn.execute(
            """
            SELECT * FROM time_entries WHERE employee_id = ?
              AND entry_timestamp BETWEEN ? AND ?
            ORDER BY entry_timestamp
            """,
            (employee_id, start_ts, end_ts),
        ).fetchall()
        return [_row_to_time_entry(row) for row in rows]

    def list_for_date(self, day: date) -> list[TimeClockEntry]:
        start_ts = datetime.combine(day, datetime.min.time()).isoformat(timespec="seconds")
        end_ts = datetime.combine(day, datetime.max.time()).isoformat(timespec="seconds")
        rows = self._conn.execute(
            """
            SELECT * FROM time_entries WHERE entry_timestamp BETWEEN ? AND ?
            ORDER BY entry_timestamp
            """,
            (start_ts, end_ts),
        ).fetchall()
        return [_row_to_time_entry(row) for row in rows]

    def list_all_for_employee(self, employee_id: int) -> list[TimeClockEntry]:
        rows = self._conn.execute(
            "SELECT * FROM time_entries WHERE employee_id = ? ORDER BY entry_timestamp",
            (employee_id,),
        ).fetchall()
        return [_row_to_time_entry(row) for row in rows]


class AppSettingsRepository:
    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn

    def get_theme_mode(self) -> str:
        row = self._conn.execute("SELECT theme_mode FROM app_settings WHERE id = 1").fetchone()
        if row is None:
            # init_db() always seeds this row; only reachable if called against a
            # connection that skipped init_db(), which is a programming error.
            return "light"
        return str(row["theme_mode"])

    def set_theme_mode(self, mode: str) -> None:
        clean_mode = validation.validate_theme_mode(mode)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE app_settings SET theme_mode = ? WHERE id = 1", (clean_mode,)
            )

    def get_annual_vacation_days(self) -> float:
        row = self._conn.execute(
            "SELECT annual_vacation_days FROM app_settings WHERE id = 1"
        ).fetchone()
        if row is None:
            # init_db() always seeds this row; only reachable if called against a
            # connection that skipped init_db(), which is a programming error.
            return 22.0
        return float(row["annual_vacation_days"])

    def set_annual_vacation_days(self, value: float) -> None:
        clean_value = validation.validate_annual_vacation_days(value)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE app_settings SET annual_vacation_days = ? WHERE id = 1", (clean_value,)
            )

    def get_data_retention_years(self) -> int:
        row = self._conn.execute(
            "SELECT data_retention_years FROM app_settings WHERE id = 1"
        ).fetchone()
        if row is None:
            # init_db() always seeds this row; only reachable if called against a
            # connection that skipped init_db(), which is a programming error.
            return 4
        return int(row["data_retention_years"])

    def set_data_retention_years(self, value: int) -> None:
        clean_value = validation.validate_data_retention_years(value)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE app_settings SET data_retention_years = ? WHERE id = 1", (clean_value,)
            )

    def get_company_name(self) -> str:
        row = self._conn.execute("SELECT company_name FROM app_settings WHERE id = 1").fetchone()
        if row is None:
            return ""
        return str(row["company_name"])

    def set_company_name(self, value: str) -> None:
        clean_value = validation.validate_company_name(value)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE app_settings SET company_name = ? WHERE id = 1", (clean_value,)
            )

    def get_company_iban(self) -> str:
        row = self._conn.execute("SELECT company_iban FROM app_settings WHERE id = 1").fetchone()
        if row is None:
            return ""
        return str(row["company_iban"])

    def set_company_iban(self, value: str) -> None:
        clean_value = validation.validate_iban(value)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE app_settings SET company_iban = ? WHERE id = 1", (clean_value,)
            )

    def get_company_nif(self) -> str:
        row = self._conn.execute("SELECT company_nif FROM app_settings WHERE id = 1").fetchone()
        if row is None:
            return ""
        return str(row["company_nif"])

    def set_company_nif(self, value: str) -> None:
        clean_value = validation.validate_company_nif(value)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE app_settings SET company_nif = ? WHERE id = 1", (clean_value,)
            )

    def get_company_ccc(self) -> str:
        row = self._conn.execute("SELECT company_ccc FROM app_settings WHERE id = 1").fetchone()
        if row is None:
            return ""
        return str(row["company_ccc"])

    def set_company_ccc(self, value: str) -> None:
        clean_value = validation.validate_company_ccc(value)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE app_settings SET company_ccc = ? WHERE id = 1", (clean_value,)
            )

    def get_company_address(self) -> str:
        row = self._conn.execute(
            "SELECT company_address FROM app_settings WHERE id = 1"
        ).fetchone()
        if row is None:
            return ""
        return str(row["company_address"])

    def set_company_address(self, value: str) -> None:
        clean_value = validation.validate_company_address(value)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE app_settings SET company_address = ? WHERE id = 1", (clean_value,)
            )

    def get_last_update_check_at(self) -> datetime | None:
        row = self._conn.execute(
            "SELECT last_update_check_at FROM app_settings WHERE id = 1"
        ).fetchone()
        if row is None or row["last_update_check_at"] is None:
            return None
        return datetime.fromisoformat(str(row["last_update_check_at"]))

    def set_last_update_check_at(self, value: datetime) -> None:
        # Sin validation.py de por medio a propósito: es un valor generado
        # por el propio sistema (app/update_check.py), no entrada de
        # usuario -- mismo criterio que UserRepository.mark_digest_sent.
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE app_settings SET last_update_check_at = ? WHERE id = 1",
                (value.isoformat(timespec="seconds"),),
            )


def gather_alerts(
    repos: Repositories,
    department_id: int | None,
    today: date,
    within_days: int = DEFAULT_ALERT_WINDOW_DAYS,
) -> list[Alert]:
    """Junta las 7 categorías de alerta (ver alerts.py) a partir de los
    datos ya persistidos -- punto único para que AlertsPage.refresh(), el
    resumen semanal de main.py y WelcomePage.refresh() no puedan divergir
    silenciosamente en esta secuencia, antes duplicada byte a byte en las
    dos primeras. department_id es obligatorio (a diferencia de
    monthly_totals()/CandidateRepository.list_all(), que lo hacen
    opcional): esta función alimenta pantallas sensibles a departamento,
    así que un llamador debe elegir conscientemente None (toda la
    empresa) en vez de caer en ello por omitir el argumento."""
    employees = repos.employees.search(department_id=department_id)
    retention_years = repos.app_settings.get_data_retention_years()
    trainings = repos.trainings.list_all()
    categories = repos.professional_categories.list_all()
    return sorted(
        all_alerts(employees, today, within_days)
        + retention_review_alerts(employees, today, retention_years, within_days)
        + training_expiry_alerts(employees, trainings, today, within_days)
        + professional_category_minimum_salary_alerts(employees, categories, today),
        key=lambda a: a.target_date,
    )


@dataclass(frozen=True, slots=True)
class Repositories:
    departments: DepartmentRepository
    employees: EmployeeRepository
    shifts: ShiftRepository
    day_types: DayTypeRepository
    closures: DepartmentClosureRepository
    absences: EmployeeAbsenceRepository
    payroll_settings: PayrollSettingsRepository
    daily_assignments: DailyAssignmentRepository
    users: UserRepository
    app_settings: AppSettingsRepository
    time_entries: TimeEntryRepository
    payroll_records: PayrollRecordRepository
    documents: EmployeeDocumentRepository
    history: EmployeeHistoryRepository
    payroll_supplements: PayrollSupplementRepository
    severance_settlements: SeveranceSettlementRepository
    audit_log: AuditLogRepository
    work_accidents: WorkAccidentRepository
    it_episodes: ITEpisodeRepository
    holiday_templates: HolidayTemplateRepository
    document_templates: DocumentTemplateRepository
    onboarding_tasks: OnboardingTaskRepository
    candidates: CandidateRepository
    trainings: EmployeeTrainingRepository
    collective_agreements: CollectiveAgreementRepository
    professional_categories: ProfessionalCategoryRepository
    objectives: ObjectiveRepository
    performance_reviews: PerformanceReviewRepository
    assigned_equipment: AssignedEquipmentRepository

    @staticmethod
    def create(conn: DbConnection) -> Repositories:
        return Repositories(
            departments=DepartmentRepository(conn),
            employees=EmployeeRepository(conn),
            shifts=ShiftRepository(conn),
            day_types=DayTypeRepository(conn),
            closures=DepartmentClosureRepository(conn),
            absences=EmployeeAbsenceRepository(conn),
            payroll_settings=PayrollSettingsRepository(conn),
            daily_assignments=DailyAssignmentRepository(conn),
            users=UserRepository(conn),
            app_settings=AppSettingsRepository(conn),
            time_entries=TimeEntryRepository(conn),
            payroll_records=PayrollRecordRepository(conn),
            documents=EmployeeDocumentRepository(conn),
            history=EmployeeHistoryRepository(conn),
            payroll_supplements=PayrollSupplementRepository(conn),
            severance_settlements=SeveranceSettlementRepository(conn),
            audit_log=AuditLogRepository(conn),
            work_accidents=WorkAccidentRepository(conn),
            it_episodes=ITEpisodeRepository(conn),
            holiday_templates=HolidayTemplateRepository(conn),
            document_templates=DocumentTemplateRepository(conn),
            onboarding_tasks=OnboardingTaskRepository(conn),
            candidates=CandidateRepository(conn),
            trainings=EmployeeTrainingRepository(conn),
            collective_agreements=CollectiveAgreementRepository(conn),
            professional_categories=ProfessionalCategoryRepository(conn),
            objectives=ObjectiveRepository(conn),
            performance_reviews=PerformanceReviewRepository(conn),
            assigned_equipment=AssignedEquipmentRepository(conn),
        )
