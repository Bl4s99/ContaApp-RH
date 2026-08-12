from __future__ import annotations

from datetime import date, datetime

from app.models import Employee, PayrollRecord, PayrollSupplement
from app.payroll import calculate_monthly_payroll
from app.payroll_pdf import (
    CompanyInfo,
    _category_line,
    _deducciones_rows,
    _devengos_no_salariales_rows,
    _devengos_salariales_rows,
    _format_currency,
    _format_percentage,
    _period_days,
    _seniority_text,
    build_payroll_pdf,
)


def make_employee(**overrides: object) -> Employee:
    defaults: dict[str, object] = dict(
        id=1,
        first_name="Ana",
        last_name="Lopez",
        email="ana@example.com",
        phone="+34 600 111 222",
        position="Ingeniera",
        department_id=1,
        shift_id=None,
        salary=28000.0,
        hire_date=date(2021, 3, 15),
        active=True,
        bank_account="",
        photo=None,
        dependent_children=0,
        dni_nie="12345678Z",
        ss_number="281234567890",
        contract_type="Indefinido",
        contract_end_date=None,
        birth_date=None,
        next_medical_checkup_date=None,
        termination_date=None,
        termination_reason=None,
        anonymized=False,
        prl_training_date=None,
        manager_id=None,
        head_of_department_id=None,
        professional_category_id=None,
    )
    defaults.update(overrides)
    return Employee(**defaults)  # type: ignore[arg-type]


def make_record(**overrides: object) -> PayrollRecord:
    payroll = calculate_monthly_payroll(
        annual_gross_salary=28000.0,
        dependent_children=0,
        ss_employee_pct=6.35,
        ss_employer_pct=31.40,
        month=3,
        year=2026,
        irpf_pct_override=15.0,
    )
    defaults: dict[str, object] = dict(
        id=1,
        employee_id=1,
        generated_at=datetime(2026, 3, 28, 10, 0),
        annual_gross_salary_snapshot=28000.0,
        dependent_children_snapshot=0,
        payroll=payroll,
    )
    defaults.update(overrides)
    return PayrollRecord(**defaults)  # type: ignore[arg-type]


def make_supplement(**overrides: object) -> PayrollSupplement:
    defaults: dict[str, object] = dict(
        id=1,
        employee_id=1,
        year=2026,
        month=3,
        supplement_type="plus",
        description="Plus de idiomas",
        amount=100.0,
        hours=None,
        rate_per_hour=None,
        created_at=datetime(2026, 3, 1),
    )
    defaults.update(overrides)
    return PayrollSupplement(**defaults)  # type: ignore[arg-type]


class TestFormatCurrency:
    def test_uses_spanish_thousands_and_decimal_separators(self) -> None:
        assert _format_currency(2285.71) == "2.285,71 €"

    def test_zero(self) -> None:
        assert _format_currency(0.0) == "0,00 €"


class TestFormatPercentage:
    def test_integer_value_has_no_decimal(self) -> None:
        assert _format_percentage(6.35) == "6,35%"

    def test_uses_comma_not_dot(self) -> None:
        assert _format_percentage(14.5) == "14,5%"
        assert "." not in _format_percentage(14.5)


class TestPeriodDays:
    def test_thirty_one_day_month(self) -> None:
        assert _period_days(2026, 3) == 31

    def test_february_non_leap_year(self) -> None:
        assert _period_days(2026, 2) == 28

    def test_february_leap_year(self) -> None:
        assert _period_days(2028, 2) == 29


class TestSeniorityText:
    def test_exact_years(self) -> None:
        assert _seniority_text(date(2021, 3, 15), date(2026, 3, 15)) == "5 años"

    def test_years_and_months(self) -> None:
        assert _seniority_text(date(2021, 3, 15), date(2026, 7, 31)) == "5 años y 4 meses"

    def test_day_of_month_not_yet_reached_does_not_round_up(self) -> None:
        # Contratado el 20, a fecha del 10 del mes siguiente todavía no se
        # ha cumplido el mes completo.
        assert _seniority_text(date(2025, 6, 20), date(2025, 7, 10)) == "menos de 1 mes"

    def test_less_than_one_month(self) -> None:
        assert _seniority_text(date(2026, 3, 20), date(2026, 3, 25)) == "menos de 1 mes"

    def test_single_year_and_single_month_use_singular(self) -> None:
        assert _seniority_text(date(2025, 2, 15), date(2026, 3, 15)) == "1 año y 1 mes"


