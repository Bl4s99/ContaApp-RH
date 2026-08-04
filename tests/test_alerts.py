from __future__ import annotations

from datetime import date, timedelta

from app.alerts import (
    all_alerts,
    birthday_alerts,
    contract_expiry_alerts,
    medical_checkup_alerts,
    prl_training_pending_alerts,
    retention_review_alerts,
    training_expiry_alerts,
)
from app.models import Employee, EmployeeTraining

TODAY = date(2026, 7, 23)


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
        salary=35000.0,
        hire_date=date(2020, 5, 1),
        active=True,
        bank_account="",
        photo=None,
        dependent_children=0,
        dni_nie=None,
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


def make_training(**overrides: object) -> EmployeeTraining:
    defaults: dict[str, object] = dict(
        id=1,
        employee_id=1,
        name="Carné de carretillero",
        completion_date=date(2024, 1, 1),
        expiration_date=None,
        created_at=None,
    )
    defaults.update(overrides)
    return EmployeeTraining(**defaults)  # type: ignore[arg-type]


class TestContractExpiryAlerts:
    def test_contract_expiring_within_window_generates_an_alert(self) -> None:
        emp = make_employee(contract_type="Temporal", contract_end_date=TODAY + timedelta(days=10))
        [alert] = contract_expiry_alerts([emp], TODAY, within_days=30)
        assert alert.category == "contrato"
        assert alert.days_remaining == 10
        assert alert.employee_id == 1

    def test_contract_expiring_outside_window_is_ignored(self) -> None:
        emp = make_employee(contract_type="Temporal", contract_end_date=TODAY + timedelta(days=45))
        assert contract_expiry_alerts([emp], TODAY, within_days=30) == []

    def test_already_expired_contract_generates_an_urgent_alert(self) -> None:
        emp = make_employee(contract_type="Temporal", contract_end_date=TODAY - timedelta(days=5))
        [alert] = contract_expiry_alerts([emp], TODAY, within_days=30)
        assert alert.days_remaining == -5
        assert "venció" in alert.detail

    def test_contract_expiring_today(self) -> None:
        emp = make_employee(contract_type="Temporal", contract_end_date=TODAY)
        [alert] = contract_expiry_alerts([emp], TODAY, within_days=30)
        assert alert.days_remaining == 0

    def test_indefinido_contract_has_no_end_date_and_no_alert(self) -> None:
        emp = make_employee(contract_type="Indefinido", contract_end_date=None)
        assert contract_expiry_alerts([emp], TODAY, within_days=30) == []

    def test_inactive_employee_generates_no_alert_even_if_expiring(self) -> None:
        emp = make_employee(
            active=False, contract_type="Temporal", contract_end_date=TODAY + timedelta(days=5)
        )
        assert contract_expiry_alerts([emp], TODAY, within_days=30) == []

    def test_multiple_alerts_sorted_by_target_date(self) -> None:
        soon = make_employee(
            id=1, email="a@x.com", contract_type="Temporal", contract_end_date=TODAY + timedelta(days=20)
        )
        sooner = make_employee(
            id=2, email="b@x.com", contract_type="Temporal", contract_end_date=TODAY + timedelta(days=2)
        )
        alerts = contract_expiry_alerts([soon, sooner], TODAY, within_days=30)
        assert [a.employee_id for a in alerts] == [2, 1]


