from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.models import TimeClockEntry


@dataclass(frozen=True, slots=True)
class WorkedInterval:
    clock_in: datetime
    clock_out: datetime | None  # None: todavía fichado, sin salida registrada

    @property
    def duration_hours(self) -> float | None:
        if self.clock_out is None:
            return None
        return round((self.clock_out - self.clock_in).total_seconds() / 3600, 2)


def pair_entries(entries: list[TimeClockEntry]) -> list[WorkedInterval]:
    """Empareja fichajes de entrada/salida en orden cronológico para un
    mismo empleado. Asume que `entries` ya alternan correctamente -- lo
    garantiza TimeEntryRepository al insertar/editar, no se revalida aquí.
    Un turno que cruza medianoche se empareja igual (la fecha de cada
    fichaje es irrelevante, solo importa el orden)."""
    ordered = sorted(entries, key=lambda e: e.entry_timestamp)
    intervals: list[WorkedInterval] = []
    pending_in: datetime | None = None
    for entry in ordered:
        if entry.entry_type == "entrada":
            pending_in = entry.entry_timestamp
        elif pending_in is not None:
            intervals.append(WorkedInterval(clock_in=pending_in, clock_out=entry.entry_timestamp))
            pending_in = None
    if pending_in is not None:
        intervals.append(WorkedInterval(clock_in=pending_in, clock_out=None))
    return intervals


def worked_hours_by_day(entries: list[TimeClockEntry]) -> dict[date, float]:
    """Horas trabajadas por día (solo pares entrada/salida completos; un
    intervalo abierto -- entrada sin salida -- no suma horas todavía, se
    debe corregir o esperar a que se registre la salida). Un turno nocturno
    que cruza medianoche se atribuye entero al día en que empezó."""
    totals: dict[date, float] = {}
    for interval in pair_entries(entries):
        if interval.duration_hours is None:
            continue
        day = interval.clock_in.date()
        totals[day] = round(totals.get(day, 0.0) + interval.duration_hours, 2)
    return totals


def total_worked_hours(entries: list[TimeClockEntry]) -> float:
    return round(
        sum(
            interval.duration_hours
            for interval in pair_entries(entries)
            if interval.duration_hours is not None
        ),
        2,
    )


def worked_hours_by_day_in_range(
    entries: list[TimeClockEntry], start: date, end: date
) -> dict[date, float]:
    """Como worked_hours_by_day(), pero pensada para cuando `entries` es el
    historial COMPLETO de un empleado (no solo el de un mes/rango concreto):
    un turno que cruza el límite de un mes se empareja correctamente porque
    el fichaje de salida del mes siguiente (o de entrada del anterior)
    sigue en la lista completa, y aquí solo se descartan del resultado los
    días fuera de [start, end]. Sin esto, filtrar los fichajes por mes
    ANTES de emparejar (como hacía TimeEntryRepository.list_for_month())
    dejaba ese turno sin horas en NINGÚN mes: la entrada quedaba huérfana
    en el mes en que empezó y la salida quedaba huérfana, sin pareja, en
    el mes siguiente."""
    return {
        day: hours for day, hours in worked_hours_by_day(entries).items() if start <= day <= end
    }


def total_worked_hours_in_range(entries: list[TimeClockEntry], start: date, end: date) -> float:
    return round(sum(worked_hours_by_day_in_range(entries, start, end).values()), 2)
