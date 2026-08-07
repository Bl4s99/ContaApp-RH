from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app import validation


class TestRequiredText:
    def test_strips_whitespace(self) -> None:
        assert validation.validate_required_text("  Ana  ", "nombre") == "Ana"

    @pytest.mark.parametrize("value", ["", "   "])
    def test_rejects_empty(self, value: str) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_required_text(value, "nombre")

    def test_rejects_too_long(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_required_text("a" * 101, "nombre")


class TestEmail:
    @pytest.mark.parametrize(
        "value",
        ["ana@example.com", "  Ana.Lopez@Example.CO  ", "a+b@sub.example.io"],
    )
    def test_accepts_valid(self, value: str) -> None:
        result = validation.validate_email(value)
        assert "@" in result
        assert result == result.lower()

    @pytest.mark.parametrize(
        "value", ["", "no-arroba.com", "sin-dominio@", "@sindominio.com", "con espacio@x.com"]
    )
    def test_rejects_invalid(self, value: str) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_email(value)


class TestPhone:
    def test_empty_is_allowed(self) -> None:
        assert validation.validate_phone("") == ""

    @pytest.mark.parametrize("value", ["+34 600 123 456", "(555) 123-4567", "123456"])
    def test_accepts_valid(self, value: str) -> None:
        assert validation.validate_phone(value) == value

    @pytest.mark.parametrize("value", ["abc", "123"])
    def test_rejects_invalid(self, value: str) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_phone(value)


class TestSalary:
    def test_accepts_zero(self) -> None:
        assert validation.validate_salary(0) == 0.0

    def test_rejects_negative(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_salary(-1)

    def test_rejects_unrealistic(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_salary(validation.MAX_SALARY + 1)


class TestMinimumSalary:
    def test_accepts_zero(self) -> None:
        assert validation.validate_minimum_salary(0) == 0.0

    def test_rejects_negative(self) -> None:
        with pytest.raises(validation.ValidationError) as exc_info:
            validation.validate_minimum_salary(-1)
        assert exc_info.value.field == "salario_minimo"

    def test_rejects_unrealistic(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_minimum_salary(validation.MAX_SALARY + 1)


class TestAccessPin:
    @pytest.mark.parametrize("value", ["1234", "123456", "0000", "  4321  "])
    def test_accepts_4_to_6_digits(self, value: str) -> None:
        result = validation.validate_access_pin(value)
        assert result == value.strip()

    @pytest.mark.parametrize("value", ["123", "1234567", "abcd", "", "12 34", "12.34", "-123"])
    def test_rejects_invalid_formats(self, value: str) -> None:
        with pytest.raises(validation.ValidationError) as exc_info:
            validation.validate_access_pin(value)
        assert exc_info.value.field == "pin"


class TestObjectiveTargetDate:
    def test_accepts_a_future_date(self) -> None:
        future = (date.today() + timedelta(days=30)).isoformat()
        assert validation.validate_objective_target_date(future) == date.today() + timedelta(
            days=30
        )

    def test_accepts_a_past_date(self) -> None:
        # A diferencia de la mayoría de fechas de este módulo, una fecha
        # objetivo pasada es un caso legítimo (backfill de un objetivo que
        # se olvidó dar de alta a tiempo), no se rechaza.
        past = (date.today() - timedelta(days=30)).isoformat()
        assert validation.validate_objective_target_date(past) == date.today() - timedelta(
            days=30
        )

    def test_rejects_empty(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_objective_target_date("")

    def test_rejects_bad_format(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_objective_target_date("31/12/2026")


class TestObjectiveStatus:
    @pytest.mark.parametrize("value", ["pendiente", "cumplido", "no_cumplido"])
    def test_accepts_valid_values(self, value: str) -> None:
        assert validation.validate_objective_status(value) == value

    @pytest.mark.parametrize("value", ["en_progreso", "", "Pendiente", "PENDIENTE"])
    def test_rejects_invalid_values(self, value: str) -> None:
        with pytest.raises(validation.ValidationError) as exc_info:
            validation.validate_objective_status(value)
        assert exc_info.value.field == "estado"


class TestReviewDate:
    def test_accepts_today(self) -> None:
        assert validation.validate_review_date(date.today().isoformat()) == date.today()

    def test_rejects_future(self) -> None:
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with pytest.raises(validation.ValidationError):
            validation.validate_review_date(tomorrow)

    def test_rejects_empty(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_review_date("")

    def test_rejects_bad_format(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_review_date("not-a-date")


class TestEquipmentAssignedDate:
    def test_accepts_today(self) -> None:
        assert (
            validation.validate_equipment_assigned_date(date.today().isoformat())
            == date.today()
        )

    def test_rejects_future(self) -> None:
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with pytest.raises(validation.ValidationError):
            validation.validate_equipment_assigned_date(tomorrow)

    def test_rejects_empty(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_equipment_assigned_date("")

    def test_rejects_bad_format(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_equipment_assigned_date("not-a-date")


class TestEquipmentReturnedDate:
    def test_accepts_today_when_assigned_before(self) -> None:
        assigned = date.today() - timedelta(days=10)
        assert (
            validation.validate_equipment_returned_date(date.today().isoformat(), assigned)
            == date.today()
        )

    def test_accepts_same_day_as_assigned(self) -> None:
        assigned = date.today()
        assert (
            validation.validate_equipment_returned_date(assigned.isoformat(), assigned)
            == assigned
        )

    def test_rejects_before_assigned_date(self) -> None:
        assigned = date.today()
        earlier = (assigned - timedelta(days=1)).isoformat()
        with pytest.raises(validation.ValidationError):
            validation.validate_equipment_returned_date(earlier, assigned)

    def test_rejects_future(self) -> None:
        assigned = date.today() - timedelta(days=10)
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with pytest.raises(validation.ValidationError):
            validation.validate_equipment_returned_date(tomorrow, assigned)

    def test_rejects_empty(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_equipment_returned_date("", date.today())

    def test_rejects_bad_format(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_equipment_returned_date("not-a-date", date.today())


class TestHireDate:
    def test_accepts_today(self) -> None:
        today = date.today()
        assert validation.validate_hire_date(today.isoformat()) == today

    def test_rejects_future(self) -> None:
        tomorrow = date.today() + timedelta(days=1)
        with pytest.raises(validation.ValidationError):
            validation.validate_hire_date(tomorrow.isoformat())

    @pytest.mark.parametrize("value", ["31/12/2024", "not-a-date", "2024-13-01"])
    def test_rejects_bad_format(self, value: str) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_hire_date(value)


class TestTimeHHMM:
    @pytest.mark.parametrize("value", ["00:00", "08:30", "23:59", " 09:15 "])
    def test_accepts_valid(self, value: str) -> None:
        assert validation.validate_time_hhmm(value, "hora") == value.strip()

    @pytest.mark.parametrize("value", ["24:00", "8:30", "08:60", "abc", "", "08-30"])
    def test_rejects_invalid(self, value: str) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_time_hhmm(value, "hora")


class TestTimeOrder:
    def test_accepts_end_after_start(self) -> None:
        validation.validate_time_order("08:00", "15:00")

    @pytest.mark.parametrize(("start", "end"), [("15:00", "08:00"), ("09:00", "09:00")])
    def test_rejects_end_not_after_start_by_default(self, start: str, end: str) -> None:
        # allow_overnight por defecto es False -- lo usa el segundo tramo de
        # un turno partido, que debe seguir siendo del mismo día (ver
        # TestSplitShiftTimes.test_rejects_second_stretch_out_of_order).
        with pytest.raises(validation.ValidationError):
            validation.validate_time_order(start, end)

    @pytest.mark.parametrize(("start", "end"), [("22:00", "06:00"), ("23:59", "00:00")])
    def test_allow_overnight_accepts_end_before_start(self, start: str, end: str) -> None:
        # Con allow_overnight=True (el turno principal, o el primer tramo de
        # uno partido), end < start significa un turno que cruza la
        # medianoche (p. ej. 22:00-06:00), no un error -- la capa de
        # fichajes (TimeEntryRepository._validate_alternation()) ya soporta
        # turnos nocturnos, así que la definición del turno no debía ser lo
        # único que lo impidiera.
        validation.validate_time_order(start, end, allow_overnight=True)

    def test_allow_overnight_still_rejects_exact_same_start_and_end(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_time_order("09:00", "09:00", allow_overnight=True)


class TestSplitShiftTimes:
    def test_both_blank_means_no_split_shift(self) -> None:
        assert validation.validate_split_shift_times(None, None, "14:30") is None
        assert validation.validate_split_shift_times("", "", "14:30") is None
        assert validation.validate_split_shift_times("  ", "  ", "14:30") is None

    def test_accepts_valid_second_stretch(self) -> None:
        result = validation.validate_split_shift_times("15:30", "17:00", "14:30")
        assert result == ("15:30", "17:00")

    @pytest.mark.parametrize(
        ("start_2", "end_2"), [("15:30", None), (None, "17:00"), ("15:30", ""), ("", "17:00")]
    )
    def test_rejects_only_one_side_provided(self, start_2: str | None, end_2: str | None) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_split_shift_times(start_2, end_2, "14:30")

    def test_rejects_second_stretch_out_of_order(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_split_shift_times("17:00", "15:30", "14:30")

    def test_rejects_second_stretch_overlapping_the_first(self) -> None:
        # First stretch ends at 14:30; second stretch can't start before that.
        with pytest.raises(validation.ValidationError):
            validation.validate_split_shift_times("14:00", "17:00", "14:30")

    def test_rejects_second_stretch_starting_exactly_when_first_ends(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_split_shift_times("14:30", "17:00", "14:30")

    def test_rejects_invalid_time_format(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_split_shift_times("bad", "17:00", "14:30")


class TestDaysOfWeek:
    def test_accepts_valid_subset(self) -> None:
        assert validation.validate_days_of_week([1, 3, 5]) == frozenset({1, 3, 5})

    def test_deduplicates(self) -> None:
        assert validation.validate_days_of_week([1, 1, 2]) == frozenset({1, 2})

    def test_rejects_empty(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_days_of_week([])

    @pytest.mark.parametrize("days", [[0], [8], [-1]])
    def test_rejects_out_of_range(self, days: list[int]) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_days_of_week(days)


class TestColorHex:
    @pytest.mark.parametrize("value", ["#2ecc71", "#ABCDEF", "#000000"])
    def test_accepts_valid(self, value: str) -> None:
        assert validation.validate_color_hex(value) == value

    @pytest.mark.parametrize("value", ["2ecc71", "#2ecc7", "#gggggg", "red", ""])
    def test_rejects_invalid(self, value: str) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_color_hex(value)


class TestNote:
    def test_strips_and_allows_empty(self) -> None:
        assert validation.validate_note("  ") == ""

    def test_rejects_too_long(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_note("a" * (validation.MAX_NOTE_LENGTH + 1))


class TestDateRange:
    def test_accepts_same_day_range(self) -> None:
        validation.validate_date_range(date(2026, 8, 1), date(2026, 8, 1))

    def test_accepts_normal_range(self) -> None:
        validation.validate_date_range(date(2026, 8, 1), date(2026, 8, 15))

    def test_rejects_end_before_start(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_date_range(date(2026, 8, 15), date(2026, 8, 1))

    def test_rejects_range_too_long(self) -> None:
        start = date(2026, 1, 1)
        end = start + timedelta(days=validation.MAX_RANGE_DAYS)
        with pytest.raises(validation.ValidationError):
            validation.validate_date_range(start, end)

    def test_accepts_range_at_the_limit(self) -> None:
        start = date(2026, 1, 1)
        end = start + timedelta(days=validation.MAX_RANGE_DAYS - 1)
        validation.validate_date_range(start, end)


class TestIban:
    def test_blank_is_allowed_and_returns_blank(self) -> None:
        assert validation.validate_iban("") == ""
        assert validation.validate_iban("   ") == ""

    @pytest.mark.parametrize(
        "value",
        [
            "ES9121000418450200051332",
            "es91 2100 0418 4502 0005 1332",  # lowercase + spaces, normalized
            "GB29NWBK60161331926819",
            "DE89370400440532013000",
            "FR1420041010050500013M02606",
        ],
    )
    def test_accepts_known_valid_ibans(self, value: str) -> None:
        result = validation.validate_iban(value)
        assert result.replace(" ", "") == value.replace(" ", "").upper()

    def test_formats_with_spaces_every_four_chars(self) -> None:
        assert validation.validate_iban("ES9121000418450200051332") == (
            "ES91 2100 0418 4502 0005 1332"
        )

    def test_rejects_bad_checksum(self) -> None:
        # Last digit tampered with -> mod-97 check digit no longer valid.
        with pytest.raises(validation.ValidationError):
            validation.validate_iban("ES9121000418450200051333")

    def test_rejects_wrong_length_for_spain(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_iban("ES912100041845020005133")  # one digit short

    @pytest.mark.parametrize("value", ["not-an-iban", "1234", "ES91-2100-0418"])
    def test_rejects_garbage_structure(self, value: str) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_iban(value)


class TestDependentChildren:
    @pytest.mark.parametrize("value", [0, 1, 5, validation.MAX_DEPENDENT_CHILDREN])
    def test_accepts_valid_counts(self, value: int) -> None:
        assert validation.validate_dependent_children(value) == value

    def test_rejects_negative(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_dependent_children(-1)

    def test_rejects_above_max(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_dependent_children(validation.MAX_DEPENDENT_CHILDREN + 1)


class TestPercentage:
    @pytest.mark.parametrize("value", [0, 6.35, 31.4, 100])
    def test_accepts_valid_range(self, value: float) -> None:
        assert validation.validate_percentage(value, "campo") == value

    def test_rejects_negative(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_percentage(-0.1, "campo")

    def test_rejects_above_100(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_percentage(100.1, "campo")


class TestUsername:
    def test_strips_whitespace(self) -> None:
        assert validation.validate_username("  admin  ") == "admin"

    def test_accepts_a_short_common_username(self) -> None:
        assert validation.validate_username("admin") == "admin"

    def test_rejects_too_short(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_username("ab")

    def test_rejects_too_long(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_username("a" * (validation.MAX_USERNAME_LENGTH + 1))

    def test_rejects_blank(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_username("   ")


class TestPassword:
    def test_rejects_the_old_seeded_admin_password(self) -> None:
        # El asistente de primer arranque (app/setup_wizard.py) sustituyó a
        # la semilla "admin"/"admin" -- esa contraseña ya no debe aceptarse.
        with pytest.raises(validation.ValidationError):
            validation.validate_password("admin")

    def test_rejects_too_short(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_password("abc")

    def test_does_not_strip_whitespace(self) -> None:
        # A password's whitespace is significant -- unlike a name field, it
        # must round-trip exactly as typed.
        assert validation.validate_password("  pass  ") == "  pass  "


class TestEmailProvider:
    @pytest.mark.parametrize("value", validation.EMAIL_PROVIDERS)
    def test_accepts_every_known_provider(self, value: str) -> None:
        assert validation.validate_email_provider(value) == value

    def test_rejects_unknown_provider(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_email_provider("yahoo")


class TestAppPassword:
    def test_accepts_a_value(self) -> None:
        assert validation.validate_app_password("abcd efgh ijkl") == "abcd efgh ijkl"

    def test_strips_whitespace(self) -> None:
        assert validation.validate_app_password("  secret  ") == "secret"

    def test_rejects_blank(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_app_password("   ")


class TestUserRoleAndDepartment:
    def test_admin_with_no_department_is_valid(self) -> None:
        assert validation.validate_user_role_and_department("admin", None) == ("admin", None)

    def test_encargado_with_department_is_valid(self) -> None:
        assert validation.validate_user_role_and_department("encargado", 3) == ("encargado", 3)

    def test_rejects_unknown_role(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_user_role_and_department("gerente", None)

    def test_rejects_encargado_without_department(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_user_role_and_department("encargado", None)

    def test_rejects_admin_with_department(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_user_role_and_department("admin", 3)


class TestThemeMode:
    @pytest.mark.parametrize("value", ["light", "dark"])
    def test_accepts_valid_modes(self, value: str) -> None:
        assert validation.validate_theme_mode(value) == value

    def test_rejects_unknown_mode(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_theme_mode("blue")

    def test_rejects_wrong_case(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_theme_mode("Light")


class TestTimeEntryType:
    @pytest.mark.parametrize("value", ["entrada", "salida"])
    def test_accepts_valid_types(self, value: str) -> None:
        assert validation.validate_time_entry_type(value) == value

    def test_rejects_unknown_type(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_time_entry_type("descanso")

    def test_rejects_wrong_case(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_time_entry_type("Entrada")


class TestTimeEntryTimestamp:
    def test_accepts_now(self) -> None:
        now = datetime.now()
        assert validation.validate_time_entry_timestamp(now) == now

    def test_accepts_past(self) -> None:
        past = datetime.now() - timedelta(days=1)
        assert validation.validate_time_entry_timestamp(past) == past

    def test_rejects_future(self) -> None:
        future = datetime.now() + timedelta(hours=1)
        with pytest.raises(validation.ValidationError):
            validation.validate_time_entry_timestamp(future)


class TestDniNie:
    def test_empty_is_allowed(self) -> None:
        assert validation.validate_dni_nie("") == ""
        assert validation.validate_dni_nie("   ") == ""

    @pytest.mark.parametrize("value", ["00000000T", "12345678Z", "99999999R"])
    def test_accepts_valid_dni(self, value: str) -> None:
        assert validation.validate_dni_nie(value) == value

    @pytest.mark.parametrize("value", ["X1234567L", "Y1234567X"])
    def test_accepts_valid_nie(self, value: str) -> None:
        assert validation.validate_dni_nie(value) == value

    def test_lowercase_is_normalized_to_uppercase(self) -> None:
        assert validation.validate_dni_nie("12345678z") == "12345678Z"
        assert validation.validate_dni_nie("x1234567l") == "X1234567L"

    def test_strips_surrounding_whitespace_and_internal_spaces(self) -> None:
        assert validation.validate_dni_nie("  1234 5678Z ") == "12345678Z"

    def test_rejects_wrong_control_letter(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_dni_nie("12345678A")

    def test_rejects_too_few_digits(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_dni_nie("1234567Z")

    def test_rejects_missing_letter(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_dni_nie("123456789")

    def test_rejects_invalid_nie_prefix(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_dni_nie("A1234567L")


class TestCif:
    # Dígitos de control calculados hacia adelante con el propio algoritmo
    # (suma de posiciones pares + posiciones impares dobladas y reducidas),
    # no copiados de una lista de CIFs "conocidos" -- más fiable para
    # comprobar que el algoritmo es internamente consistente.
    def test_empty_is_allowed(self) -> None:
        assert validation.validate_cif("") == ""
        assert validation.validate_cif("   ") == ""

    @pytest.mark.parametrize(
        "value",
        [
            "B23456718",  # letra que exige dígito de control
            "N3456712C",  # letra que exige letra de control
            "C45671237",  # letra que acepta ambas formas -- forma dígito
            "C4567123G",  # letra que acepta ambas formas -- forma letra
        ],
    )
    def test_accepts_valid_cif(self, value: str) -> None:
        assert validation.validate_cif(value) == value

    def test_lowercase_is_normalized_to_uppercase(self) -> None:
        assert validation.validate_cif("b23456718") == "B23456718"

    def test_rejects_letter_form_when_digit_required(self) -> None:
        # "B" exige dígito de control -- la letra correspondiente no vale.
        with pytest.raises(validation.ValidationError):
            validation.validate_cif("B2345671H")

    def test_rejects_digit_form_when_letter_required(self) -> None:
        # "N" exige letra de control -- el dígito correspondiente no vale.
        with pytest.raises(validation.ValidationError):
            validation.validate_cif("N34567123")

    def test_rejects_unknown_organization_letter(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_cif("K23456718")

    def test_rejects_wrong_length(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_cif("B234567")


class TestCompanyNif:
    def test_empty_is_allowed(self) -> None:
        assert validation.validate_company_nif("") == ""

    def test_accepts_valid_dni(self) -> None:
        assert validation.validate_company_nif("12345678Z") == "12345678Z"

    def test_accepts_valid_cif(self) -> None:
        assert validation.validate_company_nif("B23456718") == "B23456718"

    def test_rejects_garbage_matching_neither_format(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_company_nif("no-es-un-nif")


class TestSsNumber:
    def test_empty_is_allowed(self) -> None:
        assert validation.validate_ss_number("") == ""

    def test_accepts_twelve_digits(self) -> None:
        assert validation.validate_ss_number("281234567890") == "281234567890"

    def test_strips_common_separators(self) -> None:
        assert validation.validate_ss_number("28/12345678/90") == "281234567890"
        assert validation.validate_ss_number("28-12345678-90") == "281234567890"
        assert validation.validate_ss_number("28 1234 5678 90") == "281234567890"

    def test_rejects_wrong_digit_count(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_ss_number("2812345678")

    def test_rejects_non_digits(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_ss_number("28123456789A")


class TestContractType:
    @pytest.mark.parametrize("value", validation.CONTRACT_TYPES)
    def test_accepts_every_known_type(self, value: str) -> None:
        assert validation.validate_contract_type(value) == value

    def test_rejects_unknown_type(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_contract_type("Becario")


class TestContractEndDate:
    def test_empty_is_allowed_for_any_type(self) -> None:
        assert validation.validate_contract_end_date("", "Temporal", date(2024, 1, 1)) is None
        assert validation.validate_contract_end_date("", "Indefinido", date(2024, 1, 1)) is None

    def test_accepts_valid_date_for_temporal(self) -> None:
        result = validation.validate_contract_end_date(
            "2026-12-31", "Temporal", date(2024, 1, 1)
        )
        assert result == date(2026, 12, 31)

    def test_rejects_end_date_for_indefinido(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_contract_end_date("2026-12-31", "Indefinido", date(2024, 1, 1))

    def test_rejects_end_date_before_hire_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_contract_end_date(
                "2023-12-31", "Temporal", date(2024, 1, 1)
            )

    def test_accepts_end_date_equal_to_hire_date(self) -> None:
        result = validation.validate_contract_end_date(
            "2024-01-01", "Temporal", date(2024, 1, 1)
        )
        assert result == date(2024, 1, 1)

    def test_rejects_malformed_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_contract_end_date("31/12/2026", "Temporal", date(2024, 1, 1))


class TestBirthDate:
    def test_empty_is_allowed(self) -> None:
        assert validation.validate_birth_date("", date(2024, 1, 1)) is None

    def test_accepts_a_valid_past_date(self) -> None:
        result = validation.validate_birth_date("1990-05-20", date(2024, 1, 1))
        assert result == date(1990, 5, 20)

    def test_rejects_todays_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_birth_date(date.today().isoformat(), date(2024, 1, 1))

    def test_rejects_a_future_date(self) -> None:
        future = date.today() + timedelta(days=1)
        with pytest.raises(validation.ValidationError):
            validation.validate_birth_date(future.isoformat(), date(2024, 1, 1))

    def test_rejects_birth_date_after_hire_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_birth_date("2024-06-01", date(2024, 1, 1))

    def test_accepts_birth_date_exactly_the_minimum_working_age_before_hire_date(self) -> None:
        # Antes de la edad laboral mínima (ver test_rejects_below_minimum_
        # working_age más abajo), este caso límite era "nacimiento igual a
        # ingreso" (0 años) -- ya no es una fecha válida, así que el nuevo
        # límite real es la edad mínima exacta, no la igualdad de fechas.
        result = validation.validate_birth_date("2008-01-01", date(2024, 1, 1))
        assert result == date(2008, 1, 1)

    def test_rejects_below_minimum_working_age(self) -> None:
        # Regresión: solo se comprobaba que el nacimiento no fuera
        # posterior al ingreso, sin ninguna edad mínima entre ambas fechas
        # -- se podía contratar a alguien con semanas o meses de edad.
        with pytest.raises(validation.ValidationError):
            validation.validate_birth_date("2008-01-02", date(2024, 1, 1))

    def test_minimum_working_age_handles_leap_day_birthdays(self) -> None:
        # 29 de febrero de un año bisiesto + 16 años cae en un año no
        # bisiesto -- mismo criterio que _next_anniversary() en alerts.py.
        result = validation.validate_birth_date("2008-02-29", date(2024, 3, 1))
        assert result == date(2008, 2, 29)

    def test_rejects_malformed_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_birth_date("20/05/1990", date(2024, 1, 1))


class TestNextMedicalCheckupDate:
    def test_empty_is_allowed(self) -> None:
        assert validation.validate_next_medical_checkup_date("") is None

    def test_accepts_a_future_date(self) -> None:
        future = date.today() + timedelta(days=30)
        assert validation.validate_next_medical_checkup_date(future.isoformat()) == future

    def test_accepts_a_past_date_since_overdue_is_a_valid_state(self) -> None:
        past = date.today() - timedelta(days=10)
        assert validation.validate_next_medical_checkup_date(past.isoformat()) == past

    def test_rejects_malformed_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_next_medical_checkup_date("not-a-date")


class TestPrlTrainingDate:
    def test_empty_is_allowed(self) -> None:
        assert validation.validate_prl_training_date("", date(2024, 1, 1)) is None

    def test_accepts_a_past_date_on_or_after_hire(self) -> None:
        result = validation.validate_prl_training_date("2024-02-01", date(2024, 1, 1))
        assert result == date(2024, 2, 1)

    def test_accepts_todays_date(self) -> None:
        today = date.today()
        assert validation.validate_prl_training_date(today.isoformat(), date(2020, 1, 1)) == today

    def test_rejects_a_future_date(self) -> None:
        future = date.today() + timedelta(days=1)
        with pytest.raises(validation.ValidationError):
            validation.validate_prl_training_date(future.isoformat(), date(2020, 1, 1))

    def test_rejects_date_before_hire_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_prl_training_date("2023-12-31", date(2024, 1, 1))

    def test_accepts_date_equal_to_hire_date(self) -> None:
        result = validation.validate_prl_training_date("2024-01-01", date(2024, 1, 1))
        assert result == date(2024, 1, 1)

    def test_rejects_malformed_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_prl_training_date("01/02/2024", date(2024, 1, 1))


class TestWorkAccidentValidation:
    @pytest.mark.parametrize("value", validation.WORK_ACCIDENT_SEVERITIES)
    def test_accepts_every_known_severity(self, value: str) -> None:
        assert validation.validate_work_accident_severity(value) == value

    def test_rejects_unknown_severity(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_work_accident_severity("Catastrófico")

    def test_accident_date_accepts_a_past_date_on_or_after_hire(self) -> None:
        result = validation.validate_work_accident_date("2024-02-01", date(2024, 1, 1))
        assert result == date(2024, 2, 1)

    def test_accident_date_rejects_empty(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_work_accident_date("", date(2024, 1, 1))

    def test_accident_date_rejects_a_future_date(self) -> None:
        future = date.today() + timedelta(days=1)
        with pytest.raises(validation.ValidationError):
            validation.validate_work_accident_date(future.isoformat(), date(2020, 1, 1))

    def test_accident_date_rejects_date_before_hire_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_work_accident_date("2023-12-31", date(2024, 1, 1))

    def test_accident_date_rejects_malformed_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_work_accident_date("01/02/2024", date(2024, 1, 1))

    def test_accident_date_accepts_on_or_before_termination_date(self) -> None:
        result = validation.validate_work_accident_date(
            "2024-06-01", date(2024, 1, 1), date(2024, 6, 1)
        )
        assert result == date(2024, 6, 1)

    def test_accident_date_rejects_date_after_termination_date(self) -> None:
        # Regresión: se podía registrar un accidente para un empleado ya
        # inactivo con fecha posterior a su propia baja -- alcanzable
        # desde la app normal (filtrar por "Inactivos", elegir cualquier
        # ex-empleado). Una fecha ANTERIOR a la baja sigue siendo válida
        # (una corrección histórica introducida después de tramitarla).
        with pytest.raises(validation.ValidationError):
            validation.validate_work_accident_date(
                "2024-06-15", date(2024, 1, 1), date(2024, 6, 1)
            )

    def test_accident_date_no_termination_date_means_no_upper_bound(self) -> None:
        # Empleado activo (termination_date=None): sin límite superior más
        # allá de "hoy", ya comprobado en test_accident_date_rejects_a_future_date.
        result = validation.validate_work_accident_date("2024-06-15", date(2024, 1, 1), None)
        assert result == date(2024, 6, 15)


class TestItContingency:
    @pytest.mark.parametrize("value", validation.IT_CONTINGENCIES)
    def test_accepts_every_known_contingency(self, value: str) -> None:
        assert validation.validate_it_contingency(value) == value

    def test_rejects_unknown_contingency(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_it_contingency("Enfermedad profesional")


class TestItLeaveDate:
    def test_accepts_a_past_date_on_or_after_hire(self) -> None:
        assert validation.validate_it_leave_date("2024-02-01", date(2024, 1, 1)) == date(
            2024, 2, 1
        )

    def test_rejects_empty(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_it_leave_date("", date(2024, 1, 1))

    def test_rejects_a_future_date(self) -> None:
        future = date.today() + timedelta(days=1)
        with pytest.raises(validation.ValidationError):
            validation.validate_it_leave_date(future.isoformat(), date(2020, 1, 1))

    def test_rejects_date_before_hire_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_it_leave_date("2023-12-31", date(2024, 1, 1))

    def test_rejects_malformed_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_it_leave_date("01/02/2024", date(2024, 1, 1))

    def test_rejects_date_after_termination_date(self) -> None:
        # Regresión: se podía abrir un episodio de IT para un empleado ya
        # inactivo con fecha posterior a su propia baja.
        with pytest.raises(validation.ValidationError):
            validation.validate_it_leave_date("2024-06-15", date(2024, 1, 1), date(2024, 6, 1))

    def test_accepts_date_on_or_before_termination_date(self) -> None:
        result = validation.validate_it_leave_date(
            "2024-06-01", date(2024, 1, 1), date(2024, 6, 1)
        )
        assert result == date(2024, 6, 1)


class TestItConfirmationDate:
    def test_empty_is_allowed(self) -> None:
        assert validation.validate_it_confirmation_date("", date(2026, 1, 1)) is None

    def test_accepts_a_date_on_or_after_leave_date(self) -> None:
        result = validation.validate_it_confirmation_date("2026-01-15", date(2026, 1, 1))
        assert result == date(2026, 1, 15)

    def test_rejects_a_future_date(self) -> None:
        future = date.today() + timedelta(days=1)
        with pytest.raises(validation.ValidationError):
            validation.validate_it_confirmation_date(future.isoformat(), date(2020, 1, 1))

    def test_rejects_date_before_leave_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_it_confirmation_date("2025-12-31", date(2026, 1, 1))

    def test_rejects_malformed_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_it_confirmation_date("01/02/2024", date(2024, 1, 1))

    def test_rejects_date_before_last_confirmation_date(self) -> None:
        # Regresión: se podía "retroceder" en el tiempo -- una nueva
        # confirmación anterior a la ya registrada no tiene sentido clínico.
        with pytest.raises(validation.ValidationError):
            validation.validate_it_confirmation_date(
                "2026-01-10", date(2026, 1, 1), date(2026, 1, 20)
            )

    def test_accepts_date_on_or_after_last_confirmation_date(self) -> None:
        result = validation.validate_it_confirmation_date(
            "2026-01-25", date(2026, 1, 1), date(2026, 1, 20)
        )
        assert result == date(2026, 1, 25)


class TestItReturnDate:
    def test_empty_is_allowed(self) -> None:
        assert validation.validate_it_return_date("", date(2026, 1, 1)) is None

    def test_accepts_a_date_on_or_after_leave_date(self) -> None:
        result = validation.validate_it_return_date("2026-01-15", date(2026, 1, 1))
        assert result == date(2026, 1, 15)

    def test_rejects_a_future_date(self) -> None:
        future = date.today() + timedelta(days=1)
        with pytest.raises(validation.ValidationError):
            validation.validate_it_return_date(future.isoformat(), date(2020, 1, 1))

    def test_rejects_date_before_leave_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_it_return_date("2025-12-31", date(2026, 1, 1))

    def test_rejects_malformed_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_it_return_date("01/02/2024", date(2024, 1, 1))

    def test_rejects_date_before_last_confirmation_date(self) -> None:
        # Regresión: se podía cerrar el episodio (alta médica) con fecha
        # ANTERIOR a la última confirmación de que la baja seguía vigente
        # -- clínicamente imposible.
        with pytest.raises(validation.ValidationError):
            validation.validate_it_return_date(
                "2026-01-10", date(2026, 1, 1), date(2026, 1, 20)
            )

    def test_accepts_date_on_or_after_last_confirmation_date(self) -> None:
        result = validation.validate_it_return_date(
            "2026-01-25", date(2026, 1, 1), date(2026, 1, 20)
        )
        assert result == date(2026, 1, 25)


class TestAnnualVacationDays:
    def test_accepts_the_default(self) -> None:
        assert validation.validate_annual_vacation_days(22) == 22.0

    def test_accepts_zero(self) -> None:
        assert validation.validate_annual_vacation_days(0) == 0.0

    def test_rejects_negative(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_annual_vacation_days(-1)

    def test_rejects_unreasonably_large(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_annual_vacation_days(400)


class TestDataRetentionYears:
    def test_accepts_the_default(self) -> None:
        assert validation.validate_data_retention_years(4) == 4

    def test_accepts_zero(self) -> None:
        assert validation.validate_data_retention_years(0) == 0

    def test_rejects_negative(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_data_retention_years(-1)

    def test_rejects_unreasonably_large(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_data_retention_years(200)


class TestDocumentCategory:
    @pytest.mark.parametrize("value", validation.DOCUMENT_CATEGORIES)
    def test_accepts_every_known_category(self, value: str) -> None:
        assert validation.validate_document_category(value) == value

    def test_rejects_unknown_category(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_document_category("Factura")


class TestDocumentFilename:
    def test_accepts_a_normal_filename(self) -> None:
        assert validation.validate_document_filename("contrato.pdf") == "contrato.pdf"

    def test_strips_surrounding_whitespace(self) -> None:
        assert validation.validate_document_filename("  contrato.pdf  ") == "contrato.pdf"

    def test_rejects_empty(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_document_filename("   ")

    def test_rejects_too_long(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_document_filename("a" * 300 + ".pdf")


class TestDocumentContent:
    def test_accepts_nonempty_bytes(self) -> None:
        assert validation.validate_document_content(b"%PDF-1.4 fake content") == b"%PDF-1.4 fake content"

    def test_rejects_empty_bytes(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_document_content(b"")

    def test_rejects_oversized_content(self) -> None:
        too_big = b"x" * (validation.MAX_DOCUMENT_SIZE_BYTES + 1)
        with pytest.raises(validation.ValidationError):
            validation.validate_document_content(too_big)

    def test_accepts_content_at_exactly_the_limit(self) -> None:
        at_limit = b"x" * validation.MAX_DOCUMENT_SIZE_BYTES
        assert validation.validate_document_content(at_limit) == at_limit


class TestHolidayLabel:
    def test_strips_whitespace(self) -> None:
        assert validation.validate_holiday_label("  Año Nuevo  ") == "Año Nuevo"

    @pytest.mark.parametrize("value", ["", "   "])
    def test_rejects_empty(self, value: str) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_holiday_label(value)

    def test_rejects_too_long(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_holiday_label("a" * 101)


class TestParseHolidayImportText:
    def test_parses_a_single_line_with_label(self) -> None:
        result = validation.parse_holiday_import_text("2026-01-01 Año Nuevo")
        assert result == [(date(2026, 1, 1), "Año Nuevo")]

    def test_defaults_label_when_missing(self) -> None:
        result = validation.parse_holiday_import_text("2026-01-01")
        assert result == [(date(2026, 1, 1), validation.DEFAULT_HOLIDAY_LABEL)]

    def test_parses_multiple_lines_preserving_order(self) -> None:
        text = "2026-05-01 Fiesta del Trabajo\n2026-01-06 Reyes\n2026-12-25 Navidad"
        result = validation.parse_holiday_import_text(text)
        assert result == [
            (date(2026, 5, 1), "Fiesta del Trabajo"),
            (date(2026, 1, 6), "Reyes"),
            (date(2026, 12, 25), "Navidad"),
        ]

    def test_ignores_blank_lines(self) -> None:
        text = "2026-01-01 Año Nuevo\n\n   \n2026-12-25 Navidad"
        result = validation.parse_holiday_import_text(text)
        assert len(result) == 2

    def test_ignores_comment_lines(self) -> None:
        text = "# Nacional\n2026-01-01 Año Nuevo\n# Autonómico\n2026-03-19 San José"
        result = validation.parse_holiday_import_text(text)
        assert result == [(date(2026, 1, 1), "Año Nuevo"), (date(2026, 3, 19), "San José")]

    def test_strips_extra_whitespace_from_label(self) -> None:
        result = validation.parse_holiday_import_text("2026-01-01    Año Nuevo   ")
        assert result == [(date(2026, 1, 1), "Año Nuevo")]

    def test_rejects_malformed_line(self) -> None:
        with pytest.raises(validation.ValidationError, match="línea 1"):
            validation.parse_holiday_import_text("01/01/2026 Año Nuevo")

    def test_rejects_invalid_calendar_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.parse_holiday_import_text("2026-13-01 Fecha imposible")

    def test_reports_the_correct_line_number(self) -> None:
        text = "2026-01-01 Año Nuevo\n\nnot-a-date"
        with pytest.raises(validation.ValidationError, match="línea 3"):
            validation.parse_holiday_import_text(text)

    def test_rejects_duplicate_date_in_the_same_text(self) -> None:
        text = "2026-01-01 Año Nuevo\n2026-01-01 Repetido"
        with pytest.raises(validation.ValidationError, match="más de una vez"):
            validation.parse_holiday_import_text(text)

    def test_rejects_empty_text(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.parse_holiday_import_text("")

    def test_rejects_text_with_only_comments(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.parse_holiday_import_text("# Nacional\n# Autonómico")

    def test_rejects_too_many_dates(self) -> None:
        # Más de un año natural de fechas *distintas* (day-by-day, cruzando a
        # 2027) -- así el límite se dispara por cantidad, no por la
        # comprobación de fechas repetidas.
        day_count = validation.MAX_HOLIDAY_IMPORT_LINES + 10
        days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(day_count)]
        text = "\n".join(f"{d.isoformat()} Festivo" for d in days)
        with pytest.raises(validation.ValidationError):
            validation.parse_holiday_import_text(text)


class TestDocumentTemplateBody:
    def test_strips_whitespace(self) -> None:
        assert validation.validate_document_template_body("  Hola {nombre}.  ") == "Hola {nombre}."

    @pytest.mark.parametrize("value", ["", "   "])
    def test_rejects_empty(self, value: str) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_document_template_body(value)

    def test_rejects_too_long(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_document_template_body(
                "a" * (validation.MAX_DOCUMENT_TEMPLATE_BODY_LENGTH + 1)
            )

    def test_accepts_content_at_exactly_the_limit(self) -> None:
        body = "a" * validation.MAX_DOCUMENT_TEMPLATE_BODY_LENGTH
        assert validation.validate_document_template_body(body) == body


class TestCandidatePhase:
    @pytest.mark.parametrize("value", validation.CANDIDATE_PHASES)
    def test_accepts_every_known_phase(self, value: str) -> None:
        assert validation.validate_candidate_phase(value) == value

    def test_rejects_unknown_phase(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_candidate_phase("Fase inventada")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_candidate_phase("")


class TestTerminationDate:
    def test_accepts_a_valid_past_date(self) -> None:
        result = validation.validate_termination_date("2024-06-01", date(2024, 1, 1))
        assert result == date(2024, 6, 1)

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_termination_date("", date(2024, 1, 1))

    def test_rejects_invalid_format(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_termination_date("01/06/2024", date(2024, 1, 1))

    def test_rejects_date_before_hire_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_termination_date("2023-12-31", date(2024, 1, 1))

    def test_accepts_todays_date(self) -> None:
        today = date.today()
        assert validation.validate_termination_date(today.isoformat(), date(2020, 1, 1)) == today

    def test_rejects_a_future_date(self) -> None:
        # Regresión: era el único validador de fecha del dominio que
        # admitía el futuro -- una fecha de baja futura dejaba al empleado
        # inactivo DESDE HOY (terminate() aplica active=0 de inmediato) y
        # generaba un finiquito permanente calculado como si la baja ya
        # hubiera ocurrido.
        future = date.today() + timedelta(days=1)
        with pytest.raises(validation.ValidationError):
            validation.validate_termination_date(future.isoformat(), date(2020, 1, 1))


class TestTrainingCompletionDate:
    def test_accepts_a_past_date(self) -> None:
        assert validation.validate_training_completion_date("2024-01-01") == date(2024, 1, 1)

    def test_accepts_todays_date(self) -> None:
        today = date.today()
        assert validation.validate_training_completion_date(today.isoformat()) == today

    def test_rejects_empty(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_training_completion_date("")

    def test_rejects_a_future_date(self) -> None:
        future = date.today() + timedelta(days=1)
        with pytest.raises(validation.ValidationError):
            validation.validate_training_completion_date(future.isoformat())

    def test_rejects_malformed_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_training_completion_date("01/02/2024")

    def test_accepts_a_date_long_before_any_hire_date(self) -> None:
        # A diferencia de un accidente de trabajo, una certificación puede
        # haberse obtenido mucho antes de trabajar aquí -- deliberadamente
        # sin comprobación de hire_date (ver EmployeeTraining).
        assert validation.validate_training_completion_date("2005-01-01") == date(2005, 1, 1)


class TestTrainingExpirationDate:
    def test_empty_is_allowed(self) -> None:
        assert validation.validate_training_expiration_date("", date(2024, 1, 1)) is None

    def test_accepts_a_date_after_completion(self) -> None:
        result = validation.validate_training_expiration_date("2027-01-01", date(2024, 1, 1))
        assert result == date(2027, 1, 1)

    def test_rejects_a_date_before_completion(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_training_expiration_date("2023-01-01", date(2024, 1, 1))

    def test_rejects_a_date_equal_to_completion(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_training_expiration_date("2024-01-01", date(2024, 1, 1))

    def test_rejects_malformed_date(self) -> None:
        with pytest.raises(validation.ValidationError):
            validation.validate_training_expiration_date("01/02/2027", date(2024, 1, 1))
