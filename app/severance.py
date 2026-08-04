"""Cálculo puro del finiquito al causar baja un empleado: parte
proporcional de la paga extra en curso y de las vacaciones no
disfrutadas -- misma filosofía que payroll.py/vacation.py/time_tracking.py
(sin UI ni base de datos).

Deliberadamente NO incluye:
  - El salario del mes en curso hasta el último día trabajado: eso ya lo
    cubre la nómina normal de ese mes (generable por separado en Nóminas).
  - Ninguna indemnización por despido: varía demasiado según el tipo de
    contrato, la causa y lo pactado -- no es un cálculo que este módulo
    pueda hacer de forma genérica y fiable, a diferencia de las dos
    partidas anteriores, que sí tienen una fórmula estándar.

Convención de devengo de pagas extra usada aquí (la habitual, salvo que un
convenio colectivo diga otra cosa): la paga de verano se devenga de enero a
junio y se paga en julio; la de Navidad, de julio a diciembre y se paga en
diciembre. Solo se calcula la parte proporcional del semestre EN CURSO en
la fecha de baja -- cualquier semestre ya terminado se asume pagado por la
nómina normal, sin comprobar el histórico de nóminas generadas.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app import vacation
from app.payroll import PAGAS_TOTALES


@dataclass(frozen=True, slots=True)
class SeveranceCalculation:
    vacation_days_pending: float
    vacation_amount: float
    extra_payment_months_accrued: int
    extra_payment_amount: float
    total_amount: float


def _current_semester_start(as_of: date) -> date:
    if as_of.month <= 6:
        return date(as_of.year, 1, 1)
    return date(as_of.year, 7, 1)


def calculate_severance(
    hire_date: date,
    termination_date: date,
    annual_gross_salary: float,
    annual_vacation_days: float,
    vacation_days_used_this_year: int,
) -> SeveranceCalculation:
    if termination_date < hire_date:
        raise ValueError("la fecha de baja no puede ser anterior a la de ingreso")
    if annual_gross_salary < 0:
        raise ValueError("annual_gross_salary no puede ser negativo")
    if annual_vacation_days < 0:
        raise ValueError("annual_vacation_days no puede ser negativo")
    if vacation_days_used_this_year < 0:
        raise ValueError("vacation_days_used_this_year no puede ser negativo")

    # Vacaciones no disfrutadas: lo devengado hasta la fecha de baja menos lo
    # ya usado este año, nunca negativo (un exceso de días ya disfrutados no
    # genera una deuda del empleado hacia la empresa en este cálculo -- fuera
    # de alcance, ver módulo).
    vacation_entitled = vacation.entitlement_up_to(
        hire_date, termination_date, annual_vacation_days
    )
    vacation_days_pending = max(0.0, round(vacation_entitled - vacation_days_used_this_year, 2))
    daily_rate = annual_gross_salary / 365
    vacation_amount = round(vacation_days_pending * daily_rate, 2)

    # Paga extra: solo la parte proporcional del semestre en curso.
    semester_start = _current_semester_start(termination_date)
    effective_start = max(hire_date, semester_start)
    extra_payment_months_accrued = vacation.complete_months_between(
        effective_start, termination_date
    )
    paga_extra_completa = round(annual_gross_salary / PAGAS_TOTALES, 2)
    extra_payment_amount = round(paga_extra_completa * extra_payment_months_accrued / 6, 2)

    total_amount = round(vacation_amount + extra_payment_amount, 2)
    return SeveranceCalculation(
        vacation_days_pending=vacation_days_pending,
        vacation_amount=vacation_amount,
        extra_payment_months_accrued=extra_payment_months_accrued,
        extra_payment_amount=extra_payment_amount,
        total_amount=total_amount,
    )
