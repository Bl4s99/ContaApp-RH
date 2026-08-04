from __future__ import annotations

import pytest

from app.payroll import (
    MESES_PAGA_EXTRA,
    REDUCCION_RENDIMIENTOS_MAX,
    REDUCCION_RENDIMIENTOS_MIN,
    REDUCCION_RENDIMIENTOS_UMBRAL_ALTO,
    REDUCCION_RENDIMIENTOS_UMBRAL_BAJO,
    calculate_monthly_payroll,
    estimate_irpf_withholding_rate,
    minimo_por_descendientes,
    reduccion_rendimientos_trabajo,
)

# NOTE: these tests verify the implementation is internally consistent and
# faithfully computes the formula described in app/payroll.py's module
# docstring (a bug-detection / regression safety net). They do NOT verify
# the results match the official Agencia Tributaria withholding calculator
# for any specific real employee — see the module docstring for why.


class TestMinimoPorDescendientes:
    def test_zero_children(self) -> None:
        assert minimo_por_descendientes(0) == 0.0

    def test_matches_official_non_cumulative_table(self) -> None:
        # 1er, 2º, 3er hijo tienen importes distintos; 4º en adelante se repite.
        assert minimo_por_descendientes(1) == 2400.0
        assert minimo_por_descendientes(2) == 2400.0 + 2700.0
        assert minimo_por_descendientes(3) == 2400.0 + 2700.0 + 4000.0
        assert minimo_por_descendientes(4) == 2400.0 + 2700.0 + 4000.0 + 4500.0
        assert minimo_por_descendientes(5) == 2400.0 + 2700.0 + 4000.0 + 4500.0 + 4500.0

    def test_monotonically_increasing(self) -> None:
        values = [minimo_por_descendientes(n) for n in range(6)]
        assert values == sorted(values)

    def test_negative_treated_as_zero(self) -> None:
        assert minimo_por_descendientes(-1) == 0.0


class TestReduccionRendimientosTrabajo:
    def test_flat_at_maximum_below_lower_threshold(self) -> None:
        assert reduccion_rendimientos_trabajo(0) == REDUCCION_RENDIMIENTOS_MAX
        assert (
            reduccion_rendimientos_trabajo(REDUCCION_RENDIMIENTOS_UMBRAL_BAJO)
            == REDUCCION_RENDIMIENTOS_MAX
        )

    def test_flat_at_minimum_above_upper_threshold(self) -> None:
        # No a 0.0: la reducción tiene un suelo (Art. 20 LIRPF) -- ver el
        # comentario en reduccion_rendimientos_trabajo(). Antes de este fix,
        # esta función devolvía 0.0 aquí, lo que producía una discontinuidad
        # de ~2364€ en la base imponible justo en este umbral.
        assert (
            reduccion_rendimientos_trabajo(REDUCCION_RENDIMIENTOS_UMBRAL_ALTO)
            == REDUCCION_RENDIMIENTOS_MIN
        )
        assert reduccion_rendimientos_trabajo(100_000) == REDUCCION_RENDIMIENTOS_MIN

    def test_linear_interpolation_at_midpoint(self) -> None:
        midpoint = (REDUCCION_RENDIMIENTOS_UMBRAL_BAJO + REDUCCION_RENDIMIENTOS_UMBRAL_ALTO) / 2
        expected = (REDUCCION_RENDIMIENTOS_MAX + REDUCCION_RENDIMIENTOS_MIN) / 2
        assert reduccion_rendimientos_trabajo(midpoint) == pytest.approx(expected)

    def test_monotonically_non_increasing(self) -> None:
        values = [reduccion_rendimientos_trabajo(x) for x in range(0, 25000, 500)]
        assert values == sorted(values, reverse=True)


class TestEstimateIrpfWithholdingRate:
    def test_zero_or_negative_salary_gives_zero(self) -> None:
        assert estimate_irpf_withholding_rate(0, 6.35, 0) == 0.0
        assert estimate_irpf_withholding_rate(-1000, 6.35, 0) == 0.0

    def test_low_salary_below_minimo_gives_zero(self) -> None:
        assert estimate_irpf_withholding_rate(12000, 6.35, 0) == 0.0

    def test_reference_case_24000_no_children(self) -> None:
        # Hand-derived and cross-checked step by step against the module's own
        # formula (see conversation/dev notes) — catches regressions in the
        # bracket/MPF/reduction arithmetic, not an official AEAT figure.
        assert estimate_irpf_withholding_rate(24000, 6.35, 0) == 15.66

    def test_rate_never_negative_or_above_max(self) -> None:
        for salary in [0, 5000, 12000, 24000, 60000, 300000, 1_000_000]:
            for children in [0, 1, 5, 10]:
                rate = estimate_irpf_withholding_rate(salary, 6.35, children)
                assert 0.0 <= rate <= 47.0

    def test_monotonically_non_decreasing_with_salary(self) -> None:
        salaries = [12000, 18000, 24000, 30000, 40000, 60000, 100000, 250000, 400000]
        rates = [estimate_irpf_withholding_rate(s, 6.35, 0) for s in salaries]
        assert rates == sorted(rates)

    def test_more_dependent_children_never_increases_the_rate(self) -> None:
        salary = 30000
        rates = [estimate_irpf_withholding_rate(salary, 6.35, n) for n in range(6)]
        assert rates == sorted(rates, reverse=True)

    def test_higher_ss_employee_pct_lowers_taxable_base_and_rate(self) -> None:
        # A higher SS-employee percentage shrinks rendimiento neto, so the
        # resulting IRPF rate should not increase.
        low_ss_rate = estimate_irpf_withholding_rate(30000, 6.35, 0)
        high_ss_rate = estimate_irpf_withholding_rate(30000, 12.0, 0)
        assert high_ss_rate <= low_ss_rate


