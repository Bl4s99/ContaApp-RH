from __future__ import annotations

from datetime import date

import pytest

from app.incapacidad_temporal import calculate_it_payment_breakdown

# Salario anual limpio para que paga_ordinaria (annual/14) y la tarifa diaria
# (paga_ordinaria/30) den números redondos: 21000 / 14 = 1500; 1500 / 30 = 50.
CLEAN_SALARY = 21000.0


class TestCommonContingencyTiers:
    def test_single_day_falls_entirely_in_the_unpaid_tier(self) -> None:
        breakdown = calculate_it_payment_breakdown(
            "Común", date(2026, 1, 1), date(2026, 1, 1), CLEAN_SALARY
        )
        assert breakdown.total_days == 1
        [row] = breakdown.rows
        assert row.payer == "Sin prestación"
        assert row.days == 1
        assert row.amount == 0.0
        assert breakdown.total_amount == 0.0

    def test_exactly_three_days_all_unpaid(self) -> None:
        breakdown = calculate_it_payment_breakdown(
            "Común", date(2026, 1, 1), date(2026, 1, 3), CLEAN_SALARY
        )
        [row] = breakdown.rows
        assert row.days == 3
        assert breakdown.total_amount == 0.0

    def test_fourth_day_enters_the_60_percent_employer_tier(self) -> None:
        breakdown = calculate_it_payment_breakdown(
            "Común", date(2026, 1, 1), date(2026, 1, 4), CLEAN_SALARY
        )
        assert [(r.payer, r.days) for r in breakdown.rows] == [
            ("Sin prestación", 3),
            ("Empresa (pago delegado)", 1),
        ]
        assert breakdown.rows[1].percentage == 60.0
        assert breakdown.rows[1].amount == 30.0  # 50 * 0.60 * 1

    def test_twenty_days_stays_within_the_60_percent_tier(self) -> None:
        breakdown = calculate_it_payment_breakdown(
            "Común", date(2026, 1, 1), date(2026, 1, 20), CLEAN_SALARY
        )
        assert [(r.payer, r.days, r.percentage) for r in breakdown.rows] == [
            ("Sin prestación", 3, 0.0),
            ("Empresa (pago delegado)", 17, 60.0),
        ]

    def test_twenty_one_days_enters_the_75_percent_tier(self) -> None:
        breakdown = calculate_it_payment_breakdown(
            "Común", date(2026, 1, 1), date(2026, 1, 21), CLEAN_SALARY
        )
        assert [(r.payer, r.days, r.percentage) for r in breakdown.rows] == [
            ("Sin prestación", 3, 0.0),
            ("Empresa (pago delegado)", 17, 60.0),
            ("Empresa (pago delegado)", 1, 75.0),
        ]

    def test_full_breakdown_total_matches_reference_calculation(self) -> None:
        # 3 días sin prestación + 17 días al 60% + 5 días al 75%, tarifa diaria 50.
        breakdown = calculate_it_payment_breakdown(
            "Común", date(2026, 1, 1), date(2026, 1, 25), CLEAN_SALARY
        )
        assert breakdown.total_days == 25
        assert breakdown.daily_rate == 50.0
        expected_total = round(17 * 50 * 0.60 + 5 * 50 * 0.75, 2)
        assert breakdown.total_amount == expected_total == 697.5

    def test_no_leave_disability_contingency_uses_the_same_tiers_as_common(self) -> None:
        common = calculate_it_payment_breakdown(
            "Común", date(2026, 1, 1), date(2026, 1, 25), CLEAN_SALARY
        )
        non_work = calculate_it_payment_breakdown(
            "Accidente no laboral", date(2026, 1, 1), date(2026, 1, 25), CLEAN_SALARY
        )
        assert common.rows == non_work.rows
        assert common.total_amount == non_work.total_amount


class TestWorkAccidentContingencyTiers:
    def test_first_day_is_paid_in_full_by_the_employer(self) -> None:
        breakdown = calculate_it_payment_breakdown(
            "Accidente de trabajo", date(2026, 1, 1), date(2026, 1, 1), CLEAN_SALARY
        )
        [row] = breakdown.rows
        assert row.payer == "Empresa"
        assert row.percentage == 100.0
        assert row.amount == 50.0

    def test_second_day_onward_is_75_percent_from_social_security(self) -> None:
        breakdown = calculate_it_payment_breakdown(
            "Accidente de trabajo", date(2026, 1, 1), date(2026, 1, 5), CLEAN_SALARY
        )
        assert [(r.payer, r.days, r.percentage) for r in breakdown.rows] == [
            ("Empresa", 1, 100.0),
            ("Seguridad Social (pago delegado)", 4, 75.0),
        ]
        assert breakdown.total_amount == round(50 + 4 * 50 * 0.75, 2) == 200.0

    def test_no_unpaid_tier_unlike_common_contingency(self) -> None:
        breakdown = calculate_it_payment_breakdown(
            "Accidente de trabajo", date(2026, 1, 1), date(2026, 1, 2), CLEAN_SALARY
        )
        assert all(row.payer != "Sin prestación" for row in breakdown.rows)


class TestCalculateItPaymentBreakdownEdgeCases:
    def test_rejects_as_of_before_leave_date(self) -> None:
        with pytest.raises(ValueError):
            calculate_it_payment_breakdown(
                "Común", date(2026, 1, 10), date(2026, 1, 1), CLEAN_SALARY
            )

    def test_rejects_negative_salary(self) -> None:
        with pytest.raises(ValueError):
            calculate_it_payment_breakdown("Común", date(2026, 1, 1), date(2026, 1, 1), -100.0)

    def test_zero_salary_gives_zero_amounts_but_still_reports_days(self) -> None:
        breakdown = calculate_it_payment_breakdown(
            "Común", date(2026, 1, 1), date(2026, 1, 25), 0.0
        )
        assert breakdown.total_days == 25
        assert breakdown.total_amount == 0.0
        assert sum(r.days for r in breakdown.rows) == 25
