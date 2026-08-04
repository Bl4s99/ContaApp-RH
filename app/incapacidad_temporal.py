"""Cálculo puro de quién paga qué parte del salario durante una incapacidad
temporal (IT), según su contingencia -- misma filosofía que
payroll.py/vacation.py/severance.py (sin UI ni base de datos).

AVISO — LEER ANTES DE USAR: es una ESTIMACIÓN orientativa, no un cálculo
oficial de prestación por IT. Simplificaciones deliberadas:
  - La "base reguladora diaria" se aproxima como el salario mensual ordinario
    (annual_gross_salary / PAGAS_TOTALES) entre 30 días -- la base reguladora
    real se calcula a partir de las bases de cotización del mes anterior, que
    pueden diferir del salario bruto por topes/mínimos de cotización. No se
    modela esa diferencia.
  - Días 1-3 de contingencia común como "sin prestación" es la regla general;
    muchos convenios colectivos mejoran voluntariamente ese tramo (lo paga la
    empresa igualmente) — este módulo no conoce el convenio aplicable, así
    que no lo asume.
  - No distingue "pago delegado" (la empresa adelanta y la Seguridad Social
    reembolsa) de pago directo por la Seguridad Social -- estructuralmente
    importa quién financia cada tramo, no quién mueve el dinero primero.
Verifica siempre con una gestoría o asesor laboral antes de usar estas
cifras para decisiones reales de nómina.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.payroll import PAGAS_TOTALES

IT_DAYS_IN_MONTH = 30  # convención estándar de la Seguridad Social para bases diarias


@dataclass(frozen=True, slots=True)
class ITDayTier:
    from_day: int  # 1-indexado, el propio leave_date es el día 1
    to_day: int | None  # inclusive; None = sin límite superior
    payer: str
    percentage: float  # sobre la base reguladora diaria, 0-100


# Contingencia común y accidente no laboral comparten el mismo calendario de
# pago (a diferencia de accidente de trabajo) -- son dos motivos de registro
# distintos, pero la misma tabla de "quién paga qué".
_COMMON_TIERS: tuple[ITDayTier, ...] = (
    ITDayTier(1, 3, "Sin prestación", 0.0),
    ITDayTier(4, 20, "Empresa (pago delegado)", 60.0),
    ITDayTier(21, None, "Empresa (pago delegado)", 75.0),
)

_WORK_ACCIDENT_TIERS: tuple[ITDayTier, ...] = (
    ITDayTier(1, 1, "Empresa", 100.0),
    ITDayTier(2, None, "Seguridad Social (pago delegado)", 75.0),
)


def tiers_for_contingency(contingency: str) -> tuple[ITDayTier, ...]:
    if contingency == "Accidente de trabajo":
        return _WORK_ACCIDENT_TIERS
    return _COMMON_TIERS


@dataclass(frozen=True, slots=True)
class ITBreakdownRow:
    payer: str
    percentage: float
    days: int
    amount: float


@dataclass(frozen=True, slots=True)
class ITPaymentBreakdown:
    total_days: int
    daily_rate: float
    rows: tuple[ITBreakdownRow, ...]
    total_amount: float


def calculate_it_payment_breakdown(
    contingency: str,
    leave_date: date,
    as_of: date,
    annual_gross_salary: float,
) -> ITPaymentBreakdown:
    if as_of < leave_date:
        raise ValueError("as_of no puede ser anterior a leave_date")
    if annual_gross_salary < 0:
        raise ValueError("annual_gross_salary no puede ser negativo")

    total_days = (as_of - leave_date).days + 1
    monthly_salary = annual_gross_salary / PAGAS_TOTALES
    daily_rate = monthly_salary / IT_DAYS_IN_MONTH

    rows = []
    total_amount = 0.0
    for tier in tiers_for_contingency(contingency):
        lo = tier.from_day
        hi = tier.to_day if tier.to_day is not None else total_days
        hi = min(hi, total_days)
        days_in_tier = max(0, hi - lo + 1)
        if days_in_tier == 0:
            continue
        amount = round(daily_rate * (tier.percentage / 100.0) * days_in_tier, 2)
        rows.append(
            ITBreakdownRow(
                payer=tier.payer, percentage=tier.percentage, days=days_in_tier, amount=amount
            )
        )
        total_amount += amount

    return ITPaymentBreakdown(
        total_days=total_days,
        daily_rate=round(daily_rate, 2),
        rows=tuple(rows),
        total_amount=round(total_amount, 2),
    )