class TestCategoryLine:
    def test_uses_category_name_when_available(self) -> None:
        assert _category_line("Ingeniera", "Técnico de nivel 2") == (
            "Categoría profesional",
            "Técnico de nivel 2",
        )

    def test_falls_back_to_position_with_a_different_label(self) -> None:
        # No debe hacerse pasar el puesto libre por la categoría formal del
        # convenio -- ver el comentario en app/payroll_pdf.py.
        assert _category_line("Ingeniera", None) == ("Puesto", "Ingeniera")


class TestDevengosSalarialesRows:
    def test_includes_paga_ordinaria(self) -> None:
        record = make_record()
        rows = _devengos_salariales_rows(record, ())
        labels = [label for label, _ in rows]
        assert "Salario base (paga ordinaria)" in labels

    def test_omits_paga_extra_when_zero(self) -> None:
        record = make_record()  # marzo: no es mes de paga extra
        rows = _devengos_salariales_rows(record, ())
        labels = [label for label, _ in rows]
        assert not any("extraordinaria" in label for label in labels)

    def test_includes_plus_and_horas_extra_supplements(self) -> None:
        record = make_record()
        supplements = [
            make_supplement(supplement_type="plus", description="Plus de idiomas", amount=100.0),
            make_supplement(
                id=2, supplement_type="horas_extra", description="5h extra", amount=50.0
            ),
        ]
        rows = _devengos_salariales_rows(record, supplements)
        labels = [label for label, _ in rows]
        assert any("Plus de idiomas" in label for label in labels)
        assert any("5h extra" in label for label in labels)

    def test_includes_bonos_supplements(self) -> None:
        # Un bono tributa igual que un plus -- pertenece a este desglose,
        # no al de percepciones no salariales.
        record = make_record()
        supplements = [make_supplement(supplement_type="bonos", description="Bono Q1", amount=200.0)]
        rows = _devengos_salariales_rows(record, supplements)
        labels = [label for label, _ in rows]
        assert any("Bono Q1" in label for label in labels)

    def test_excludes_anticipo_supplements(self) -> None:
        record = make_record()
        supplements = [make_supplement(supplement_type="anticipo", description="Anticipo marzo")]
        rows = _devengos_salariales_rows(record, supplements)
        labels = [label for label, _ in rows]
        assert not any("Anticipo" in label for label in labels)

    def test_excludes_dietas_supplements(self) -> None:
        # Las dietas son percepción no salarial -- ver TestDevengosNoSalarialesRows.
        record = make_record()
        supplements = [make_supplement(supplement_type="dietas", description="Viaje a Madrid")]
        rows = _devengos_salariales_rows(record, supplements)
        labels = [label for label, _ in rows]
        assert not any("Viaje a Madrid" in label for label in labels)


class TestDevengosNoSalarialesRows:
    def test_empty_without_dietas(self) -> None:
        supplements = [
            make_supplement(supplement_type="plus", description="Plus de idiomas"),
            make_supplement(id=2, supplement_type="anticipo", description="Anticipo marzo"),
        ]
        assert _devengos_no_salariales_rows(supplements) == []

    def test_includes_dietas(self) -> None:
        supplements = [
            make_supplement(supplement_type="dietas", description="Viaje a Madrid", amount=45.0)
        ]
        rows = _devengos_no_salariales_rows(supplements)
        labels = [label for label, _ in rows]
        assert any("Viaje a Madrid" in label for label in labels)

    def test_excludes_plus_horas_extra_bonos_and_anticipo(self) -> None:
        supplements = [
            make_supplement(supplement_type="plus", description="Plus de idiomas"),
            make_supplement(id=2, supplement_type="horas_extra", description="5h extra"),
            make_supplement(id=3, supplement_type="bonos", description="Bono Q1"),
            make_supplement(id=4, supplement_type="anticipo", description="Anticipo marzo"),
        ]
        assert _devengos_no_salariales_rows(supplements) == []


