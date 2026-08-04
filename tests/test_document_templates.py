from __future__ import annotations

from datetime import date

from app.document_templates import build_placeholder_values, render_document_template
from app.models import Employee


def make_employee(**overrides: object) -> Employee:
    defaults: dict[str, object] = dict(
        id=1,
        first_name="Ana",
        last_name="García López",
        email="ana@example.com",
        phone="600111222",
        position="Comercial",
        department_id=1,
        shift_id=None,
        salary=24000.0,
        hire_date=date(2020, 3, 15),
        active=True,
        bank_account="ES9121000418450200051332",
        photo=None,
        dependent_children=0,
        dni_nie="00000000T",
        ss_number=None,
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


class TestBuildPlaceholderValues:
    def test_maps_basic_fields(self) -> None:
        employee = make_employee()
        values = build_placeholder_values(employee, "Ventas")
        assert values["nombre"] == "Ana"
        assert values["apellidos"] == "García López"
        assert values["nombre_completo"] == "Ana García López"
        assert values["puesto"] == "Comercial"
        assert values["departamento"] == "Ventas"
        assert values["dni_nie"] == "00000000T"
        assert values["email"] == "ana@example.com"
        assert values["telefono"] == "600111222"
        assert values["tipo_contrato"] == "Indefinido"

    def test_formats_salary_spanish_style(self) -> None:
        employee = make_employee(salary=24000.0)
        values = build_placeholder_values(employee, "Ventas")
        assert values["salario"] == "24.000,00 €"

    def test_formats_hire_date(self) -> None:
        employee = make_employee(hire_date=date(2020, 3, 15))
        values = build_placeholder_values(employee, "Ventas")
        assert values["fecha_ingreso"] == "15/03/2020"

    def test_fecha_hoy_matches_real_today(self) -> None:
        employee = make_employee()
        values = build_placeholder_values(employee, "Ventas")
        assert values["fecha_hoy"] == date.today().strftime("%d/%m/%Y")

    def test_missing_dni_nie_becomes_empty_string(self) -> None:
        employee = make_employee(dni_nie=None)
        values = build_placeholder_values(employee, "Ventas")
        assert values["dni_nie"] == ""

    def test_active_employee_has_empty_termination_placeholders(self) -> None:
        employee = make_employee(termination_date=None, termination_reason=None)
        values = build_placeholder_values(employee, "Ventas")
        assert values["fecha_baja"] == ""
        assert values["motivo_baja"] == ""

    def test_terminated_employee_has_populated_termination_placeholders(self) -> None:
        employee = make_employee(
            termination_date=date(2026, 6, 30), termination_reason="Baja voluntaria"
        )
        values = build_placeholder_values(employee, "Ventas")
        assert values["fecha_baja"] == "30/06/2026"
        assert values["motivo_baja"] == "Baja voluntaria"


class TestRenderDocumentTemplate:
    def test_substitutes_a_single_placeholder(self) -> None:
        result = render_document_template("Hola {nombre}.", {"nombre": "Ana"})
        assert result == "Hola Ana."

    def test_substitutes_multiple_placeholders(self) -> None:
        result = render_document_template(
            "{nombre} trabaja como {puesto}.", {"nombre": "Ana", "puesto": "Comercial"}
        )
        assert result == "Ana trabaja como Comercial."

    def test_substitutes_the_same_placeholder_repeated(self) -> None:
        result = render_document_template("{nombre}, {nombre}.", {"nombre": "Ana"})
        assert result == "Ana, Ana."

    def test_leaves_unknown_placeholder_untouched(self) -> None:
        result = render_document_template("Salario: {salarioo}.", {"salario": "24.000,00 €"})
        assert result == "Salario: {salarioo}."

    def test_leaves_text_without_placeholders_untouched(self) -> None:
        text = "Este es un texto sin marcadores."
        assert render_document_template(text, {}) == text

    def test_empty_body_returns_empty_string(self) -> None:
        assert render_document_template("", {"nombre": "Ana"}) == ""

    def test_ignores_a_stray_unmatched_brace(self) -> None:
        result = render_document_template("Un { suelto y {nombre}.", {"nombre": "Ana"})
        assert result == "Un { suelto y Ana."
