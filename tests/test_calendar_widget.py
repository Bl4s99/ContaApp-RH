from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date

import pytest

from app import calendar_widget, theme
from app.calendar_widget import (
    CalendarPopup,
    ColorSwatchPicker,
    DateEntry,
    TimeEntry,
    WeekdaySelector,
    shift_month,
)

# tk_root fixture is session-scoped in tests/conftest.py, shared across all
# test modules that need a live Tk interpreter.


def _button_for_date(popup: CalendarPopup, target: date) -> tk.Button:
    # Se busca por posición en la rejilla (no por texto del día) para evitar
    # ambigüedad: los días de relleno del mes anterior/siguiente pueden
    # repetir el mismo número que un día del mes en vista.
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(
        popup._view_year, popup._view_month
    )
    for widget in popup._grid_frame.winfo_children():
        if not isinstance(widget, tk.Button):
            continue
        info = widget.grid_info()
        row, col = int(info["row"]), int(info["column"])
        if weeks[row][col] == target:
            return widget
    raise AssertionError(f"No hay botón para {target} en la vista {popup._view_year}-{popup._view_month}")


class TestShiftMonth:
    def test_next_month_within_year(self) -> None:
        assert shift_month(2026, 3, 1) == (2026, 4)

    def test_previous_month_within_year(self) -> None:
        assert shift_month(2026, 3, -1) == (2026, 2)

    def test_rolls_over_to_next_year(self) -> None:
        assert shift_month(2026, 12, 1) == (2027, 1)

    def test_rolls_back_to_previous_year(self) -> None:
        assert shift_month(2026, 1, -1) == (2025, 12)

    @pytest.mark.parametrize("delta", [12, 24, -12, -24])
    def test_full_year_jumps_keep_month(self, delta: int) -> None:
        year, month = shift_month(2026, 7, delta)
        assert month == 7
        assert year == 2026 + delta // 12


class TestTimeEntry:
    def test_get_returns_initial_value(self, tk_root: tk.Tk) -> None:
        widget = TimeEntry(tk_root, initial="08:30")
        assert widget.get() == "08:30"

    def test_reflects_variable_changes(self, tk_root: tk.Tk) -> None:
        widget = TimeEntry(tk_root, initial="08:30")
        widget.hour_var.set("14")
        widget.minute_var.set("45")
        assert widget.get() == "14:45"

    def test_invalid_minute_falls_back_without_crashing(self, tk_root: tk.Tk) -> None:
        widget = TimeEntry(tk_root, initial="08:07")
        assert widget.get() == "08:00"

    def test_invalid_hour_falls_back_without_crashing(self, tk_root: tk.Tk) -> None:
        widget = TimeEntry(tk_root, initial="bad:00")
        assert widget.get() == "09:00"


class TestWeekdaySelector:
    def test_get_returns_initial_selection(self, tk_root: tk.Tk) -> None:
        widget = WeekdaySelector(tk_root, initial=frozenset({1, 3, 5}))
        assert widget.get() == frozenset({1, 3, 5})

    def test_defaults_to_empty(self, tk_root: tk.Tk) -> None:
        widget = WeekdaySelector(tk_root)
        assert widget.get() == frozenset()

    def test_set_weekdays_replaces_selection(self, tk_root: tk.Tk) -> None:
        widget = WeekdaySelector(tk_root, initial=frozenset({1, 2}))
        widget.set_weekdays(frozenset({6, 7}))
        assert widget.get() == frozenset({6, 7})

    def test_toggling_a_checkbox_updates_get(self, tk_root: tk.Tk) -> None:
        widget = WeekdaySelector(tk_root)
        widget._vars[2].set(True)
        assert widget.get() == frozenset({2})