class TestCalculateMonthlyPayroll:
    def test_rejects_invalid_month(self) -> None:
        with pytest.raises(ValueError):
            calculate_monthly_payroll(24000, 0, 6.35, 31.40, month=13, year=2026)
        with pytest.raises(ValueError):
            calculate_monthly_payroll(24000, 0, 6.35, 31.40, month=0, year=2026)

    def test_ordinary_month_has_no_extra_payment(self) -> None:
        result = calculate_monthly_payroll(24000, 0, 6.35, 31.40, month=3, year=2026)
        assert 3 not in MESES_PAGA_EXTRA
        assert result.paga_extra == 0.0
        assert result.bruto_mes == result.paga_ordinaria

    @pytest.mark.parametrize("month", sorted(MESES_PAGA_EXTRA))
    def test_extra_payment_months_double_the_gross(self, month: int) -> None:
        result = calculate_monthly_payroll(24000, 0, 6.35, 31.40, month=month, year=2026)
        assert result.paga_extra == result.paga_ordinaria
        assert result.bruto_mes == pytest.approx(result.paga_ordinaria * 2)

    def test_fourteen_pagas_sum_to_the_annual_salary(self) -> None:
        annual = 28000.0
        total = 0.0
        for month in range(1, 13):
            result = calculate_monthly_payroll(annual, 0, 6.35, 31.40, month=month, year=2026)
            total += result.bruto_mes
        assert total == pytest.approx(annual, abs=0.05)  # rounding to cents across 14 pagas

    def test_neto_equals_bruto_minus_irpf_minus_ss_employee(self) -> None:
        result = calculate_monthly_payroll(30000, 1, 6.35, 31.40, month=5, year=2026)
        assert result.neto == pytest.approx(
            result.bruto_mes - result.irpf_importe - result.ss_employee_importe
        )

    def test_coste_total_equals_bruto_plus_ss_employer(self) -> None:
        result = calculate_monthly_payroll(30000, 1, 6.35, 31.40, month=5, year=2026)
        assert result.coste_total_empresa == pytest.approx(
            result.bruto_mes + result.ss_employer_importe
        )

    def test_zero_salary_gives_all_zeroes_not_a_crash(self) -> None:
        result = calculate_monthly_payroll(0, 0, 6.35, 31.40, month=1, year=2026)
        assert result.bruto_mes == 0.0
        assert result.irpf_importe == 0.0
        assert result.neto == 0.0

    def test_custom_ss_percentages_are_reflected_in_the_breakdown(self) -> None:
        result = calculate_monthly_payroll(24000, 0, 10.0, 25.0, month=1, year=2026)
        assert result.ss_employee_pct == 10.0
        assert result.ss_employer_pct == 25.0
        # abs=0.01: these amounts are deliberately rounded to the cent.
        assert result.ss_employee_importe == pytest.approx(result.bruto_mes * 0.10, abs=0.01)
        assert result.ss_employer_importe == pytest.approx(result.bruto_mes * 0.25, abs=0.01)

    def test_result_carries_the_requested_month_and_year(self) -> None:
        result = calculate_monthly_payroll(24000, 0, 6.35, 31.40, month=9, year=2027)
        assert result.month == 9
        assert result.year == 2027

    def test_net_pay_never_drops_sharply_as_gross_salary_increases(self) -> None:
        # Regresión: reduccion_rendimientos_trabajo() saltaba a 0.0 justo al
        # cruzar REDUCCION_RENDIMIENTOS_UMBRAL_ALTO en vez de mantener el
        # suelo REDUCCION_RENDIMIENTOS_MIN, produciendo una discontinuidad
        # de ~2364€ en la base imponible -- 1€ más de salario anual podía
        # bajar el neto mensual más de 17€/mes. Ni test_monotonically_non_
        # increasing (sobre la propia reducción, que seguía siendo "no
        # creciente" aunque cayera en picado) ni
        # test_monotonically_non_decreasing_with_salary (sobre el tipo,
        # muestreado en saltos de miles que no caían justo en la zona
        # conflictiva) detectaban esto -- este test comprueba directamente
        # la magnitud que de verdad le importa a un empleado: el neto
        # mensual, muestreado euro a euro alrededor del umbral exacto.
        # Tolerancia de 0.50€ (no 0): redondear el tipo de IRPF a 2
        # decimales porcentuales ANTES de multiplicar por el bruto (igual
        # que una nómina real, que también imprime el tipo redondeado)
        # introduce oscilaciones de céntimos inevitables e inofensivas
        # (confirmado por barrido: máxima oscilación observada en el rango
        # 10.000-60.000€, 0.39€) -- lo que este test debe atrapar es un
        # salto real de varios euros como el de este bug, no ese ruido.
        salaries = range(19000, 22000)
        results = [
            calculate_monthly_payroll(salary, 0, 6.35, 31.40, month=3, year=2026)
            for salary in salaries
        ]
        for previous, current in zip(results, results[1:]):
            assert current.neto >= previous.neto - 0.50, (
                f"{previous.bruto_mes}->{current.bruto_mes}: "
                f"neto bajó de {previous.neto} a {current.neto}"
            )