class TestBirthdayAlerts:
    def test_birthday_within_window_generates_an_alert(self) -> None:
        emp = make_employee(birth_date=date(1990, 8, 2))  # 10 days after TODAY (2026-07-23)
        [alert] = birthday_alerts([emp], TODAY, within_days=30)
        assert alert.category == "cumpleanos"
        assert alert.days_remaining == 10
        assert alert.target_date == date(2026, 8, 2)

    def test_birthday_outside_window_is_ignored(self) -> None:
        emp = make_employee(birth_date=date(1990, 12, 25))
        assert birthday_alerts([emp], TODAY, within_days=30) == []

    def test_birthday_already_passed_this_year_rolls_to_next_year(self) -> None:
        emp = make_employee(birth_date=date(1990, 1, 15))  # already passed on 2026-07-23
        [alert] = birthday_alerts([emp], TODAY, within_days=200)
        assert alert.target_date == date(2027, 1, 15)
        assert alert.days_remaining == 176

    def test_birthday_wraps_the_year_boundary_correctly(self) -> None:
        near_year_end = date(2026, 12, 20)
        emp = make_employee(birth_date=date(1990, 1, 5))
        [alert] = birthday_alerts([emp], near_year_end, within_days=30)
        assert alert.target_date == date(2027, 1, 5)
        assert alert.days_remaining == 16

    def test_birthday_today(self) -> None:
        emp = make_employee(birth_date=date(1990, 7, 23))
        [alert] = birthday_alerts([emp], TODAY, within_days=30)
        assert alert.days_remaining == 0
        assert "hoy" in alert.detail

    def test_turning_age_is_computed_correctly(self) -> None:
        emp = make_employee(birth_date=date(1990, 8, 2))
        [alert] = birthday_alerts([emp], TODAY, within_days=30)
        assert "36" in alert.detail

    def test_february_29_birthday_observed_march_1_in_a_non_leap_year(self) -> None:
        # 2026-07-23 -> next Feb 29 falls in 2028 (leap); force a non-leap
        # target by asking from just before it in a non-leap year (2027).
        emp = make_employee(birth_date=date(1992, 2, 29))
        near = date(2027, 2, 20)
        [alert] = birthday_alerts([emp], near, within_days=30)
        assert alert.target_date == date(2027, 3, 1)

    def test_no_birth_date_means_no_alert(self) -> None:
        emp = make_employee(birth_date=None)
        assert birthday_alerts([emp], TODAY, within_days=30) == []

    def test_inactive_employee_generates_no_birthday_alert(self) -> None:
        emp = make_employee(active=False, birth_date=date(1990, 8, 2))
        assert birthday_alerts([emp], TODAY, within_days=30) == []


class TestMedicalCheckupAlerts:
    def test_upcoming_checkup_within_window_generates_an_alert(self) -> None:
        emp = make_employee(next_medical_checkup_date=TODAY + timedelta(days=5))
        [alert] = medical_checkup_alerts([emp], TODAY, within_days=30)
        assert alert.category == "revision_medica"
        assert alert.days_remaining == 5

    def test_checkup_outside_window_is_ignored(self) -> None:
        emp = make_employee(next_medical_checkup_date=TODAY + timedelta(days=60))
        assert medical_checkup_alerts([emp], TODAY, within_days=30) == []

    def test_overdue_checkup_generates_an_urgent_alert(self) -> None:
        emp = make_employee(next_medical_checkup_date=TODAY - timedelta(days=10))
        [alert] = medical_checkup_alerts([emp], TODAY, within_days=30)
        assert alert.days_remaining == -10
        assert "vencida" in alert.detail

    def test_no_checkup_date_means_no_alert(self) -> None:
        emp = make_employee(next_medical_checkup_date=None)
        assert medical_checkup_alerts([emp], TODAY, within_days=30) == []

    def test_inactive_employee_generates_no_checkup_alert(self) -> None:
        emp = make_employee(active=False, next_medical_checkup_date=TODAY + timedelta(days=5))
        assert medical_checkup_alerts([emp], TODAY, within_days=30) == []


class TestPrlTrainingPendingAlerts:
    def test_missing_training_generates_an_alert(self) -> None:
        emp = make_employee(prl_training_date=None)
        [alert] = prl_training_pending_alerts([emp], TODAY, within_days=30)
        assert alert.category == "formacion_prl"
        assert alert.target_date == emp.hire_date
        assert alert.days_remaining < 0
        assert "pendiente" in alert.detail

    def test_training_already_done_generates_no_alert(self) -> None:
        emp = make_employee(prl_training_date=date(2020, 6, 1))
        assert prl_training_pending_alerts([emp], TODAY, within_days=30) == []

    def test_inactive_employee_generates_no_alert(self) -> None:
        emp = make_employee(active=False, prl_training_date=None)
        assert prl_training_pending_alerts([emp], TODAY, within_days=30) == []

    def test_hired_today_still_generates_an_alert(self) -> None:
        emp = make_employee(hire_date=TODAY, prl_training_date=None)
        [alert] = prl_training_pending_alerts([emp], TODAY, within_days=30)
        assert alert.days_remaining == 0
        assert "alta de hoy" in alert.detail

    def test_multiple_alerts_sorted_by_hire_date(self) -> None:
        newer = make_employee(
            id=1, email="a@x.com", hire_date=date(2021, 1, 1), prl_training_date=None
        )
        older = make_employee(
            id=2, email="b@x.com", hire_date=date(2019, 1, 1), prl_training_date=None
        )
        alerts = prl_training_pending_alerts([newer, older], TODAY, within_days=30)
        assert [a.employee_id for a in alerts] == [2, 1]