class TestColorSwatchPicker:
    def test_get_returns_initial_color(self, tk_root: tk.Tk) -> None:
        widget = ColorSwatchPicker(tk_root, initial="#e74c3c")
        assert widget.get() == "#e74c3c"

    def test_unknown_initial_color_falls_back_to_first_preset(self, tk_root: tk.Tk) -> None:
        widget = ColorSwatchPicker(tk_root, initial="not-a-preset")
        assert widget.get() in widget._buttons

    def test_selecting_a_swatch_updates_get(self, tk_root: tk.Tk) -> None:
        widget = ColorSwatchPicker(tk_root, initial="#e74c3c")
        widget._select("#3498db")
        assert widget.get() == "#3498db"


class TestCalendarPopupMarkedDates:
    def test_marked_date_gets_disclaimer_colors(self, tk_root: tk.Tk) -> None:
        palette = theme.current()
        popup = CalendarPopup(
            tk_root,
            on_select=lambda _d: None,
            initial=date(2026, 3, 1),
            marked_dates=frozenset({date(2026, 3, 15)}),
        )
        try:
            button = _button_for_date(popup, date(2026, 3, 15))
            assert button.cget("bg") == palette.disclaimer_bg
            assert button.cget("fg") == palette.disclaimer_fg
        finally:
            popup.destroy()

    def test_unmarked_date_keeps_normal_colors(self, tk_root: tk.Tk) -> None:
        palette = theme.current()
        popup = CalendarPopup(
            tk_root,
            on_select=lambda _d: None,
            initial=date(2026, 3, 1),
            marked_dates=frozenset({date(2026, 3, 15)}),
        )
        try:
            button = _button_for_date(popup, date(2026, 3, 16))
            assert button.cget("bg") == palette.bg
            assert button.cget("fg") == palette.text
        finally:
            popup.destroy()

    def test_today_highlight_takes_priority_over_marked_date(self, tk_root: tk.Tk) -> None:
        palette = theme.current()
        today = date.today()
        popup = CalendarPopup(
            tk_root,
            on_select=lambda _d: None,
            initial=today,
            marked_dates=frozenset({today}),
        )
        try:
            button = _button_for_date(popup, today)
            assert button.cget("bg") == palette.today_highlight
        finally:
            popup.destroy()

    def test_disabled_date_is_not_treated_as_a_holiday_even_if_marked(self, tk_root: tk.Tk) -> None:
        palette = theme.current()
        popup = CalendarPopup(
            tk_root,
            on_select=lambda _d: None,
            initial=date(2026, 3, 1),
            max_date=date(2026, 3, 10),
            marked_dates=frozenset({date(2026, 3, 15)}),
        )
        try:
            button = _button_for_date(popup, date(2026, 3, 15))
            assert button.cget("bg") == palette.bg
            assert str(button.cget("state")) == "disabled"
        finally:
            popup.destroy()

    def test_navigating_to_another_month_still_marks_its_dates(self, tk_root: tk.Tk) -> None:
        palette = theme.current()
        popup = CalendarPopup(
            tk_root,
            on_select=lambda _d: None,
            initial=date(2026, 3, 1),
            marked_dates=frozenset({date(2026, 4, 15)}),
        )
        try:
            popup._go_next_month()
            button = _button_for_date(popup, date(2026, 4, 15))
            assert button.cget("bg") == palette.disclaimer_bg
        finally:
            popup.destroy()


class TestDateEntryMarkedDates:
    def test_stores_marked_dates(self, tk_root: tk.Tk) -> None:
        marks = frozenset({date(2026, 3, 15)})
        entry = DateEntry(tk_root, marked_dates=marks)
        try:
            assert entry._marked_dates == marks
        finally:
            entry.destroy()

    def test_open_picker_forwards_marked_dates_to_the_popup(
        self, tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        marks = frozenset({date(2026, 3, 15)})
        entry = DateEntry(tk_root, marked_dates=marks)
        captured: dict[str, object] = {}

        def fake_popup(_parent: tk.Misc, **kwargs: object) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(calendar_widget, "CalendarPopup", fake_popup)
        try:
            entry._open_picker()
            assert captured["marked_dates"] == marks
        finally:
            entry.destroy()
