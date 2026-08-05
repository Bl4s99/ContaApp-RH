"""Cálculo puro de alertas de RRHH (contratos próximos a vencer, cumpleaños
próximos, revisiones médicas próximas o vencidas, revisión de anonimización
RGPD pendiente, formación PRL pendiente, certificaciones próximas a caducar
o ya caducadas, salario por debajo del mínimo de categoría profesional) a
partir de la lista de empleados -- sin acceso a UI ni base de datos, misma
filosofía que payroll.py/vacation.py/time_tracking.py.
contract_expiry_alerts/birthday_alerts/medical_checkup_alerts/
prl_training_pending_alerts/training_expiry_alerts/
professional_category_minimum_salary_alerts solo tienen sentido para un
empleado ACTIVO (ya no está en plantilla, si no); retention_review_alerts()
es la excepción deliberada: mira justo a los empleados INACTIVOS que las
demás excluyen. training_expiry_alerts() y
professional_category_minimum_salary_alerts() son también las únicas que
necesitan algo más que `employees`: una certificación con fecha de caducidad
vive en EmployeeTraining (un empleado puede tener varias), y el mínimo
salarial vive en ProfessionalCategory -- ninguna de las dos es un campo del
propio Employee como las demás fechas de este módulo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models import Employee, EmployeeTraining, ProfessionalCategory

DEFAULT_ALERT_WINDOW_DAYS = 30


@dataclass(frozen=True, slots=True)
class Alert:
    employee_id: int
    employee_name: str
    # "contrato" | "cumpleanos" | "revision_medica" | "retencion_rgpd" |
    # "formacion_prl" | "certificacion" | "salario_minimo"
    category: str
    target_date: date
    days_remaining: int  # negativo si ya venció/pasó
    detail: str


def _next_anniversary(month: int, day: int, today: date) -> date:
    # 29 de febrero cae en 1 de marzo en los años no bisiestos -- de otro
    # modo un empleado nacido ese día se quedaría sin alerta la mayoría de
    # los años, ya que date(year, 2, 29) no existe fuera de un bisiesto.
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = date(year, 3, 1)
        if candidate >= today:
            return candidate
    raise AssertionError("unreachable: today.year + 1 always resolves")


def contract_expiry_alerts(
    employees: list[Employee], today: date, within_days: int = DEFAULT_ALERT_WINDOW_DAYS
) -> list[Alert]:
    alerts = []
    for emp in employees:
        if not emp.active or emp.contract_end_date is None:
            continue
        days_remaining = (emp.contract_end_date - today).days
        if days_remaining > within_days:
            continue
        assert emp.id is not None
        if days_remaining < 0:
            detail = f"Contrato venció hace {-days_remaining} día(s)"
        elif days_remaining == 0:
            detail = "Contrato vence hoy"
        else:
            detail = f"Contrato vence en {days_remaining} día(s)"
        alerts.append(
            Alert(
                employee_id=emp.id,
                employee_name=emp.full_name,
                category="contrato",
                target_date=emp.contract_end_date,
                days_remaining=days_remaining,
                detail=detail,
            )
        )
    return sorted(alerts, key=lambda a: a.target_date)


def birthday_alerts(
    employees: list[Employee], today: date, within_days: int = DEFAULT_ALERT_WINDOW_DAYS
) -> list[Alert]:
    alerts = []
    for emp in employees:
        if not emp.active or emp.birth_date is None:
            continue
        next_birthday = _next_anniversary(emp.birth_date.month, emp.birth_date.day, today)
        days_remaining = (next_birthday - today).days
        if days_remaining > within_days:
            continue
        assert emp.id is not None
        turning_age = next_birthday.year - emp.birth_date.year
        detail = (
            f"¡Cumple {turning_age} años hoy!"
            if days_remaining == 0
            else f"Cumple {turning_age} años en {days_remaining} día(s)"
        )
        alerts.append(
            Alert(
                employee_id=emp.id,
                employee_name=emp.full_name,
                category="cumpleanos",
                target_date=next_birthday,
                days_remaining=days_remaining,
                detail=detail,
            )
        )
    return sorted(alerts, key=lambda a: a.target_date)


def medical_checkup_alerts(
    employees: list[Employee], today: date, within_days: int = DEFAULT_ALERT_WINDOW_DAYS
) -> list[Alert]:
    alerts = []
    for emp in employees:
        if not emp.active or emp.next_medical_checkup_date is None:
            continue
        days_remaining = (emp.next_medical_checkup_date - today).days
        if days_remaining > within_days:
            continue
        assert emp.id is not None
        if days_remaining < 0:
            detail = f"Revisión médica vencida hace {-days_remaining} día(s)"
        elif days_remaining == 0:
            detail = "Revisión médica hoy"
        else:
            detail = f"Revisión médica en {days_remaining} día(s)"
        alerts.append(
            Alert(
                employee_id=emp.id,
                employee_name=emp.full_name,
                category="revision_medica",
                target_date=emp.next_medical_checkup_date,
                days_remaining=days_remaining,
                detail=detail,
            )
        )
    return sorted(alerts, key=lambda a: a.target_date)


def prl_training_pending_alerts(
    employees: list[Employee], today: date, within_days: int = DEFAULT_ALERT_WINDOW_DAYS
) -> list[Alert]:
    """La formación PRL (Ley 31/1995, art. 19) debe impartirse en el momento
    de la contratación -- así que a diferencia de las otras tres alertas de
    empleado activo (que avisan de algo que vencerá pronto), aquí no hay
    "fecha límite futura" que vigilar: si `prl_training_date` sigue sin
    rellenar, la obligación ya estaba vencida desde el propio `hire_date`.
    `target_date` se fija en `hire_date` precisamente por eso -- el aviso
    sale como "vencido" desde el primer día, no como "próximo"."""
    alerts = []
    for emp in employees:
        if not emp.active or emp.prl_training_date is not None:
            continue
        assert emp.id is not None
        days_remaining = (emp.hire_date - today).days
        if days_remaining > within_days:
            continue
        if days_remaining < 0:
            detail = f"Formación PRL pendiente desde hace {-days_remaining} día(s)"
        else:
            detail = "Formación PRL pendiente (alta de hoy)"
        alerts.append(
            Alert(
                employee_id=emp.id,
                employee_name=emp.full_name,
                category="formacion_prl",
                target_date=emp.hire_date,
                days_remaining=days_remaining,
                detail=detail,
            )
        )
    return sorted(alerts, key=lambda a: a.target_date)


def training_expiry_alerts(
    employees: list[Employee],
    trainings: list[EmployeeTraining],
    today: date,
    within_days: int = DEFAULT_ALERT_WINDOW_DAYS,
) -> list[Alert]:
    """A diferencia de las demás alertas de empleado activo, no recorre
    `employees` buscando un campo de fecha propio: una certificación con
    fecha de caducidad vive en una entidad aparte (un empleado puede tener
    varias), así que recorre `trainings` y solo emite una alerta si su
    empleado sigue estando en `employees` y activo -- si `employees` ya
    viene acotado por departamento/rol desde el llamante, una certificación
    fuera de ese conjunto sencillamente no genera alerta, sin necesitar su
    propio filtro por departamento aquí."""
    active_employees_by_id = {emp.id: emp for emp in employees if emp.active}
    alerts = []
    for training in trainings:
        if training.expiration_date is None:
            continue
        emp = active_employees_by_id.get(training.employee_id)
        if emp is None:
            continue
        assert emp.id is not None
        days_remaining = (training.expiration_date - today).days
        if days_remaining > within_days:
            continue
        if days_remaining < 0:
            detail = f"'{training.name}' caducó hace {-days_remaining} día(s)"
        elif days_remaining == 0:
            detail = f"'{training.name}' caduca hoy"
        else:
            detail = f"'{training.name}' caduca en {days_remaining} día(s)"
        alerts.append(
            Alert(
                employee_id=emp.id,
                employee_name=emp.full_name,
                category="certificacion",
                target_date=training.expiration_date,
                days_remaining=days_remaining,
                detail=detail,
            )
        )
    return sorted(alerts, key=lambda a: a.target_date)


def _format_currency(value: float) -> str:
    # Formato español (punto de millar, coma decimal), igual que
    # employee_page._format_currency -- se duplica en vez de importarse
    # porque esa es privada al módulo y esta app no tiene todavía un sitio
    # común de utilidades de formato compartido entre páginas. Además,
    # este módulo es deliberadamente puro (sin imports de la capa de UI).
    us_formatted = f"{value:,.2f}"
    integer_part, decimal_part = us_formatted.split(".")
    integer_part = integer_part.replace(",", ".")
    return f"{integer_part},{decimal_part} €"


def professional_category_minimum_salary_alerts(
    employees: list[Employee], categories: list[ProfessionalCategory], today: date
) -> list[Alert]:
    """Empleados activos con categoría profesional asignada cuyo salario
    actual queda por debajo del mínimo de esa categoría
    (ProfessionalCategory.minimum_salary) -- el catálogo y la asignación ya
    existían, pero hasta ahora nada comparaba ambos datos ni avisaba.

    A diferencia de las demás alertas de este módulo, no hay una fecha real
    de cuándo empezó a estar por debajo del mínimo: el salario o la propia
    categoría pudieron cambiar en cualquier momento, y esta app no cruza esa
    combinación exacta con el historial de puesto/salario. Se usa
    `hire_date` como aproximación simple para poder ordenarla junto a las
    demás alertas y para que aparezca resaltada en rojo (siempre en el
    pasado salvo alta el mismo día) -- mismo criterio ya usado por
    `prl_training_pending_alerts()`, no una afirmación de que lleva
    exactamente ese tiempo por debajo. El importe de diferencia en el
    detalle sí es exacto, calculado sobre los datos actuales."""
    categories_by_id = {category.id: category for category in categories}
    alerts = []
    for emp in employees:
        if not emp.active or emp.professional_category_id is None:
            continue
        category = categories_by_id.get(emp.professional_category_id)
        if category is None or emp.salary >= category.minimum_salary:
            continue
        assert emp.id is not None
        days_remaining = (emp.hire_date - today).days
        shortfall = category.minimum_salary - emp.salary
        detail = (
            f"Salario {_format_currency(shortfall)} por debajo del mínimo de "
            f"'{category.name}' ({_format_currency(category.minimum_salary)}/año)"
        )
        alerts.append(
            Alert(
                employee_id=emp.id,
                employee_name=emp.full_name,
                category="salario_minimo",
                target_date=emp.hire_date,
                days_remaining=days_remaining,
                detail=detail,
            )
        )
    return sorted(alerts, key=lambda a: a.target_date)


def _add_years(start: date, years: int) -> date:
    try:
        return start.replace(year=start.year + years)
    except ValueError:
        # 29 de febrero cayendo en un año no bisiesto -- mismo criterio que
        # _next_anniversary().
        return start.replace(month=3, day=1, year=start.year + years)


def retention_review_alerts(
    employees: list[Employee],
    today: date,
    retention_years: int,
    within_days: int = DEFAULT_ALERT_WINDOW_DAYS,
) -> list[Alert]:
    """Empleados dados de baja cuyo periodo de conservación obligatoria de
    datos (fiscal/laboral, ver AppSettingsRepository.get_data_retention_years)
    ya venció o está a punto de vencer: candidatos a revisar para anonimizar
    (EmployeeRepository.anonymize()). A diferencia de las otras tres alertas,
    esta mira empleados INACTIVOS -- justo los que ellas excluyen -- y un
    empleado ya anonimizado no vuelve a generar alerta, porque no queda nada
    más que anonimizar."""
    alerts = []
    for emp in employees:
        if emp.active or emp.anonymized or emp.termination_date is None:
            continue
        assert emp.id is not None
        review_date = _add_years(emp.termination_date, retention_years)
        days_remaining = (review_date - today).days
        if days_remaining > within_days:
            continue
        if days_remaining < 0:
            detail = (
                f"Periodo de conservación vencido hace {-days_remaining} día(s): "
                "revisar anonimización"
            )
        elif days_remaining == 0:
            detail = "Periodo de conservación vence hoy: revisar anonimización"
        else:
            detail = f"Periodo de conservación vence en {days_remaining} día(s)"
        alerts.append(
            Alert(
                employee_id=emp.id,
                employee_name=emp.full_name,
                category="retencion_rgpd",
                target_date=review_date,
                days_remaining=days_remaining,
                detail=detail,
            )
        )
    return sorted(alerts, key=lambda a: a.target_date)


def all_alerts(
    employees: list[Employee], today: date, within_days: int = DEFAULT_ALERT_WINDOW_DAYS
) -> list[Alert]:
    combined = (
        contract_expiry_alerts(employees, today, within_days)
        + birthday_alerts(employees, today, within_days)
        + medical_checkup_alerts(employees, today, within_days)
        + prl_training_pending_alerts(employees, today, within_days)
    )
    return sorted(combined, key=lambda a: a.target_date)