class TestRetentionReviewAlerts:
    def test_overdue_retention_period_generates_an_urgent_alert(self) -> None:
        emp = make_employee(
            active=False, termination_date=TODAY - timedelta(days=4 * 365 + 10)
        )
        [alert] = retention_review_alerts([emp], TODAY, retention_years=4, within_days=30)
        assert alert.category == "retencion_rgpd"
        assert alert.days_remaining < 0
        assert "vencido" in alert.detail

    def test_retention_period_ending_soon_generates_an_alert(self) -> None:
        # TODAY es 2026-07-23; +4 años de 2022-07-30 cae en 2026-07-30, es
        # decir, 7 días después de TODAY (evita restar días "a mano" contra
        # años civiles, que no son múltiplos exactos de 365 por los bisiestos).
        emp = make_employee(active=False, termination_date=date(2022, 7, 30))
        [alert] = retention_review_alerts([emp], TODAY, retention_years=4, within_days=30)
        assert alert.target_date == date(2026, 7, 30)
        assert alert.days_remaining == 7

    def test_retention_period_far_in_the_future_is_ignored(self) -> None:
        emp = make_employee(active=False, termination_date=TODAY - timedelta(days=30))
        assert retention_review_alerts([emp], TODAY, retention_years=4, within_days=30) == []

    def test_active_employee_generates_no_retention_alert(self) -> None:
        emp = make_employee(active=True, termination_date=None)
        assert retention_review_alerts([emp], TODAY, retention_years=4, within_days=30) == []

    def test_already_anonymized_employee_generates_no_alert(self) -> None:
        emp = make_employee(
            active=False,
            termination_date=TODAY - timedelta(days=4 * 365 + 10),
            anonymized=True,
        )
        assert retention_review_alerts([emp], TODAY, retention_years=4, within_days=30) == []

    def test_inactive_employee_without_termination_date_generates_no_alert(self) -> None:
        # No debería ocurrir en la práctica (terminate() siempre fija la
        # fecha), pero defensivo: sin fecha no hay nada que calcular.
        emp = make_employee(active=False, termination_date=None)
        assert retention_review_alerts([emp], TODAY, retention_years=4, within_days=30) == []

    def test_zero_retention_years_means_review_due_at_termination(self) -> None:
        emp = make_employee(active=False, termination_date=TODAY)
        [alert] = retention_review_alerts([emp], TODAY, retention_years=0, within_days=30)
        assert alert.days_remaining == 0

    def test_multiple_alerts_sorted_by_target_date(self) -> None:
        sooner = make_employee(
            id=1, email="a@x.com", active=False, termination_date=TODAY - timedelta(days=4 * 365 - 2)
        )
        later = make_employee(
            id=2, email="b@x.com", active=False, termination_date=TODAY - timedelta(days=4 * 365 - 20)
        )
        alerts = retention_review_alerts([sooner, later], TODAY, retention_years=4, within_days=30)
        assert [a.employee_id for a in alerts] == [1, 2]


class TestAllAlerts:
    def test_combines_and_sorts_every_category(self) -> None:
        emp = make_employee(
            id=1,
            email="a@x.com",
            contract_type="Temporal",
            contract_end_date=TODAY + timedelta(days=20),
            birth_date=date(1990, 7, 25),  # 2 days out
            next_medical_checkup_date=TODAY + timedelta(days=1),
            prl_training_date=date(2020, 5, 1),  # ya formado -> sin alerta de PRL aquí
        )
        alerts = all_alerts([emp], TODAY, within_days=30)
        # medical checkup (+1 day) < birthday (+2 days) < contract (+20 days)
        assert [a.category for a in alerts] == ["revision_medica", "cumpleanos", "contrato"]

    def test_includes_prl_training_pending_category(self) -> None:
        emp = make_employee(id=1, email="a@x.com", prl_training_date=None)
        alerts = all_alerts([emp], TODAY, within_days=30)
        assert [a.category for a in alerts] == ["formacion_prl"]

    def test_empty_employee_list_gives_no_alerts(self) -> None:
        assert all_alerts([], TODAY, within_days=30) == []


