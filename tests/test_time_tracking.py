from __future__ import annotations

from datetime import date, datetime

from app.models import TimeClockEntry
from app.time_tracking import (
    pair_entries,
    total_worked_hours,
    total_worked_hours_in_range,
    worked_hours_by_day,
    worked_hours_by_day_in_range,
)


def _entry(entry_type: str, when: datetime) -> TimeClockEntry:
    return TimeClockEntry(id=None, employee_id=1, entry_type=entry_type, entry_timestamp=when, note="")


class TestPairEntries:
    def test_empty_list(self) -> None:
        assert pair_entries([]) == []

    def test_single_complete_pair(self) -> None:
        entries = [
            _entry("entrada", datetime(2026, 3, 10, 9, 0)),
            _entry("salida", datetime(2026, 3, 10, 17, 0)),
        ]
        intervals = pair_entries(entries)
        assert len(intervals) == 1
        assert intervals[0].clock_in == datetime(2026, 3, 10, 9, 0)
        assert intervals[0].clock_out == datetime(2026, 3, 10, 17, 0)
        assert intervals[0].duration_hours == 8.0

    def test_unordered_input_is_sorted_first(self) -> None:
        entries = [
            _entry("salida", datetime(2026, 3, 10, 17, 0)),
            _entry("entrada", datetime(2026, 3, 10, 9, 0)),
        ]
        intervals = pair_entries(entries)
        assert len(intervals) == 1
        assert intervals[0].duration_hours == 8.0

    def test_multiple_pairs_same_day(self) -> None:
        # Turno partido: mañana y tarde con un hueco al mediodía.
        entries = [
            _entry("entrada", datetime(2026, 3, 10, 9, 0)),
            _entry("salida", datetime(2026, 3, 10, 13, 0)),
            _entry("entrada", datetime(2026, 3, 10, 15, 0)),
            _entry("salida", datetime(2026, 3, 10, 18, 0)),
        ]
        intervals = pair_entries(entries)
        assert [i.duration_hours for i in intervals] == [4.0, 3.0]

    def test_overnight_shift_crossing_midnight(self) -> None:
        entries = [
            _entry("entrada", datetime(2026, 3, 10, 22, 0)),
            _entry("salida", datetime(2026, 3, 11, 6, 0)),
        ]
        intervals = pair_entries(entries)
        assert len(intervals) == 1
        assert intervals[0].duration_hours == 8.0

    def test_trailing_open_entry_has_no_duration(self) -> None:
        entries = [_entry("entrada", datetime(2026, 3, 10, 9, 0))]
        intervals = pair_entries(entries)
        assert len(intervals) == 1
        assert intervals[0].clock_out is None
        assert intervals[0].duration_hours is None


class TestWorkedHoursByDay:
    def test_attributes_overnight_shift_to_the_start_day(self) -> None:
        entries = [
            _entry("entrada", datetime(2026, 3, 10, 22, 0)),
            _entry("salida", datetime(2026, 3, 11, 6, 0)),
        ]
        totals = worked_hours_by_day(entries)
        assert totals == {date(2026, 3, 10): 8.0}

    def test_sums_multiple_pairs_in_the_same_day(self) -> None:
        entries = [
            _entry("entrada", datetime(2026, 3, 10, 9, 0)),
            _entry("salida", datetime(2026, 3, 10, 13, 0)),
            _entry("entrada", datetime(2026, 3, 10, 15, 0)),
            _entry("salida", datetime(2026, 3, 10, 18, 0)),
        ]
        totals = worked_hours_by_day(entries)
        assert totals == {date(2026, 3, 10): 7.0}

    def test_open_entry_does_not_count(self) -> None:
        entries = [_entry("entrada", datetime(2026, 3, 10, 9, 0))]
        assert worked_hours_by_day(entries) == {}


class TestTotalWorkedHours:
    def test_sums_across_days(self) -> None:
        entries = [
            _entry("entrada", datetime(2026, 3, 10, 9, 0)),
            _entry("salida", datetime(2026, 3, 10, 17, 0)),
            _entry("entrada", datetime(2026, 3, 11, 9, 0)),
            _entry("salida", datetime(2026, 3, 11, 13, 0)),
        ]
        assert total_worked_hours(entries) == 12.0

    def test_zero_for_no_complete_pairs(self) -> None:
        assert total_worked_hours([_entry("entrada", datetime(2026, 3, 10, 9, 0))]) == 0.0


class TestWorkedHoursInRange:
    # Regresión: un turno nocturno que cruza el límite de un mes (entrada
    # el último día, salida al día siguiente) no contaba horas en NINGÚN
    # mes cuando `entries` se acotaba por mes ANTES de emparejar (como
    # hacía TimeEntryRepository.list_for_month()) -- la entrada quedaba
    # huérfana en el mes que empieza, y la salida, huérfana, en el mes
    # siguiente. La corrección: pasar el historial COMPLETO del empleado y
    # filtrar los DÍAS resultantes después de emparejar, no los fichajes
    # antes.
    def test_shift_crossing_month_boundary_counts_in_the_month_it_started(self) -> None:
        entries = [
            _entry("entrada", datetime(2026, 1, 31, 22, 0)),
            _entry("salida", datetime(2026, 2, 1, 6, 0)),
        ]
        january = worked_hours_by_day_in_range(entries, date(2026, 1, 1), date(2026, 1, 31))
        february = worked_hours_by_day_in_range(entries, date(2026, 2, 1), date(2026, 2, 28))
        assert january == {date(2026, 1, 31): 8.0}
        assert february == {}
        assert total_worked_hours_in_range(entries, date(2026, 1, 1), date(2026, 1, 31)) == 8.0
        assert total_worked_hours_in_range(entries, date(2026, 2, 1), date(2026, 2, 28)) == 0.0

    def test_does_not_double_count_across_the_two_months(self) -> None:
        entries = [
            _entry("entrada", datetime(2026, 1, 31, 22, 0)),
            _entry("salida", datetime(2026, 2, 1, 6, 0)),
        ]
        january_total = total_worked_hours_in_range(entries, date(2026, 1, 1), date(2026, 1, 31))
        february_total = total_worked_hours_in_range(entries, date(2026, 2, 1), date(2026, 2, 28))
        assert january_total + february_total == 8.0

    def test_excludes_days_outside_the_requested_range_even_without_crossing(self) -> None:
        entries = [
            _entry("entrada", datetime(2026, 1, 15, 9, 0)),
            _entry("salida", datetime(2026, 1, 15, 17, 0)),
            _entry("entrada", datetime(2026, 2, 15, 9, 0)),
            _entry("salida", datetime(2026, 2, 15, 17, 0)),
        ]
        january = worked_hours_by_day_in_range(entries, date(2026, 1, 1), date(2026, 1, 31))
        assert january == {date(2026, 1, 15): 8.0}
