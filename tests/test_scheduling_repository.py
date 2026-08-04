from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from app import validation
from app.repository import (
    DailyAssignmentRepository,
    DayTypeRepository,
    DepartmentClosureRepository,
    DepartmentRepository,
    DuplicateError,
    EmployeeAbsenceRepository,
    EmployeeInput,
    EmployeeRepository,
    HolidayTemplateRepository,
    NotFoundError,
    ReferenceInUseError,
    RepositoryError,
    ShiftInput,
    ShiftRepository,
    TimeEntryRepository,
)


def make_employee_input(**overrides: object) -> EmployeeInput:
    defaults: dict[str, object] = dict(
        first_name="Ana",
        last_name="Lopez",
        email="ana.lopez@example.com",
        phone="",
        position="Ingeniera",
        department_id=1,
        salary=35000.0,
        hire_date="2023-05-01",
        active=True,
    )
    defaults.update(overrides)
    return EmployeeInput(**defaults)  # type: ignore[arg-type]


def make_shift_input(**overrides: object) -> ShiftInput:
    defaults: dict[str, object] = dict(
        department_id=1,
        name="Turno mañana",
        start_time="08:00",
        end_time="15:00",
        days_of_week=frozenset({1, 2, 3, 4, 5}),
    )
    defaults.update(overrides)
    return ShiftInput(**defaults)  # type: ignore[arg-type]


class TestShiftRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    def test_create_and_get(self, conn: sqlite3.Connection, department_id: int) -> None:
        repo = ShiftRepository(conn)
        shift = repo.create(make_shift_input(department_id=department_id))
        assert shift.id is not None
        assert shift.days_of_week == frozenset({1, 2, 3, 4, 5})
        assert repo.get(shift.id).name == "Turno mañana"

    def test_create_with_unknown_department_raises(self, conn: sqlite3.Connection) -> None:
        repo = ShiftRepository(conn)
        with pytest.raises(NotFoundError):
            repo.create(make_shift_input(department_id=999))

    def test_duplicate_name_within_department_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = ShiftRepository(conn)
        repo.create(make_shift_input(department_id=department_id))
        with pytest.raises(DuplicateError):
            repo.create(make_shift_input(department_id=department_id))

    def test_same_name_allowed_in_different_department(self, conn: sqlite3.Connection) -> None:
        dept_repo = DepartmentRepository(conn)
        repo = ShiftRepository(conn)
        dept_a = dept_repo.create("A")
        dept_b = dept_repo.create("B")
        assert dept_a.id is not None and dept_b.id is not None
        repo.create(make_shift_input(department_id=dept_a.id))
        repo.create(make_shift_input(department_id=dept_b.id))  # should not raise

    def test_start_equal_to_end_time_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = ShiftRepository(conn)
        with pytest.raises(validation.ValidationError):
            repo.create(
                make_shift_input(
                    department_id=department_id, start_time="09:00", end_time="09:00"
                )
            )

    def test_overnight_shift_can_be_created(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        # end_time < start_time ya no se rechaza: es un turno que cruza la
        # medianoche (p. ej. un turno de noche 22:00-06:00), no un error.
        repo = ShiftRepository(conn)
        shift = repo.create(
            make_shift_input(
                department_id=department_id, start_time="22:00", end_time="06:00"
            )
        )
        assert shift.start_time == "22:00"
        assert shift.end_time == "06:00"
        assert shift.schedule_display == "22:00-06:00"

    def test_empty_days_rejected(self, conn: sqlite3.Connection, department_id: int) -> None:
        repo = ShiftRepository(conn)
        with pytest.raises(validation.ValidationError):
            repo.create(
                make_shift_input(department_id=department_id, days_of_week=frozenset())
            )

    def test_list_for_department_sorted_by_name(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = ShiftRepository(conn)
        repo.create(make_shift_input(department_id=department_id, name="Turno tarde"))
        repo.create(make_shift_input(department_id=department_id, name="Turno mañana"))
        names = [s.name for s in repo.list_for_department(department_id)]
        assert names == ["Turno mañana", "Turno tarde"]

    def test_update_changes_fields(self, conn: sqlite3.Connection, department_id: int) -> None:
        repo = ShiftRepository(conn)
        shift = repo.create(make_shift_input(department_id=department_id))
        assert shift.id is not None
        updated = repo.update(
            shift.id,
            make_shift_input(
                department_id=department_id, name="Turno mañana", start_time="09:00"
            ),
        )
        assert updated.start_time == "09:00"

    def test_get_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            ShiftRepository(conn).get(999)

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            ShiftRepository(conn).delete(999)

    def test_delete_shift_unassigns_employees_instead_of_blocking(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        shift_repo = ShiftRepository(conn)
        emp_repo = EmployeeRepository(conn)
        shift = shift_repo.create(make_shift_input(department_id=department_id))
        assert shift.id is not None
        employee = emp_repo.create(
            make_employee_input(department_id=department_id, shift_id=shift.id)
        )
        assert employee.id is not None

        shift_repo.delete(shift.id)

        refreshed = emp_repo.get(employee.id)
        assert refreshed.shift_id is None

    def test_create_with_split_schedule(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        shift = ShiftRepository(conn).create(
            make_shift_input(
                department_id=department_id,
                start_time="08:00",
                end_time="14:30",
                start_time_2="15:30",
                end_time_2="17:00",
            )
        )
        assert (shift.start_time_2, shift.end_time_2) == ("15:30", "17:00")
        assert shift.schedule_display == "08:00-14:30 y 15:30-17:00"

    def test_create_without_split_schedule_has_none(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        shift = ShiftRepository(conn).create(make_shift_input(department_id=department_id))
        assert shift.start_time_2 is None and shift.end_time_2 is None
        assert shift.schedule_display == "08:00-15:00"

    def test_create_with_overlapping_split_schedule_rejected(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            ShiftRepository(conn).create(
                make_shift_input(
                    department_id=department_id,
                    end_time="14:30",
                    start_time_2="14:00",  # starts before the first stretch even ends
                    end_time_2="17:00",
                )
            )

    def test_delete_blocked_when_daily_assignments_exist(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        shift_repo = ShiftRepository(conn)
        emp_repo = EmployeeRepository(conn)
        shift = shift_repo.create(make_shift_input(department_id=department_id))
        assert shift.id is not None
        employee = emp_repo.create(make_employee_input(department_id=department_id))
        assert employee.id is not None
        DailyAssignmentRepository(conn).set_day(employee.id, date(2026, 8, 3), shift.id)

        with pytest.raises(ReferenceInUseError):
            shift_repo.delete(shift.id)


class TestEmployeeShiftAssignment:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    def test_create_with_shift_in_same_department_succeeds(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        shift = ShiftRepository(conn).create(make_shift_input(department_id=department_id))
        assert shift.id is not None
        employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id, shift_id=shift.id)
        )
        assert employee.shift_id == shift.id

    def test_create_without_shift_defaults_to_none(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id)
        )
        assert employee.shift_id is None

    def test_create_with_shift_from_other_department_rejected(
        self, conn: sqlite3.Connection
    ) -> None:
        dept_repo = DepartmentRepository(conn)
        dept_a = dept_repo.create("A")
        dept_b = dept_repo.create("B")
        assert dept_a.id is not None and dept_b.id is not None
        shift = ShiftRepository(conn).create(make_shift_input(department_id=dept_a.id))
        assert shift.id is not None
        with pytest.raises(validation.ValidationError):
            EmployeeRepository(conn).create(
                make_employee_input(department_id=dept_b.id, shift_id=shift.id)
            )

    def test_create_with_unknown_shift_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        with pytest.raises(NotFoundError):
            EmployeeRepository(conn).create(
                make_employee_input(department_id=department_id, shift_id=999)
            )


class TestDayTypeRepository:
    def test_create_and_get(self, conn: sqlite3.Connection) -> None:
        repo = DayTypeRepository(conn)
        created = repo.create("Vacaciones", "#2ecc71")
        assert created.id is not None
        assert repo.get(created.id).color == "#2ecc71"

    def test_duplicate_name_rejected(self, conn: sqlite3.Connection) -> None:
        repo = DayTypeRepository(conn)
        repo.create("Vacaciones", "#2ecc71")
        with pytest.raises(DuplicateError):
            repo.create("vacaciones", "#000000")

    def test_invalid_color_rejected(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            DayTypeRepository(conn).create("Vacaciones", "not-a-color")

    def test_list_all_sorted(self, conn: sqlite3.Connection) -> None:
        repo = DayTypeRepository(conn)
        repo.create("Enfermedad", "#e67e22")
        repo.create("Ausencia", "#c0392b")
        names = [d.name for d in repo.list_all()]
        assert names == ["Ausencia", "Enfermedad"]

    def test_delete_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            DayTypeRepository(conn).delete(999)

    def test_delete_in_use_is_blocked(self, conn: sqlite3.Connection) -> None:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        day_type = DayTypeRepository(conn).create("Festivo", "#e74c3c")
        assert day_type.id is not None
        DepartmentClosureRepository(conn).set_day(dept.id, date(2026, 8, 15), day_type.id)
        with pytest.raises(ReferenceInUseError):
            DayTypeRepository(conn).delete(day_type.id)

    def test_defaults_to_not_vacation(self, conn: sqlite3.Connection) -> None:
        day_type = DayTypeRepository(conn).create("Festivo", "#e74c3c")
        assert day_type.is_vacation is False

    def test_create_as_vacation(self, conn: sqlite3.Connection) -> None:
        day_type = DayTypeRepository(conn).create("Vacaciones", "#2ecc71", is_vacation=True)
        assert day_type.is_vacation is True

    def test_update_changes_name_color_and_is_vacation(self, conn: sqlite3.Connection) -> None:
        repo = DayTypeRepository(conn)
        day_type = repo.create("Festivo", "#e74c3c")
        assert day_type.id is not None
        updated = repo.update(day_type.id, "Vacaciones", "#2ecc71", True)
        assert updated.name == "Vacaciones"
        assert updated.color == "#2ecc71"
        assert updated.is_vacation is True

    def test_update_missing_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            DayTypeRepository(conn).update(999, "Vacaciones", "#2ecc71", True)

    def test_update_to_duplicate_name_rejected(self, conn: sqlite3.Connection) -> None:
        repo = DayTypeRepository(conn)
        repo.create("Vacaciones", "#2ecc71")
        other = repo.create("Festivo", "#e74c3c")
        assert other.id is not None
        with pytest.raises(DuplicateError):
            repo.update(other.id, "vacaciones", "#e74c3c", False)

    def test_update_can_toggle_is_vacation_on_an_in_use_day_type(
        self, conn: sqlite3.Connection
    ) -> None:
        # Deleting-and-recreating isn't an option here: day_types.id is
        # ON DELETE RESTRICT once an absence references it, so update() is
        # the only way to fix/flag an existing, in-use day type.
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        employee = EmployeeRepository(conn).create(make_employee_input(department_id=dept.id))
        assert employee.id is not None
        day_type = DayTypeRepository(conn).create("Vacaciones", "#2ecc71")
        assert day_type.id is not None
        EmployeeAbsenceRepository(conn).set_day(employee.id, date(2026, 8, 15), day_type.id)

        updated = DayTypeRepository(conn).update(day_type.id, "Vacaciones", "#2ecc71", True)
        assert updated.is_vacation is True


class TestDepartmentClosureRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def day_type_id(self, conn: sqlite3.Connection) -> int:
        day_type = DayTypeRepository(conn).create("Festivo", "#e74c3c")
        assert day_type.id is not None
        return day_type.id

    def test_set_day_creates_and_clears(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        repo = DepartmentClosureRepository(conn)
        repo.set_day(department_id, date(2026, 8, 15), day_type_id, note="Puente")
        closures = repo.get_for_month(department_id, 2026, 8)
        assert closures[date(2026, 8, 15)].note == "Puente"

        repo.set_day(department_id, date(2026, 8, 15), None)
        closures_after = repo.get_for_month(department_id, 2026, 8)
        assert date(2026, 8, 15) not in closures_after

    def test_clearing_a_day_that_was_never_set_is_a_no_op(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        DepartmentClosureRepository(conn).set_day(department_id, date(2026, 8, 15), None)

    def test_set_day_upserts_existing_mark(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        repo = DepartmentClosureRepository(conn)
        other_type = DayTypeRepository(conn).create("Cierre", "#111111")
        assert other_type.id is not None
        repo.set_day(department_id, date(2026, 8, 15), day_type_id)
        repo.set_day(department_id, date(2026, 8, 15), other_type.id, note="cambiado")
        closures = repo.get_for_month(department_id, 2026, 8)
        assert closures[date(2026, 8, 15)].day_type_id == other_type.id
        assert closures[date(2026, 8, 15)].note == "cambiado"

    def test_mark_range_includes_weekends(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        repo = DepartmentClosureRepository(conn)
        count = repo.mark_range(
            department_id, day_type_id, date(2026, 8, 1), date(2026, 8, 7)
        )
        assert count == 7
        closures = repo.get_for_month(department_id, 2026, 8)
        assert len(closures) == 7

    def test_list_dates_for_department_spans_every_month(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        # A diferencia de get_for_month(), no debe acotarse a un mes/año --
        # pensado para el selector de fecha (CalendarPopup), que necesita
        # conocer los festivos de CUALQUIER mes al que el usuario navegue.
        repo = DepartmentClosureRepository(conn)
        repo.set_day(department_id, date(2026, 1, 1), day_type_id)
        repo.set_day(department_id, date(2026, 12, 25), day_type_id)
        assert repo.list_dates_for_department(department_id) == {
            date(2026, 1, 1),
            date(2026, 12, 25),
        }

    def test_list_dates_for_department_excludes_other_departments(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        other_dept = DepartmentRepository(conn).create("Producción")
        assert other_dept.id is not None
        repo = DepartmentClosureRepository(conn)
        repo.set_day(department_id, date(2026, 1, 1), day_type_id)
        repo.set_day(other_dept.id, date(2026, 6, 1), day_type_id)
        assert repo.list_dates_for_department(department_id) == {date(2026, 1, 1)}

    def test_list_dates_for_department_empty_when_none_registered(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        assert DepartmentClosureRepository(conn).list_dates_for_department(department_id) == frozenset()

    def test_mark_range_rejects_end_before_start(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            DepartmentClosureRepository(conn).mark_range(
                department_id, day_type_id, date(2026, 8, 15), date(2026, 8, 1)
            )

    def test_mark_range_unknown_department_raises(
        self, conn: sqlite3.Connection, day_type_id: int
    ) -> None:
        with pytest.raises(NotFoundError):
            DepartmentClosureRepository(conn).mark_range(
                999, day_type_id, date(2026, 8, 1), date(2026, 8, 2)
            )

    def test_get_for_month_excludes_other_months(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        repo = DepartmentClosureRepository(conn)
        repo.set_day(department_id, date(2026, 7, 31), day_type_id)
        repo.set_day(department_id, date(2026, 8, 1), day_type_id)
        repo.set_day(department_id, date(2026, 9, 1), day_type_id)
        august = repo.get_for_month(department_id, 2026, 8)
        assert list(august.keys()) == [date(2026, 8, 1)]


class TestHolidayTemplateRepository:
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

    @pytest.fixture()
    def day_type_id(self, conn: sqlite3.Connection) -> int:
        day_type = DayTypeRepository(conn).create("Festivo", "#e74c3c")
        assert day_type.id is not None
        return day_type.id

    def test_create_and_get(self, conn: sqlite3.Connection) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        assert template.name == "Festivos 2026"
        assert template.created_at == date.today()
        assert repo.get(template.id) == template

    def test_create_rejects_duplicate_name_case_insensitive(
        self, conn: sqlite3.Connection
    ) -> None:
        repo = HolidayTemplateRepository(conn)
        repo.create("Festivos 2026")
        with pytest.raises(DuplicateError):
            repo.create("festivos 2026")

    def test_create_rejects_blank_name(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(validation.ValidationError):
            HolidayTemplateRepository(conn).create("   ")

    def test_get_unknown_template_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            HolidayTemplateRepository(conn).get(999)

    def test_list_all_orders_by_name(self, conn: sqlite3.Connection) -> None:
        repo = HolidayTemplateRepository(conn)
        repo.create("Festivos 2027")
        repo.create("Festivos 2026")
        names = [t.name for t in repo.list_all()]
        assert names == ["Festivos 2026", "Festivos 2027"]

    def test_delete_removes_template(self, conn: sqlite3.Connection) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        repo.delete(template.id)
        with pytest.raises(NotFoundError):
            repo.get(template.id)

    def test_delete_unknown_template_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            HolidayTemplateRepository(conn).delete(999)

    def test_delete_cascades_to_its_dates(self, conn: sqlite3.Connection) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        repo.import_dates(template.id, "2026-01-01 Año Nuevo")
        repo.delete(template.id)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM holiday_template_dates WHERE template_id = ?",
            (template.id,),
        ).fetchone()[0]
        assert remaining == 0

    def test_import_dates_returns_count_and_stores_rows(self, conn: sqlite3.Connection) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        count = repo.import_dates(
            template.id, "2026-01-01 Año Nuevo\n2026-12-25 Navidad"
        )
        assert count == 2
        dates = repo.list_dates(template.id)
        assert [(d.holiday_date, d.label) for d in dates] == [
            (date(2026, 1, 1), "Año Nuevo"),
            (date(2026, 12, 25), "Navidad"),
        ]

    def test_import_dates_unknown_template_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            HolidayTemplateRepository(conn).import_dates(999, "2026-01-01 Año Nuevo")

    def test_import_dates_propagates_parse_errors(self, conn: sqlite3.Connection) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        with pytest.raises(validation.ValidationError):
            repo.import_dates(template.id, "not-a-date")

    def test_reimporting_the_same_date_updates_its_label(self, conn: sqlite3.Connection) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        repo.import_dates(template.id, "2026-01-01 Provisional")
        repo.import_dates(template.id, "2026-01-01 Año Nuevo")
        dates = repo.list_dates(template.id)
        assert len(dates) == 1
        assert dates[0].label == "Año Nuevo"

    def test_list_dates_unknown_template_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            HolidayTemplateRepository(conn).list_dates(999)

    def test_list_dates_orders_by_date(self, conn: sqlite3.Connection) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        repo.import_dates(template.id, "2026-12-25 Navidad\n2026-01-01 Año Nuevo")
        dates = repo.list_dates(template.id)
        assert [d.holiday_date for d in dates] == [date(2026, 1, 1), date(2026, 12, 25)]

    def test_delete_date_removes_a_single_row(self, conn: sqlite3.Connection) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        repo.import_dates(template.id, "2026-01-01 Año Nuevo\n2026-12-25 Navidad")
        first_id = repo.list_dates(template.id)[0].id
        assert first_id is not None
        repo.delete_date(first_id)
        remaining = repo.list_dates(template.id)
        assert len(remaining) == 1
        assert remaining[0].label == "Navidad"

    def test_delete_date_unknown_id_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            HolidayTemplateRepository(conn).delete_date(999)

    def test_apply_to_departments_creates_closures(
        self,
        conn: sqlite3.Connection,
        department_id: int,
        other_department_id: int,
        day_type_id: int,
    ) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        repo.import_dates(template.id, "2026-01-01 Año Nuevo\n2026-12-25 Navidad")

        result = repo.apply_to_departments(
            template.id, [department_id, other_department_id], day_type_id
        )
        assert result.departments_applied == 2
        assert result.closures_created == 4
        assert result.closures_skipped == 0

        closures = DepartmentClosureRepository(conn).get_for_month(department_id, 2026, 1)
        assert closures[date(2026, 1, 1)].day_type_id == day_type_id
        assert closures[date(2026, 1, 1)].note == "Año Nuevo"
        other_closures = DepartmentClosureRepository(conn).get_for_month(
            other_department_id, 2026, 1
        )
        assert date(2026, 1, 1) in other_closures

    def test_apply_to_departments_does_not_overwrite_an_existing_closure(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        other_type = DayTypeRepository(conn).create("Cierre por obras", "#111111")
        assert other_type.id is not None
        DepartmentClosureRepository(conn).set_day(
            department_id, date(2026, 1, 1), other_type.id, note="Cierre ya existente"
        )

        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        repo.import_dates(template.id, "2026-01-01 Año Nuevo")

        result = repo.apply_to_departments(template.id, [department_id], day_type_id)
        assert result.closures_created == 0
        assert result.closures_skipped == 1

        closures = DepartmentClosureRepository(conn).get_for_month(department_id, 2026, 1)
        assert closures[date(2026, 1, 1)].day_type_id == other_type.id
        assert closures[date(2026, 1, 1)].note == "Cierre ya existente"

    def test_apply_to_departments_rejects_a_template_with_no_dates(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        with pytest.raises(RepositoryError):
            repo.apply_to_departments(template.id, [department_id], day_type_id)

    def test_apply_to_departments_rejects_no_departments_selected(
        self, conn: sqlite3.Connection, day_type_id: int
    ) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        repo.import_dates(template.id, "2026-01-01 Año Nuevo")
        with pytest.raises(RepositoryError):
            repo.apply_to_departments(template.id, [], day_type_id)

    def test_apply_to_departments_unknown_department_raises(
        self, conn: sqlite3.Connection, day_type_id: int
    ) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        repo.import_dates(template.id, "2026-01-01 Año Nuevo")
        with pytest.raises(NotFoundError):
            repo.apply_to_departments(template.id, [999], day_type_id)

    def test_apply_to_departments_unknown_day_type_raises(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        repo.import_dates(template.id, "2026-01-01 Año Nuevo")
        with pytest.raises(NotFoundError):
            repo.apply_to_departments(template.id, [department_id], 999)

    def test_apply_to_departments_is_reapplicable_without_duplicating(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        repo = HolidayTemplateRepository(conn)
        template = repo.create("Festivos 2026")
        assert template.id is not None
        repo.import_dates(template.id, "2026-01-01 Año Nuevo")
        repo.apply_to_departments(template.id, [department_id], day_type_id)
        second = repo.apply_to_departments(template.id, [department_id], day_type_id)
        assert second.closures_created == 0
        assert second.closures_skipped == 1


class TestEmployeeAbsenceRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def day_type_id(self, conn: sqlite3.Connection) -> int:
        day_type = DayTypeRepository(conn).create("Vacaciones", "#2ecc71")
        assert day_type.id is not None
        return day_type.id

    def test_mark_range_without_shift_defaults_to_weekdays(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id)
        )
        assert employee.id is not None
        # 2026-08-01 is a Saturday; range covers one full week (Sat..Fri) = 5 weekdays + 2 weekend days
        result = EmployeeAbsenceRepository(conn).mark_range(
            employee.id, day_type_id, date(2026, 8, 1), date(2026, 8, 7)
        )
        assert result.marked == 5
        assert result.skipped == 2

    def test_mark_range_respects_employee_shift_days(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        shift = ShiftRepository(conn).create(
            make_shift_input(
                department_id=department_id,
                name="Fin de semana",
                days_of_week=frozenset({6, 7}),
            )
        )
        assert shift.id is not None
        employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id, shift_id=shift.id)
        )
        assert employee.id is not None

        result = EmployeeAbsenceRepository(conn).mark_range(
            employee.id, day_type_id, date(2026, 8, 1), date(2026, 8, 7)
        )
        assert result.marked == 2
        assert result.skipped == 5

    def test_set_day_upserts(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id)
        )
        assert employee.id is not None
        repo = EmployeeAbsenceRepository(conn)
        other_type = DayTypeRepository(conn).create("Enfermedad", "#e67e22")
        assert other_type.id is not None

        repo.set_day(employee.id, date(2026, 8, 3), day_type_id)
        repo.set_day(employee.id, date(2026, 8, 3), other_type.id, note="gripe")

        absences = repo.get_for_month(employee.id, 2026, 8)
        assert absences[date(2026, 8, 3)].day_type_id == other_type.id
        assert absences[date(2026, 8, 3)].note == "gripe"

    def test_set_day_none_clears_mark(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id)
        )
        assert employee.id is not None
        repo = EmployeeAbsenceRepository(conn)
        repo.set_day(employee.id, date(2026, 8, 3), day_type_id)
        repo.set_day(employee.id, date(2026, 8, 3), None)
        assert repo.get_for_month(employee.id, 2026, 8) == {}

    def test_list_for_department_month_excludes_other_departments(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        other_dept = DepartmentRepository(conn).create("Otro")
        assert other_dept.id is not None
        emp_repo = EmployeeRepository(conn)
        absence_repo = EmployeeAbsenceRepository(conn)

        in_dept = emp_repo.create(
            make_employee_input(department_id=department_id, email="in@x.com")
        )
        outside_dept = emp_repo.create(
            make_employee_input(department_id=other_dept.id, email="out@x.com")
        )
        assert in_dept.id is not None and outside_dept.id is not None

        absence_repo.set_day(in_dept.id, date(2026, 8, 5), day_type_id)
        absence_repo.set_day(outside_dept.id, date(2026, 8, 5), day_type_id)

        results = absence_repo.list_for_department_month(department_id, 2026, 8)
        assert [a.employee_id for a in results] == [in_dept.id]

    def test_deleting_employee_cascades_absences(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        emp_repo = EmployeeRepository(conn)
        employee = emp_repo.create(make_employee_input(department_id=department_id))
        assert employee.id is not None
        EmployeeAbsenceRepository(conn).set_day(employee.id, date(2026, 8, 5), day_type_id)

        emp_repo.delete(employee.id)

        remaining = conn.execute(
            "SELECT COUNT(*) FROM employee_absences WHERE employee_id = ?", (employee.id,)
        ).fetchone()[0]
        assert remaining == 0

    def test_mark_range_unknown_employee_raises(
        self, conn: sqlite3.Connection, day_type_id: int
    ) -> None:
        with pytest.raises(NotFoundError):
            EmployeeAbsenceRepository(conn).mark_range(
                999, day_type_id, date(2026, 8, 1), date(2026, 8, 2)
            )

    def test_set_day_and_mark_range_are_immediately_approved(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id)
        )
        assert employee.id is not None
        repo = EmployeeAbsenceRepository(conn)
        repo.set_day(employee.id, date(2026, 8, 3), day_type_id)
        assert repo.get_for_month(employee.id, 2026, 8)[date(2026, 8, 3)].status == "aprobada"

    def test_list_all_for_employee_includes_every_status_and_excludes_other_employees(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        # A diferencia de get_for_month/list_for_date (solo 'aprobada'), esta
        # es la vista completa que usa la exportación RGPD: debe traer
        # también las pendientes/rechazadas.
        emp_repo = EmployeeRepository(conn)
        absence_repo = EmployeeAbsenceRepository(conn)
        employee = emp_repo.create(make_employee_input(department_id=department_id))
        other = emp_repo.create(
            make_employee_input(department_id=department_id, email="otro@x.com")
        )
        assert employee.id is not None and other.id is not None

        absence_repo.set_day(employee.id, date(2026, 9, 1), day_type_id)
        pending = absence_repo.request(employee.id, day_type_id, date(2026, 8, 3))
        assert pending.id is not None
        absence_repo.set_day(other.id, date(2026, 8, 3), day_type_id)

        results = absence_repo.list_all_for_employee(employee.id)
        assert [(a.absence_date, a.status) for a in results] == [
            (date(2026, 8, 3), "pendiente"),
            (date(2026, 9, 1), "aprobada"),
        ]


class TestAbsenceRequestWorkflow:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def day_type_id(self, conn: sqlite3.Connection) -> int:
        day_type = DayTypeRepository(conn).create("Vacaciones", "#2ecc71", is_vacation=True)
        assert day_type.id is not None
        return day_type.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id)
        )
        assert employee.id is not None
        return employee.id

    def test_request_creates_a_pending_absence(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        absence = EmployeeAbsenceRepository(conn).request(
            employee_id, day_type_id, date(2026, 8, 3), note="vacaciones familiares"
        )
        assert absence.status == "pendiente"
        assert absence.note == "vacaciones familiares"

    def test_pending_request_does_not_appear_in_get_for_month(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        repo = EmployeeAbsenceRepository(conn)
        repo.request(employee_id, day_type_id, date(2026, 8, 3))
        assert repo.get_for_month(employee_id, 2026, 8) == {}

    def test_pending_request_does_not_appear_in_list_for_date(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        repo = EmployeeAbsenceRepository(conn)
        repo.request(employee_id, day_type_id, date(2026, 8, 3))
        assert repo.list_for_date(date(2026, 8, 3)) == []

    def test_pending_request_does_not_count_toward_vacation_balance(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        repo = EmployeeAbsenceRepository(conn)
        repo.request(employee_id, day_type_id, date(2026, 8, 3))
        assert repo.count_vacation_days_for_year(employee_id, 2026) == 0

    def test_approve_makes_it_visible_and_counted(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        repo = EmployeeAbsenceRepository(conn)
        absence = repo.request(employee_id, day_type_id, date(2026, 8, 3))
        assert absence.id is not None

        approved = repo.approve(absence.id)
        assert approved.status == "aprobada"
        assert date(2026, 8, 3) in repo.get_for_month(employee_id, 2026, 8)
        assert repo.count_vacation_days_for_year(employee_id, 2026) == 1

    def test_reject_keeps_it_out_of_the_calendar(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        repo = EmployeeAbsenceRepository(conn)
        absence = repo.request(employee_id, day_type_id, date(2026, 8, 3))
        assert absence.id is not None

        rejected = repo.reject(absence.id)
        assert rejected.status == "rechazada"
        assert repo.get_for_month(employee_id, 2026, 8) == {}
        assert repo.count_vacation_days_for_year(employee_id, 2026) == 0

    def test_approve_unknown_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeAbsenceRepository(conn).approve(999)

    def test_reject_unknown_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeAbsenceRepository(conn).reject(999)

    def test_get_unknown_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            EmployeeAbsenceRepository(conn).get(999)

    def test_list_pending_only_includes_pending(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        repo = EmployeeAbsenceRepository(conn)
        approved_directly = repo.request(employee_id, day_type_id, date(2026, 8, 1))
        to_approve = repo.request(employee_id, day_type_id, date(2026, 8, 2))
        to_reject = repo.request(employee_id, day_type_id, date(2026, 8, 3))
        still_pending = repo.request(employee_id, day_type_id, date(2026, 8, 4))
        assert approved_directly.id is not None and to_approve.id is not None
        assert to_reject.id is not None and still_pending.id is not None
        repo.approve(approved_directly.id)
        repo.approve(to_approve.id)
        repo.reject(to_reject.id)

        pending = repo.list_pending()
        assert [p.absence_date for p in pending] == [date(2026, 8, 4)]

    def test_list_pending_excludes_other_employees_and_is_global(
        self, conn: sqlite3.Connection, department_id: int, day_type_id: int
    ) -> None:
        other = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id, email="otro@example.com")
        )
        assert other.id is not None
        repo = EmployeeAbsenceRepository(conn)
        repo.request(other.id, day_type_id, date(2026, 8, 5))
        assert len(repo.list_pending()) == 1

    def test_list_pending_for_department_only_includes_that_department(
        self,
        conn: sqlite3.Connection,
        department_id: int,
        employee_id: int,
        day_type_id: int,
    ) -> None:
        other_department = DepartmentRepository(conn).create("Marketing")
        assert other_department.id is not None
        other_employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=other_department.id, email="otro@example.com")
        )
        assert other_employee.id is not None

        repo = EmployeeAbsenceRepository(conn)
        repo.request(employee_id, day_type_id, date(2026, 8, 1))
        repo.request(other_employee.id, day_type_id, date(2026, 8, 2))

        assert [p.absence_date for p in repo.list_pending_for_department(department_id)] == [
            date(2026, 8, 1)
        ]
        assert [
            p.absence_date for p in repo.list_pending_for_department(other_department.id)
        ] == [date(2026, 8, 2)]

    def test_list_pending_for_department_excludes_approved_and_rejected(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int, day_type_id: int
    ) -> None:
        repo = EmployeeAbsenceRepository(conn)
        to_approve = repo.request(employee_id, day_type_id, date(2026, 8, 1))
        to_reject = repo.request(employee_id, day_type_id, date(2026, 8, 2))
        assert to_approve.id is not None and to_reject.id is not None
        repo.approve(to_approve.id)
        repo.reject(to_reject.id)

        assert repo.list_pending_for_department(department_id) == []

    def test_request_range_marks_only_working_weekdays_as_pending(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        repo = EmployeeAbsenceRepository(conn)
        # 2026-08-01 is a Saturday; range covers one full week.
        result = repo.request_range(
            employee_id, day_type_id, date(2026, 8, 1), date(2026, 8, 7)
        )
        assert result.marked == 5
        assert result.skipped == 2
        assert len(repo.list_pending()) == 5

    def test_re_requesting_an_approved_day_resets_it_to_pending(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        repo = EmployeeAbsenceRepository(conn)
        repo.set_day(employee_id, date(2026, 8, 3), day_type_id)  # directly approved
        assert repo.get_for_month(employee_id, 2026, 8)[date(2026, 8, 3)].status == "aprobada"

        repo.request(employee_id, day_type_id, date(2026, 8, 3), note="corrección")
        # No longer shows as approved until re-approved.
        assert repo.get_for_month(employee_id, 2026, 8) == {}
        pending = repo.list_pending()
        assert len(pending) == 1 and pending[0].note == "corrección"

    def test_rejecting_a_request_that_overwrote_an_approved_day_restores_it(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        # Regresión: sin esto, rechazar una solicitud que había sobrescrito
        # un día ya aprobado dejaba el día completamente vacío -- ni la
        # aprobación original ni la solicitud rechazada quedaban visibles
        # en ningún sitio, aunque nadie hubiera decidido descartar la
        # aprobación original en sí.
        repo = EmployeeAbsenceRepository(conn)
        other_day_type = DayTypeRepository(conn).create("Enfermedad", "#e67e22")
        assert other_day_type.id is not None

        repo.set_day(employee_id, date(2026, 8, 3), day_type_id, note="vacaciones aprobadas")
        new_request = repo.request(
            employee_id, other_day_type.id, date(2026, 8, 3), note="en realidad estoy enfermo"
        )
        assert new_request.id is not None

        rejected = repo.reject(new_request.id)
        assert rejected.status == "aprobada"
        assert rejected.day_type_id == day_type_id
        assert rejected.note == "vacaciones aprobadas"
        restored = repo.get_for_month(employee_id, 2026, 8)[date(2026, 8, 3)]
        assert restored.day_type_id == day_type_id
        assert restored.status == "aprobada"

    def test_rejecting_a_fresh_request_with_no_prior_approval_still_just_rejects(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        repo = EmployeeAbsenceRepository(conn)
        fresh_request = repo.request(employee_id, day_type_id, date(2026, 8, 3))
        assert fresh_request.id is not None

        rejected = repo.reject(fresh_request.id)
        assert rejected.status == "rechazada"
        assert repo.get_for_month(employee_id, 2026, 8) == {}

    def test_second_request_before_the_first_is_decided_preserves_the_original_snapshot(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        # Pedir un segundo cambio mientras el primero sigue sin decidir no
        # debe perder el snapshot de la aprobación original (capturado en
        # la primera solicitud) -- de lo contrario, rechazar el segundo
        # cambio no podría restaurar nada.
        repo = EmployeeAbsenceRepository(conn)
        other_day_type = DayTypeRepository(conn).create("Enfermedad", "#e67e22")
        third_day_type = DayTypeRepository(conn).create("Permiso", "#9b59b6")
        assert other_day_type.id is not None and third_day_type.id is not None

        repo.set_day(employee_id, date(2026, 8, 3), day_type_id, note="original")
        first_request = repo.request(employee_id, other_day_type.id, date(2026, 8, 3))
        second_request = repo.request(employee_id, third_day_type.id, date(2026, 8, 3))
        assert first_request.id is not None and second_request.id is not None
        assert first_request.id == second_request.id  # misma fila (mismo empleado+fecha)

        rejected = repo.reject(second_request.id)
        assert rejected.status == "aprobada"
        assert rejected.day_type_id == day_type_id
        assert rejected.note == "original"

    def test_approving_a_request_discards_the_previous_snapshot(
        self, conn: sqlite3.Connection, employee_id: int, day_type_id: int
    ) -> None:
        repo = EmployeeAbsenceRepository(conn)
        other_day_type = DayTypeRepository(conn).create("Enfermedad", "#e67e22")
        assert other_day_type.id is not None

        repo.set_day(employee_id, date(2026, 8, 3), day_type_id)
        new_request = repo.request(employee_id, other_day_type.id, date(2026, 8, 3))
        assert new_request.id is not None

        approved = repo.approve(new_request.id)
        assert approved.day_type_id == other_day_type.id
        row = conn.execute(
            "SELECT previous_day_type_id, previous_note FROM employee_absences WHERE id = ?",
            (new_request.id,),
        ).fetchone()
        assert row["previous_day_type_id"] is None
        assert row["previous_note"] is None


class TestCountVacationDaysForYear:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id)
        )
        assert employee.id is not None
        return employee.id

    def test_counts_only_vacation_flagged_absences(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        day_type_repo = DayTypeRepository(conn)
        vacation_type = day_type_repo.create("Vacaciones", "#2ecc71", is_vacation=True)
        sick_type = day_type_repo.create("Enfermedad", "#e67e22", is_vacation=False)
        assert vacation_type.id is not None and sick_type.id is not None

        absence_repo = EmployeeAbsenceRepository(conn)
        absence_repo.set_day(employee_id, date(2026, 8, 3), vacation_type.id)
        absence_repo.set_day(employee_id, date(2026, 8, 4), vacation_type.id)
        absence_repo.set_day(employee_id, date(2026, 8, 5), sick_type.id)

        assert absence_repo.count_vacation_days_for_year(employee_id, 2026) == 2

    def test_excludes_other_years(self, conn: sqlite3.Connection, employee_id: int) -> None:
        vacation_type = DayTypeRepository(conn).create(
            "Vacaciones", "#2ecc71", is_vacation=True
        )
        assert vacation_type.id is not None
        absence_repo = EmployeeAbsenceRepository(conn)
        absence_repo.set_day(employee_id, date(2025, 12, 31), vacation_type.id)
        absence_repo.set_day(employee_id, date(2026, 1, 1), vacation_type.id)

        assert absence_repo.count_vacation_days_for_year(employee_id, 2026) == 1
        assert absence_repo.count_vacation_days_for_year(employee_id, 2025) == 1

    def test_excludes_other_employees(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other_employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id, email="otro@example.com")
        )
        assert other_employee.id is not None
        vacation_type = DayTypeRepository(conn).create(
            "Vacaciones", "#2ecc71", is_vacation=True
        )
        assert vacation_type.id is not None
        EmployeeAbsenceRepository(conn).set_day(
            other_employee.id, date(2026, 8, 3), vacation_type.id
        )

        assert (
            EmployeeAbsenceRepository(conn).count_vacation_days_for_year(employee_id, 2026) == 0
        )

    def test_renaming_the_day_type_does_not_lose_the_flag(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        # The flag travels with the row, not the name -- this is exactly the
        # robustness the is_vacation column was added for.
        day_type_repo = DayTypeRepository(conn)
        vacation_type = day_type_repo.create("Vacaciones", "#2ecc71", is_vacation=True)
        assert vacation_type.id is not None
        EmployeeAbsenceRepository(conn).set_day(employee_id, date(2026, 8, 3), vacation_type.id)

        day_type_repo.update(vacation_type.id, "Vacaciones anuales", "#2ecc71", True)

        assert (
            EmployeeAbsenceRepository(conn).count_vacation_days_for_year(employee_id, 2026) == 1
        )

    def test_zero_when_no_absences(self, conn: sqlite3.Connection, employee_id: int) -> None:
        assert EmployeeAbsenceRepository(conn).count_vacation_days_for_year(employee_id, 2026) == 0


class TestDailyAssignmentRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id)
        )
        assert employee.id is not None
        return employee.id

    @pytest.fixture()
    def morning_shift_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        shift = ShiftRepository(conn).create(
            make_shift_input(
                department_id=department_id,
                name="Turno mañana",
                days_of_week=frozenset({1, 2, 3, 4, 5}),
            )
        )
        assert shift.id is not None
        return shift.id

    def test_set_day_creates_and_clears(
        self, conn: sqlite3.Connection, employee_id: int, morning_shift_id: int
    ) -> None:
        repo = DailyAssignmentRepository(conn)
        repo.set_day(employee_id, date(2026, 8, 3), morning_shift_id)
        assignments = repo.get_for_month(employee_id, 2026, 8)
        assert assignments[date(2026, 8, 3)].shift_id == morning_shift_id

        repo.set_day(employee_id, date(2026, 8, 3), None)
        assert date(2026, 8, 3) not in repo.get_for_month(employee_id, 2026, 8)

    def test_clearing_a_day_that_was_never_set_is_a_no_op(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        DailyAssignmentRepository(conn).set_day(employee_id, date(2026, 8, 3), None)

    def test_set_day_upserts_existing_assignment(
        self, conn: sqlite3.Connection, employee_id: int, department_id: int, morning_shift_id: int
    ) -> None:
        afternoon_shift = ShiftRepository(conn).create(
            make_shift_input(department_id=department_id, name="Turno tarde", start_time="15:00", end_time="22:00")
        )
        assert afternoon_shift.id is not None
        repo = DailyAssignmentRepository(conn)
        repo.set_day(employee_id, date(2026, 8, 3), morning_shift_id)
        repo.set_day(employee_id, date(2026, 8, 3), afternoon_shift.id)
        assert repo.get_for_month(employee_id, 2026, 8)[date(2026, 8, 3)].shift_id == afternoon_shift.id

    def test_set_day_unknown_employee_raises(
        self, conn: sqlite3.Connection, morning_shift_id: int
    ) -> None:
        with pytest.raises(NotFoundError):
            DailyAssignmentRepository(conn).set_day(999, date(2026, 8, 3), morning_shift_id)

    def test_set_day_unknown_shift_raises(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(NotFoundError):
            DailyAssignmentRepository(conn).set_day(employee_id, date(2026, 8, 3), 999)

    def test_apply_shift_to_range_only_fills_matching_weekdays(
        self, conn: sqlite3.Connection, employee_id: int, morning_shift_id: int
    ) -> None:
        # 2026-08-01 is a Saturday; range covers one full week (Sat..Fri).
        result = DailyAssignmentRepository(conn).apply_shift_to_range(
            employee_id, morning_shift_id, date(2026, 8, 1), date(2026, 8, 7)
        )
        assert result.marked == 5  # Mon-Fri
        assert result.skipped == 2  # Sat, Sun

    def test_apply_shift_to_range_rejects_end_before_start(
        self, conn: sqlite3.Connection, employee_id: int, morning_shift_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            DailyAssignmentRepository(conn).apply_shift_to_range(
                employee_id, morning_shift_id, date(2026, 8, 10), date(2026, 8, 1)
            )

    def test_apply_rotation_to_range_cycles_and_wraps_the_pattern(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int, morning_shift_id: int
    ) -> None:
        afternoon_shift = ShiftRepository(conn).create(
            make_shift_input(department_id=department_id, name="Turno tarde", start_time="15:00", end_time="22:00")
        )
        assert afternoon_shift.id is not None
        result = DailyAssignmentRepository(conn).apply_rotation_to_range(
            employee_id,
            [morning_shift_id, afternoon_shift.id, None],
            date(2026, 8, 1),
            date(2026, 8, 6),
        )
        assert result.marked == 4  # 2 turnos x 2 ciclos completos
        assert result.skipped == 2  # 1 descanso x 2 ciclos completos
        assignments = DailyAssignmentRepository(conn).get_for_month(employee_id, 2026, 8)
        assert assignments[date(2026, 8, 1)].shift_id == morning_shift_id
        assert assignments[date(2026, 8, 2)].shift_id == afternoon_shift.id
        assert date(2026, 8, 3) not in assignments  # descanso
        assert assignments[date(2026, 8, 4)].shift_id == morning_shift_id
        assert assignments[date(2026, 8, 5)].shift_id == afternoon_shift.id
        assert date(2026, 8, 6) not in assignments  # descanso

    def test_apply_rotation_to_range_none_clears_an_existing_assignment(
        self, conn: sqlite3.Connection, employee_id: int, morning_shift_id: int
    ) -> None:
        repo = DailyAssignmentRepository(conn)
        repo.set_day(employee_id, date(2026, 8, 1), morning_shift_id)
        result = repo.apply_rotation_to_range(
            employee_id, [None], date(2026, 8, 1), date(2026, 8, 1)
        )
        assert result.skipped == 1
        assert date(2026, 8, 1) not in repo.get_for_month(employee_id, 2026, 8)

    def test_apply_rotation_to_range_overwrites_an_existing_assignment(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int, morning_shift_id: int
    ) -> None:
        afternoon_shift = ShiftRepository(conn).create(
            make_shift_input(department_id=department_id, name="Turno tarde", start_time="15:00", end_time="22:00")
        )
        assert afternoon_shift.id is not None
        repo = DailyAssignmentRepository(conn)
        repo.set_day(employee_id, date(2026, 8, 1), afternoon_shift.id)
        repo.apply_rotation_to_range(
            employee_id, [morning_shift_id], date(2026, 8, 1), date(2026, 8, 1)
        )
        assert repo.get_for_month(employee_id, 2026, 8)[date(2026, 8, 1)].shift_id == morning_shift_id

    def test_apply_rotation_to_range_rejects_empty_pattern(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            DailyAssignmentRepository(conn).apply_rotation_to_range(
                employee_id, [], date(2026, 8, 1), date(2026, 8, 5)
            )

    def test_apply_rotation_to_range_rejects_end_before_start(
        self, conn: sqlite3.Connection, employee_id: int, morning_shift_id: int
    ) -> None:
        with pytest.raises(validation.ValidationError):
            DailyAssignmentRepository(conn).apply_rotation_to_range(
                employee_id, [morning_shift_id], date(2026, 8, 10), date(2026, 8, 1)
            )

    def test_apply_rotation_to_range_unknown_employee_raises(
        self, conn: sqlite3.Connection, morning_shift_id: int
    ) -> None:
        with pytest.raises(NotFoundError):
            DailyAssignmentRepository(conn).apply_rotation_to_range(
                999, [morning_shift_id], date(2026, 8, 1), date(2026, 8, 5)
            )

    def test_apply_rotation_to_range_unknown_shift_raises_with_no_partial_writes(
        self, conn: sqlite3.Connection, employee_id: int, morning_shift_id: int
    ) -> None:
        repo = DailyAssignmentRepository(conn)
        with pytest.raises(NotFoundError):
            repo.apply_rotation_to_range(
                employee_id, [morning_shift_id, 999], date(2026, 8, 1), date(2026, 8, 10)
            )
        assert repo.get_for_month(employee_id, 2026, 8) == {}

    def test_apply_rotation_to_range_single_day_uses_only_first_element(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int, morning_shift_id: int
    ) -> None:
        afternoon_shift = ShiftRepository(conn).create(
            make_shift_input(department_id=department_id, name="Turno tarde", start_time="15:00", end_time="22:00")
        )
        assert afternoon_shift.id is not None
        repo = DailyAssignmentRepository(conn)
        result = repo.apply_rotation_to_range(
            employee_id, [afternoon_shift.id, morning_shift_id], date(2026, 8, 1), date(2026, 8, 1)
        )
        assert result.marked == 1
        assert repo.get_for_month(employee_id, 2026, 8)[date(2026, 8, 1)].shift_id == afternoon_shift.id

    def test_get_for_department_month_excludes_other_departments(
        self, conn: sqlite3.Connection, department_id: int, morning_shift_id: int
    ) -> None:
        other_dept = DepartmentRepository(conn).create("Otro")
        assert other_dept.id is not None
        other_employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=other_dept.id, email="otro@x.com")
        )
        assert other_employee.id is not None
        other_shift = ShiftRepository(conn).create(make_shift_input(department_id=other_dept.id))
        assert other_shift.id is not None

        in_dept_employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id, email="dentro@x.com")
        )
        assert in_dept_employee.id is not None

        repo = DailyAssignmentRepository(conn)
        repo.set_day(in_dept_employee.id, date(2026, 8, 5), morning_shift_id)
        repo.set_day(other_employee.id, date(2026, 8, 5), other_shift.id)

        results = repo.get_for_department_month(department_id, 2026, 8)
        assert [a.employee_id for a in results] == [in_dept_employee.id]

    def test_deleting_employee_cascades_assignments(
        self, conn: sqlite3.Connection, employee_id: int, morning_shift_id: int
    ) -> None:
        DailyAssignmentRepository(conn).set_day(employee_id, date(2026, 8, 5), morning_shift_id)
        EmployeeRepository(conn).delete(employee_id)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM daily_shift_assignments WHERE employee_id = ?", (employee_id,)
        ).fetchone()[0]
        assert remaining == 0

    def test_list_all_for_employee_ignores_other_employees_and_orders_by_date(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int, morning_shift_id: int
    ) -> None:
        other_employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id, email="otro@x.com")
        )
        assert other_employee.id is not None
        repo = DailyAssignmentRepository(conn)
        repo.set_day(employee_id, date(2026, 8, 10), morning_shift_id)
        repo.set_day(employee_id, date(2026, 8, 3), morning_shift_id)
        repo.set_day(other_employee.id, date(2026, 8, 3), morning_shift_id)

        results = repo.list_all_for_employee(employee_id)
        assert [a.assignment_date for a in results] == [date(2026, 8, 3), date(2026, 8, 10)]


class TestTimeEntryRepository:
    @pytest.fixture()
    def department_id(self, conn: sqlite3.Connection) -> int:
        dept = DepartmentRepository(conn).create("Ventas")
        assert dept.id is not None
        return dept.id

    @pytest.fixture()
    def employee_id(self, conn: sqlite3.Connection, department_id: int) -> int:
        employee = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id)
        )
        assert employee.id is not None
        return employee.id

    @pytest.fixture()
    def base_day(self) -> date:
        # A fixed point safely in the past relative to "today" whenever this
        # suite runs, so create_manual()'s future-timestamp check never trips.
        return date.today() - timedelta(days=30)

    def test_clock_in_creates_an_entrada_entry(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = TimeEntryRepository(conn)
        entry = repo.clock(employee_id, "entrada")
        assert entry.entry_type == "entrada"
        assert entry.employee_id == employee_id

    def test_clock_out_after_clock_in(self, conn: sqlite3.Connection, employee_id: int) -> None:
        repo = TimeEntryRepository(conn)
        repo.clock(employee_id, "entrada")
        salida = repo.clock(employee_id, "salida")
        assert salida.entry_type == "salida"

    def test_clock_in_twice_in_a_row_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = TimeEntryRepository(conn)
        repo.clock(employee_id, "entrada")
        with pytest.raises(validation.ValidationError):
            repo.clock(employee_id, "entrada")

    def test_clock_out_without_clock_in_rejected(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = TimeEntryRepository(conn)
        with pytest.raises(validation.ValidationError):
            repo.clock(employee_id, "salida")

    def test_clock_unknown_employee_raises_not_found(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            TimeEntryRepository(conn).clock(999, "entrada")

    def test_last_entry_for_employee_none_when_no_entries(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        assert TimeEntryRepository(conn).last_entry_for_employee(employee_id) is None

    def test_last_entry_for_employee_reflects_most_recent(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = TimeEntryRepository(conn)
        repo.clock(employee_id, "entrada")
        repo.clock(employee_id, "salida")
        last = repo.last_entry_for_employee(employee_id)
        assert last is not None and last.entry_type == "salida"

    def test_create_manual_entry(
        self, conn: sqlite3.Connection, employee_id: int, base_day: date
    ) -> None:
        repo = TimeEntryRepository(conn)
        timestamp = datetime.combine(base_day, datetime.min.time()).replace(hour=9)
        entry = repo.create_manual(employee_id, "entrada", timestamp, note="olvidó fichar")
        assert entry.entry_timestamp == timestamp
        assert entry.note == "olvidó fichar"

    def test_create_manual_rejects_future_timestamp(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        future = datetime.now() + timedelta(days=1)
        with pytest.raises(validation.ValidationError):
            TimeEntryRepository(conn).create_manual(employee_id, "entrada", future)

    def test_create_manual_unknown_employee_raises_not_found(
        self, conn: sqlite3.Connection, base_day: date
    ) -> None:
        timestamp = datetime.combine(base_day, datetime.min.time())
        with pytest.raises(NotFoundError):
            TimeEntryRepository(conn).create_manual(999, "entrada", timestamp)

    def test_manual_entry_inserted_between_existing_pair_must_keep_alternation(
        self, conn: sqlite3.Connection, employee_id: int, base_day: date
    ) -> None:
        repo = TimeEntryRepository(conn)
        morning = datetime.combine(base_day, datetime.min.time()).replace(hour=9)
        evening = datetime.combine(base_day, datetime.min.time()).replace(hour=17)
        repo.create_manual(employee_id, "entrada", morning)
        repo.create_manual(employee_id, "salida", evening)

        noon = datetime.combine(base_day, datetime.min.time()).replace(hour=12)
        # Inserting another 'salida' between the existing entrada/salida pair
        # would produce entrada, salida, salida -- breaks alternation.
        with pytest.raises(validation.ValidationError):
            repo.create_manual(employee_id, "salida", noon)
        # Same for inserting another 'entrada' in that gap: entrada, entrada, salida.
        with pytest.raises(validation.ValidationError):
            repo.create_manual(employee_id, "entrada", noon)

    def test_manual_entry_appended_after_existing_pair_succeeds(
        self, conn: sqlite3.Connection, employee_id: int, base_day: date
    ) -> None:
        repo = TimeEntryRepository(conn)
        morning = datetime.combine(base_day, datetime.min.time()).replace(hour=9)
        evening = datetime.combine(base_day, datetime.min.time()).replace(hour=17)
        repo.create_manual(employee_id, "entrada", morning)
        repo.create_manual(employee_id, "salida", evening)

        night = datetime.combine(base_day, datetime.min.time()).replace(hour=20)
        entry = repo.create_manual(employee_id, "entrada", night)
        assert entry.entry_timestamp == night

    def test_update_entry(self, conn: sqlite3.Connection, employee_id: int, base_day: date) -> None:
        repo = TimeEntryRepository(conn)
        original = datetime.combine(base_day, datetime.min.time()).replace(hour=9)
        entry = repo.create_manual(employee_id, "entrada", original)
        assert entry.id is not None

        corrected = original.replace(hour=9, minute=15)
        updated = repo.update(entry.id, "entrada", corrected, note="hora corregida")
        assert updated.entry_timestamp == corrected
        assert updated.note == "hora corregida"

    def test_update_rejects_breaking_alternation(
        self, conn: sqlite3.Connection, employee_id: int, base_day: date
    ) -> None:
        repo = TimeEntryRepository(conn)
        morning = datetime.combine(base_day, datetime.min.time()).replace(hour=9)
        evening = datetime.combine(base_day, datetime.min.time()).replace(hour=17)
        repo.create_manual(employee_id, "entrada", morning)
        salida = repo.create_manual(employee_id, "salida", evening)
        assert salida.id is not None

        # Flipping the salida to another entrada would leave entrada, entrada.
        with pytest.raises(validation.ValidationError):
            repo.update(salida.id, "entrada", evening)

    def test_update_unknown_entry_raises_not_found(
        self, conn: sqlite3.Connection, base_day: date
    ) -> None:
        timestamp = datetime.combine(base_day, datetime.min.time())
        with pytest.raises(NotFoundError):
            TimeEntryRepository(conn).update(999, "entrada", timestamp)

    def test_delete_entry(self, conn: sqlite3.Connection, employee_id: int, base_day: date) -> None:
        repo = TimeEntryRepository(conn)
        timestamp = datetime.combine(base_day, datetime.min.time()).replace(hour=9)
        entry = repo.create_manual(employee_id, "entrada", timestamp)
        assert entry.id is not None
        repo.delete(entry.id)
        assert repo.last_entry_for_employee(employee_id) is None

    def test_delete_unknown_entry_raises_not_found(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(NotFoundError):
            TimeEntryRepository(conn).delete(999)

    def test_list_for_month_filters_by_month(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = TimeEntryRepository(conn)
        repo.create_manual(employee_id, "entrada", datetime(2026, 3, 10, 9, 0))
        repo.create_manual(employee_id, "salida", datetime(2026, 3, 10, 17, 0))
        repo.create_manual(employee_id, "entrada", datetime(2026, 4, 1, 9, 0))
        repo.create_manual(employee_id, "salida", datetime(2026, 4, 1, 17, 0))

        march_entries = repo.list_for_month(employee_id, 2026, 3)
        assert len(march_entries) == 2
        assert all(e.entry_timestamp.month == 3 for e in march_entries)

    def test_list_for_month_orders_chronologically(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        # Inserted directly via SQL, out of chronological order, bypassing
        # the repository's alternation validation -- that rule is covered
        # separately; this test isolates just the SELECT's ORDER BY.
        conn.execute(
            "INSERT INTO time_entries (employee_id, entry_type, entry_timestamp, note) "
            "VALUES (?, 'salida', ?, '')",
            (employee_id, "2026-03-10T17:00:00"),
        )
        conn.execute(
            "INSERT INTO time_entries (employee_id, entry_type, entry_timestamp, note) "
            "VALUES (?, 'entrada', ?, '')",
            (employee_id, "2026-03-10T09:00:00"),
        )
        conn.commit()
        entries = TimeEntryRepository(conn).list_for_month(employee_id, 2026, 3)
        assert [e.entry_timestamp.hour for e in entries] == [9, 17]

    def test_list_for_date_across_employees(
        self, conn: sqlite3.Connection, department_id: int
    ) -> None:
        emp1 = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id, email="uno@example.com")
        )
        emp2 = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id, email="dos@example.com")
        )
        assert emp1.id is not None and emp2.id is not None
        repo = TimeEntryRepository(conn)
        repo.create_manual(emp1.id, "entrada", datetime(2026, 3, 10, 9, 0))
        repo.create_manual(emp2.id, "entrada", datetime(2026, 3, 10, 9, 30))
        repo.create_manual(emp1.id, "salida", datetime(2026, 3, 11, 17, 0))

        day_entries = repo.list_for_date(date(2026, 3, 10))
        assert len(day_entries) == 2
        assert {e.employee_id for e in day_entries} == {emp1.id, emp2.id}

    def test_overnight_shift_alternation_across_midnight(
        self, conn: sqlite3.Connection, employee_id: int
    ) -> None:
        repo = TimeEntryRepository(conn)
        repo.create_manual(employee_id, "entrada", datetime(2026, 3, 10, 22, 0))
        salida = repo.create_manual(employee_id, "salida", datetime(2026, 3, 11, 6, 0))
        assert salida.entry_type == "salida"

    def test_list_all_for_employee_spans_every_month_and_excludes_others(
        self, conn: sqlite3.Connection, department_id: int, employee_id: int
    ) -> None:
        other = EmployeeRepository(conn).create(
            make_employee_input(department_id=department_id, email="otro@x.com")
        )
        assert other.id is not None
        repo = TimeEntryRepository(conn)
        # entrada/salida deben alternar en el tiempo (ver _validate_alternation),
        # así que March-entrada -> April-salida es la única secuencia válida
        # de dos fichajes que cae en meses distintos.
        repo.create_manual(employee_id, "entrada", datetime(2026, 3, 10, 9, 0))
        repo.create_manual(employee_id, "salida", datetime(2026, 4, 1, 17, 0))
        repo.create_manual(other.id, "entrada", datetime(2026, 3, 10, 9, 0))

        results = repo.list_all_for_employee(employee_id)
        assert [e.entry_timestamp for e in results] == [
            datetime(2026, 3, 10, 9, 0),
            datetime(2026, 4, 1, 17, 0),
        ]