class TestCalculateMonthlyPayrollWithSupplements:
    def test_defaults_to_zero_and_matches_the_no_supplements_case(self) -> None:
        with_defaults = calculate_monthly_payroll(24000, 0, 6.35, 31.40, month=3, year=2026)
        explicit_zero = calculate_monthly_payroll(
            24000, 0, 6.35, 31.40, month=3, year=2026, supplements_total=0.0, advances_total=0.0
        )
        assert with_defaults == explicit_zero
        assert with_defaults.supplements_total == 0.0
        assert with_defaults.advances_total == 0.0

    def test_supplements_increase_the_gross(self) -> None:
        base = calculate_monthly_payroll(24000, 0, 6.35, 31.40, month=3, year=2026)
        with_plus = calculate_monthly_payroll(
            24000, 0, 6.35, 31.40, month=3, year=2026, supplements_total=200.0
        )
        assert with_plus.bruto_mes == pytest.approx(base.bruto_mes + 200.0)
        assert with_plus.supplements_total == 200.0

    def test_supplements_increase_irpf_and_ss_employee_amounts(self) -> None:
        # The RATE stays anchored to the annual base salary (documented
        # simplification), but the AMOUNT withheld scales with the actual,
        # supplement-augmented gross for the month.
        base = calculate_monthly_payroll(24000, 0, 6.35, 31.40, month=3, year=2026)
        with_plus = calculate_monthly_payroll(
            24000, 0, 6.35, 31.40, month=3, year=2026, supplements_total=200.0
        )
        assert with_plus.irpf_pct == base.irpf_pct
        assert with_plus.irpf_importe > base.irpf_importe
        assert with_plus.ss_employee_importe > base.ss_employee_importe

    def test_advances_reduce_neto_but_not_gross(self) -> None:
        base = calculate_monthly_payroll(24000, 0, 6.35, 31.40, month=3, year=2026)
        with_advance = calculate_monthly_payroll(
            24000, 0, 6.35, 31.40, month=3, year=2026, advances_total=500.0
        )
        assert with_advance.bruto_mes == base.bruto_mes
        assert with_advance.irpf_importe == base.irpf_importe
        assert with_advance.neto == pytest.approx(base.neto - 500.0)
        assert with_advance.advances_total == 500.0

    def test_advances_do_not_affect_employer_cost(self) -> None:
        base = calculate_monthly_payroll(24000, 0, 6.35, 31.40, month=3, year=2026)
        with_advance = calculate_monthly_payroll(
            24000, 0, 6.35, 31.40, month=3, year=2026, advances_total=500.0
        )
        assert with_advance.ss_employer_importe == base.ss_employer_importe
        assert with_advance.coste_total_empresa == base.coste_total_empresa

    def test_supplements_do_increase_employer_cost(self) -> None:
        base = calculate_monthly_payroll(24000, 0, 6.35, 31.40, month=3, year=2026)
        with_plus = calculate_monthly_payroll(
            24000, 0, 6.35, 31.40, month=3, year=2026, supplements_total=200.0
        )
        assert with_plus.coste_total_empresa > base.coste_total_empresa

    def test_neto_formula_holds_with_both_supplements_and_advances(self) -> None:
        result = calculate_monthly_payroll(
            30000, 1, 6.35, 31.40, month=5, year=2026,
            supplements_total=150.0, advances_total=300.0,
        )
        assert result.neto == pytest.approx(
            result.bruto_mes - result.irpf_importe - result.ss_employee_importe - 300.0
        )

    def test_negative_supplements_total_rejected(self) -> None:
        with pytest.raises(ValueError):
            calculate_monthly_payroll(
                24000, 0, 6.35, 31.40, month=3, year=2026, supplements_total=-1.0
            )

    def test_negative_advances_total_rejected(self) -> None:
        with pytest.raises(ValueError):
            calculate_monthly_payroll(
                24000, 0, 6.35, 31.40, month=3, year=2026, advances_total=-1.0
            )