class TestTrainingExpiryAlerts:
    def test_expiring_within_window_generates_an_alert(self) -> None:
        emp = make_employee(id=1)
        training = make_training(
            employee_id=1, name="Carné", expiration_date=TODAY + timedelta(days=10)
        )
        [alert] = training_expiry_alerts([emp], [training], TODAY, within_days=30)
        assert alert.category == "certificacion"
        assert alert.days_remaining == 10
        assert "Carné" in alert.detail
        assert "caduca en 10" in alert.detail

    def test_expiring_outside_window_is_ignored(self) -> None:
        emp = make_employee(id=1)
        training = make_training(employee_id=1, expiration_date=TODAY + timedelta(days=60))
        assert training_expiry_alerts([emp], [training], TODAY, within_days=30) == []

    def test_already_expired_generates_an_urgent_alert(self) -> None:
        emp = make_employee(id=1)
        training = make_training(
            employee_id=1, name="B2 Inglés", expiration_date=TODAY - timedelta(days=5)
        )
        [alert] = training_expiry_alerts([emp], [training], TODAY, within_days=30)
        assert alert.days_remaining == -5
        assert "caducó" in alert.detail

    def test_expiring_today(self) -> None:
        emp = make_employee(id=1)
        training = make_training(employee_id=1, expiration_date=TODAY)
        [alert] = training_expiry_alerts([emp], [training], TODAY, within_days=30)
        assert alert.days_remaining == 0
        assert "caduca hoy" in alert.detail

    def test_training_with_no_expiration_never_generates_an_alert(self) -> None:
        emp = make_employee(id=1)
        training = make_training(employee_id=1, expiration_date=None)
        assert training_expiry_alerts([emp], [training], TODAY, within_days=30) == []

    def test_inactive_employee_generates_no_alert_even_if_expiring(self) -> None:
        emp = make_employee(id=1, active=False)
        training = make_training(employee_id=1, expiration_date=TODAY + timedelta(days=5))
        assert training_expiry_alerts([emp], [training], TODAY, within_days=30) == []

    def test_training_for_an_employee_outside_the_given_list_is_ignored(self) -> None:
        # Simula un `employees` ya acotado por departamento/rol: una
        # certificación de alguien fuera de ese conjunto no debe generar
        # alerta, sin que training_expiry_alerts() necesite su propio
        # filtro por departamento.
        emp = make_employee(id=1)
        training = make_training(employee_id=999, expiration_date=TODAY + timedelta(days=5))
        assert training_expiry_alerts([emp], [training], TODAY, within_days=30) == []

    def test_an_employee_with_multiple_expiring_trainings_gets_one_alert_each(self) -> None:
        emp = make_employee(id=1)
        t1 = make_training(id=1, employee_id=1, name="A", expiration_date=TODAY + timedelta(days=5))
        t2 = make_training(id=2, employee_id=1, name="B", expiration_date=TODAY + timedelta(days=15))
        alerts = training_expiry_alerts([emp], [t1, t2], TODAY, within_days=30)
        assert len(alerts) == 2
        assert [a.days_remaining for a in alerts] == [5, 15]

    def test_multiple_alerts_sorted_by_target_date(self) -> None:
        emp = make_employee(id=1)
        sooner = make_training(
            id=1, employee_id=1, name="Sooner", expiration_date=TODAY + timedelta(days=2)
        )
        later = make_training(
            id=2, employee_id=1, name="Later", expiration_date=TODAY + timedelta(days=20)
        )
        alerts = training_expiry_alerts([emp], [later, sooner], TODAY, within_days=30)
        assert [a.detail for a in alerts] == [
            "'Sooner' caduca en 2 día(s)",
            "'Later' caduca en 20 día(s)",
        ]

    def test_empty_trainings_list_gives_no_alerts(self) -> None:
        emp = make_employee(id=1)
        assert training_expiry_alerts([emp], [], TODAY, within_days=30) == []