class TestDeduccionesRows:
    def test_includes_ss_and_irpf(self) -> None:
        record = make_record()
        rows = _deducciones_rows(record, ())
        labels = [label for label, _ in rows]
        assert any("Seguridad Social" in label for label in labels)
        assert any("IRPF" in label for label in labels)

    def test_includes_anticipo_supplements(self) -> None:
        record = make_record()
        supplements = [make_supplement(supplement_type="anticipo", description="Anticipo marzo")]
        rows = _deducciones_rows(record, supplements)
        labels = [label for label, _ in rows]
        assert any("Anticipo marzo" in label for label in labels)

    def test_excludes_plus_and_horas_extra_supplements(self) -> None:
        record = make_record()
        supplements = [make_supplement(supplement_type="plus", description="Plus de idiomas")]
        rows = _deducciones_rows(record, supplements)
        labels = [label for label, _ in rows]
        assert not any("Plus de idiomas" in label for label in labels)


class TestBuildPayrollPdfWellFormedness:
    def _company(self, **overrides: object) -> CompanyInfo:
        defaults: dict[str, object] = dict(
            name="Empresa de Prueba S.L.", nif="B23456718", ccc="28/1234567/89",
            address="Calle Mayor 1, 28001 Madrid",
        )
        defaults.update(overrides)
        return CompanyInfo(**defaults)  # type: ignore[arg-type]

    def test_produces_a_valid_pdf(self) -> None:
        pdf_bytes = build_payroll_pdf(
            employee=make_employee(),
            department_name="Tecnología",
            professional_category_name=None,
            company=self._company(),
            record=make_record(),
        )
        assert pdf_bytes.startswith(b"%PDF-")
        assert b"%%EOF" in pdf_bytes[-1024:]
        assert len(pdf_bytes) > 1000

    def test_does_not_raise_with_all_empty_optional_company_fields(self) -> None:
        pdf_bytes = build_payroll_pdf(
            employee=make_employee(),
            department_name="Tecnología",
            professional_category_name=None,
            company=self._company(name="", nif="", ccc="", address=""),
            record=make_record(),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_a_very_long_company_name(self) -> None:
        pdf_bytes = build_payroll_pdf(
            employee=make_employee(),
            department_name="Tecnología",
            professional_category_name=None,
            company=self._company(name="Distribuciones " * 20),
            record=make_record(),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_non_ascii_names(self) -> None:
        pdf_bytes = build_payroll_pdf(
            employee=make_employee(first_name="María José", last_name="Muñoz Núñez"),
            department_name="Atención al público",
            professional_category_name="Técnico/a de nivel 2 — área jurídica",
            company=self._company(name="Compañía Española de Ñoquis, S.L."),
            record=make_record(),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_missing_dni_and_ss_number(self) -> None:
        pdf_bytes = build_payroll_pdf(
            employee=make_employee(dni_nie=None, ss_number=None),
            department_name="Tecnología",
            professional_category_name=None,
            company=self._company(),
            record=make_record(),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_supplements_and_advances(self) -> None:
        pdf_bytes = build_payroll_pdf(
            employee=make_employee(),
            department_name="Tecnología",
            professional_category_name="Técnico de nivel 2",
            company=self._company(),
            record=make_record(),
            supplements=[
                make_supplement(supplement_type="plus", description="Plus"),
                make_supplement(id=2, supplement_type="horas_extra", description="Horas"),
                make_supplement(id=3, supplement_type="anticipo", description="Anticipo"),
            ],
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_dietas_and_bonos(self) -> None:
        # Camino con las dos secciones de I. DEVENGOS a la vez (percepciones
        # salariales + no salariales) -- el resto de tests de esta clase
        # solo ejercitan el camino donde la segunda queda vacía y se omite.
        pdf_bytes = build_payroll_pdf(
            employee=make_employee(),
            department_name="Tecnología",
            professional_category_name="Técnico de nivel 2",
            company=self._company(),
            record=make_record(),
            supplements=[
                make_supplement(supplement_type="bonos", description="Bono Q1", amount=200.0),
                make_supplement(
                    id=2, supplement_type="dietas", description="Viaje a Madrid", amount=45.0
                ),
            ],
        )
        assert pdf_bytes.startswith(b"%PDF-")

    # Nota: no hay un test de "salida determinista para la misma entrada" --
    # reportlab incrusta un /CreationDate con la hora real del sistema en
    # cada PDF que genera (comprobado empíricamente), así que los bytes
    # crudos nunca son reproducibles entre dos llamadas, aunque los datos de
    # entrada sean idénticos. Esto no afecta a la corrección del contenido
    # (probada arriba, dato a dato), solo a la comparación byte a byte.
