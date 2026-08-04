from __future__ import annotations

from datetime import date

from app.vacation import calculate_balance, calculate_balance_up_to, entitlement_for_year


class TestEntitlementForYear:
    def test_hired_in_a_prior_year_gets_full_entitlement(self) -> None:
        assert entitlement_for_year(date(2020, 6, 15), 2026, 22) == 22.0

    def test_hired_after_the_queried_year_gets_zero(self) -> None:
        assert entitlement_for_year(date(2027, 1, 1), 2026, 22) == 0.0

    def test_hired_on_the_first_of_the_year_gets_full_entitlement(self) -> None:
        assert entitlement_for_year(date(2026, 1, 1), 2026, 22) == 22.0

    def test_hired_mid_year_on_the_first_of_a_month_prorates_from_that_month(self) -> None:
        # Hired 1 July: July..December = 6 complete months -> 6/12 of 22.
        assert entitlement_for_year(date(2026, 7, 1), 2026, 22) == 11.0

    def test_hired_mid_month_does_not_count_the_partial_month(self) -> None:
        # Hired 15 July: the partial July doesn't count, so August..December
        # = 5 complete months -> 5/12 of 22.
        expected = round(22 * 5 / 12, 2)
        assert entitlement_for_year(date(2026, 7, 15), 2026, 22) == expected

    def test_hired_in_december_gets_one_twelfth(self) -> None:
        assert entitlement_for_year(date(2026, 12, 1), 2026, 22) == round(22 / 12, 2)

    def test_hired_after_the_first_of_december_gets_zero_for_that_year(self) -> None:
        assert entitlement_for_year(date(2026, 12, 15), 2026, 22) == 0.0

    def test_scales_with_annual_days_setting(self) -> None:
        assert entitlement_for_year(date(2020, 1, 1), 2026, 30) == 30.0


class TestCalculateBalance:
    def test_remaining_is_entitled_minus_used(self) -> None:
        balance = calculate_balance(date(2020, 1, 1), 2026, 22, 14)
        assert balance.entitled_days == 22.0
        assert balance.used_days == 14
        assert balance.remaining_days == 8.0

    def test_used_more_than_entitled_gives_negative_remaining(self) -> None:
        balance = calculate_balance(date(2026, 7, 1), 2026, 22, 15)
        assert balance.entitled_days == 11.0
        assert balance.remaining_days == -4.0

    def test_year_field_is_passed_through(self) -> None:
        balance = calculate_balance(date(2020, 1, 1), 2026, 22, 0)
        assert balance.year == 2026


class TestCalculateBalanceUpTo:
    # Regresión: la ficha de un empleado de baja mostraba el devengo
    # COMPLETO del año en curso (hasta el 31 de diciembre) en vez de
    # prorratear hasta su fecha de baja, igual que ya hace el finiquito --
    # podía sobrestimar los días "disponibles" de alguien que lleva tiempo
    # sin trabajar allí.
    def test_prorates_up_to_the_given_date_not_the_full_year(self) -> None:
        # Dado de baja el 1 de julio: enero..junio = 6 meses completos.
        balance = calculate_balance_up_to(date(2020, 1, 1), date(2026, 7, 1), 22, 0)
        assert balance.entitled_days == 11.0

    def test_year_field_comes_from_as_of_not_today(self) -> None:
        balance = calculate_balance_up_to(date(2020, 1, 1), date(2024, 7, 1), 22, 0)
        assert balance.year == 2024

    def test_remaining_is_entitled_minus_used(self) -> None:
        balance = calculate_balance_up_to(date(2020, 1, 1), date(2026, 7, 1), 22, 5)
        assert balance.remaining_days == 6.0
