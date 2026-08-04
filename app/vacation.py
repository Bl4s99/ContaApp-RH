"""Cálculo puro del saldo de vacaciones: días que corresponden a un
empleado en un año concreto, sin acceso a UI ni base de datos (misma
filosofía que payroll.py y time_tracking.py).

La prorrata para el año de ingreso es una aproximación por meses completos
trabajados (1/12 de los días anuales por mes completo), no el cálculo
exacto por días que usan algunos convenios -- se documenta como tal en vez
de presentarse como un cálculo oficial.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class VacationBalance:
    year: int
    entitled_days: float
    used_days: int

    @property
    def remaining_days(self) -> float:
        return round(self.entitled_days - self.used_days, 2)


def complete_months_between(start: date, end: date) -> int:
    """Meses NATURALES completos entre start y end, ambos extremos incluidos
    solo si son completos: si `start` no cae en día 1, ese primer mes no
    cuenta; si `end` no cae en el último día de su mes, ese último mes
    tampoco cuenta -- mismo criterio conservador en los dos extremos (usado
    ya para el extremo de inicio en entitlement_for_year antes de esta
    generalización). Pública porque severance.py también la necesita, para
    prorratear la paga extra con el mismo criterio que las vacaciones."""
    if start > end:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    if start.day != 1:
        months -= 1
    if end.day != calendar.monthrange(end.year, end.month)[1]:
        months -= 1
    return max(0, months)


def entitlement_up_to(hire_date: date, as_of: date, annual_days: float) -> float:
    """Días de vacaciones devengados en el año de `as_of`, desde el 1 de
    enero (o la fecha de ingreso si es posterior) hasta `as_of` -- a
    diferencia de entitlement_for_year() (que siempre prorratea hasta el 31
    de diciembre, el año completo), esta prorratea solo hasta una fecha
    concreta a mitad de año. Pensada para el finiquito: cuánto se ha
    devengado hasta la fecha de baja, no hasta fin de año."""
    year_start = date(as_of.year, 1, 1)
    effective_start = max(hire_date, year_start)
    if effective_start > as_of:
        return 0.0
    months = complete_months_between(effective_start, as_of)
    return round(annual_days * months / 12, 2)


def entitlement_for_year(hire_date: date, year: int, annual_days: float) -> float:
    return entitlement_up_to(hire_date, date(year, 12, 31), annual_days)


def calculate_balance(
    hire_date: date, year: int, annual_days: float, used_days: int
) -> VacationBalance:
    return VacationBalance(
        year=year,
        entitled_days=entitlement_for_year(hire_date, year, annual_days),
        used_days=used_days,
    )


def calculate_balance_up_to(
    hire_date: date, as_of: date, annual_days: float, used_days: int
) -> VacationBalance:
    """Como calculate_balance(), pero prorrateado solo hasta `as_of` en vez
    de hasta fin de año -- pensado para un empleado ya de baja, cuyo saldo
    "de este año" no debería seguir devengando después de su fecha de baja
    (el mismo criterio que severance.py ya usa para el finiquito, solo que
    aquí es para mostrarlo en la ficha, no para pagarlo)."""
    return VacationBalance(
        year=as_of.year,
        entitled_days=entitlement_up_to(hire_date, as_of, annual_days),
        used_days=used_days,
    )
