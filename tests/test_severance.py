from __future__ import annotations

from datetime import date

import pytest

from app.severance import calculate_severance


def test_vacation_component_isolated() -> None:
    # Baja justo el 1 de julio (inicio del semestre de invierno): 0 meses
    # devengados de la paga de ese semestre, así que solo se ve el
    # componente de vacaciones. Salario múltiplo de 365 para una tasa
    # diaria exacta (100.0) y verificar el importe a mano sin decimales.
    result = calculate_severance(
        hire_date=date(2020, 1, 1),
        termination_date=date(2026, 7, 1),
        annual_gross_salary=36500.0,
        annual_vacation_days=24.0,
        vacation_days_used_this_year=0,
    )
    assert result.extra_payment_months_accrued == 0
    assert result.extra_payment_amount == 0.0
    assert result.vacation_days_pending == 12.0  # 6 meses completos (ene-jun) x 24/12
    assert result.vacation_amount == 1200.0  # 12 días x (36500/365 = 100 €/día)
    assert result.total_amount == 1200.0


def test_vacation_days_pending_never_negative() -> None:
    # Mismo escenario que arriba pero ya ha disfrutado más días de los que
    # llevaba devengados -- no debe generar un importe negativo.
    result = calculate_severance(
        hire_date=date(2020, 1, 1),
        termination_date=date(2026, 7, 1),
        annual_gross_salary=36500.0,
        annual_vacation_days=24.0,
        vacation_days_used_this_year=20,
    )
    assert result.vacation_days_pending == 0.0
    assert result.vacation_amount == 0.0
    assert result.total_amount == 0.0


def test_extra_payment_component_isolated_full_semester() -> None:
    # Sin vacaciones (annual_vacation_days=0) para aislar el componente de
    # paga extra. Baja el último día de un semestre completo (30 de junio):
    # los 6 meses del semestre cuentan como devengados al completo.
    result = calculate_severance(
        hire_date=date(2020, 1, 1),
        termination_date=date(2026, 6, 30),
        annual_gross_salary=14000.0,  # 14000 / 14 pagas = 1000 € por paga
        annual_vacation_days=0.0,
        vacation_days_used_this_year=0,
    )
    assert result.vacation_amount == 0.0
    assert result.extra_payment_months_accrued == 6
    assert result.extra_payment_amount == 1000.0  # semestre completo -> paga extra íntegra
    assert result.total_amount == 1000.0


def test_extra_payment_prorated_mid_semester() -> None:
    # Baja a mitad de marzo: enero y febrero cuentan como meses completos,
    # marzo no (15 no es el último día del mes) -> 2 de 6 meses.
    result = calculate_severance(
        hire_date=date(2020, 1, 1),
        termination_date=date(2026, 3, 15),
        annual_gross_salary=14000.0,
        annual_vacation_days=0.0,
        vacation_days_used_this_year=0,
    )
    assert result.extra_payment_months_accrued == 2
    assert result.extra_payment_amount == pytest.approx(333.33, abs=0.01)


def test_extra_payment_uses_hire_date_when_hired_mid_semester() -> None:
    # Contratado el 1 de febrero (dentro ya del semestre de verano): el
    # semestre no empieza a contar desde enero, sino desde la fecha de
    # ingreso -- 5 meses completos (feb-jun), no 6.
    result = calculate_severance(
        hire_date=date(2026, 2, 1),
        termination_date=date(2026, 6, 30),
        annual_gross_salary=14000.0,
        annual_vacation_days=0.0,
        vacation_days_used_this_year=0,
    )
    assert result.extra_payment_months_accrued == 5
    assert result.extra_payment_amount == pytest.approx(833.33, abs=0.01)


def test_second_semester_devengo() -> None:
    # La paga de Navidad se devenga de julio a diciembre -- baja el 31 de
    # agosto: julio y agosto completos, 2 de 6 meses.
    result = calculate_severance(
        hire_date=date(2020, 1, 1),
        termination_date=date(2026, 8, 31),
        annual_gross_salary=14000.0,
        annual_vacation_days=0.0,
        vacation_days_used_this_year=0,
    )
    assert result.extra_payment_months_accrued == 2
    assert result.extra_payment_amount == pytest.approx(333.33, abs=0.01)


def test_termination_before_hire_date_raises() -> None:
    with pytest.raises(ValueError):
        calculate_severance(
            hire_date=date(2026, 6, 1),
            termination_date=date(2026, 1, 1),
            annual_gross_salary=20000.0,
            annual_vacation_days=22.0,
            vacation_days_used_this_year=0,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"annual_gross_salary": -1.0},
        {"annual_vacation_days": -1.0},
        {"vacation_days_used_this_year": -1},
    ],
)
def test_negative_inputs_raise(kwargs: dict[str, float]) -> None:
    base = {
        "hire_date": date(2020, 1, 1),
        "termination_date": date(2026, 6, 1),
        "annual_gross_salary": 20000.0,
        "annual_vacation_days": 22.0,
        "vacation_days_used_this_year": 0,
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        calculate_severance(**base)  # type: ignore[arg-type]


def test_same_day_hire_and_termination_is_allowed() -> None:
    result = calculate_severance(
        hire_date=date(2026, 6, 1),
        termination_date=date(2026, 6, 1),
        annual_gross_salary=20000.0,
        annual_vacation_days=22.0,
        vacation_days_used_this_year=0,
    )
    assert result.vacation_days_pending == 0.0
    assert result.extra_payment_months_accrued == 0
    assert result.total_amount == 0.0
