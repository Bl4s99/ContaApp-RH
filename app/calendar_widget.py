from __future__ import annotations

import calendar
import tkinter as tk
from collections.abc import Callable
from datetime import date
from functools import partial
from tkinter import ttk

from app import theme
from app.window_utils import center_window

MONTH_NAMES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
WEEKDAY_LABELS = ["L", "M", "X", "J", "V", "S", "D"]
WEEKDAY_FULL_LABELS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
HOUR_VALUES = [f"{hour:02d}" for hour in range(24)]
MINUTE_VALUES = [f"{minute:02d}" for minute in range(0, 60, 15)]
PRESET_COLORS = [
    "#2ecc71", "#e67e22", "#e74c3c", "#9b59b6", "#3498db",
    "#1abc9c", "#f1c40f", "#7f8c8d", "#c0392b", "#34495e",
]


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    zero_based_total = year * 12 + (month - 1) + delta
    new_year, new_month_zero_based = divmod(zero_based_total, 12)
    return new_year, new_month_zero_based + 1


class CalendarPopup(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        on_select: Callable[[date], None],
        initial: date | None = None,
        max_date: date | None = None,
        min_date: date | None = None,
        marked_dates: frozenset[date] = frozenset(),
    ) -> None:
        """marked_dates son días que se resaltan como "ya festivo/cierre
        registrado" (p. ej. vía una plantilla de festivos ya aplicada al
        departamento en cuestión) -- deliberadamente NO precarga ningún
        festivo oficial por su cuenta (el calendario real cambia cada año y
        varía por comunidad/localidad, ver HolidayTemplateRepository); solo
        refleja lo que el propio departamento ya tiene registrado."""
        super().__init__(parent)
        self.title("Seleccionar fecha")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._on_select = on_select
        self._max_date = max_date
        self._min_date = min_date
        self._marked_dates = marked_dates
        start = initial or date.today()
        self._view_year = start.year
        self._view_month = start.month

        header = ttk.Frame(self, padding=6)
        header.pack(fill="x")
        ttk.Button(header, text="<", width=3, command=self._go_previous_month).pack(side="left")
        self._header_label = ttk.Label(header, anchor="center", width=18)
        self._header_label.pack(side="left", expand=True, fill="x")
        ttk.Button(header, text=">", width=3, command=self._go_next_month).pack(side="left")

        weekday_row = ttk.Frame(self, padding=(6, 0, 6, 0))
        weekday_row.pack(fill="x")
        for name in WEEKDAY_LABELS:
            ttk.Label(weekday_row, text=name, width=4, anchor="center").pack(side="left")

        self._grid_frame = ttk.Frame(self, padding=(6, 0, 6, 6))
        self._grid_frame.pack()

        self._render_month()

        self.bind("<Escape>", lambda _event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _go_previous_month(self) -> None:
        self._view_year, self._view_month = shift_month(self._view_year, self._view_month, -1)
        self._render_month()

    def _go_next_month(self) -> None:
        self._view_year, self._view_month = shift_month(self._view_year, self._view_month, 1)
        self._render_month()

    def _render_month(self) -> None:
        self._header_label.configure(
            text=f"{MONTH_NAMES[self._view_month - 1]} {self._view_year}"
        )
        for widget in self._grid_frame.winfo_children():
            widget.destroy()

        palette = theme.current()
        today = date.today()
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(
            self._view_year, self._view_month
        )
        for row, week in enumerate(weeks):
            for col, day in enumerate(week):
                in_month = day.month == self._view_month
                disabled = (self._max_date is not None and day > self._max_date) or (
                    self._min_date is not None and day < self._min_date
                )
                # "Festivo" nunca gana al resaltado de "hoy" (se conserva
                # inequívoco, es el propósito original de este selector);
                # fuera de eso, un día ya marcado como cierre para el
                # departamento en cuestión se resalta con el mismo tono ya
                # usado para "esto necesita tu atención" (aviso de nóminas).
                is_holiday = (
                    in_month and not disabled and day != today and day in self._marked_dates
                )
                if day == today:
                    bg = palette.today_highlight
                elif is_holiday:
                    bg = palette.disclaimer_bg
                else:
                    bg = palette.bg
                if not in_month or disabled:
                    fg = palette.text_muted
                elif is_holiday:
                    fg = palette.disclaimer_fg
                else:
                    fg = palette.text
                button = tk.Button(
                    self._grid_frame,
                    text=str(day.day),
                    width=3,
                    relief="solid" if day == today else "flat",
                    borderwidth=1 if day == today else 0,
                    bg=bg,
                    fg=fg,
                    state="disabled" if disabled else "normal",
                    command=partial(self._select, day),
                )
                button.grid(row=row, column=col, padx=1, pady=1)

    def _select(self, chosen: date) -> None:
        self._on_select(chosen)
        self.destroy()


class DateEntry(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        initial: date | None = None,
        max_date: date | None = None,
        min_date: date | None = None,
        marked_dates: frozenset[date] = frozenset(),
    ) -> None:
        super().__init__(parent)
        self._max_date = max_date
        self._min_date = min_date
        self._marked_dates = marked_dates
        self.value_var = tk.StringVar(value=(initial or date.today()).isoformat())
        self.entry = ttk.Entry(self, textvariable=self.value_var, width=24, state="readonly")
        self.entry.pack(side="left")
        self.picker_button = ttk.Button(
            self, text="\U0001F4C5", width=3, command=self._open_picker
        )
        self.picker_button.pack(side="left", padx=(4, 0))

    def set_enabled(self, enabled: bool) -> None:
        self.entry.configure(state="readonly" if enabled else "disabled")
        self.picker_button.configure(state="normal" if enabled else "disabled")

    def _open_picker(self) -> None:
        try:
            current = date.fromisoformat(self.value_var.get())
        except ValueError:
            current = date.today()
        CalendarPopup(
            self,
            on_select=self._set_value,
            initial=current,
            max_date=self._max_date,
            min_date=self._min_date,
            marked_dates=self._marked_dates,
        )

    def _set_value(self, chosen: date) -> None:
        self.value_var.set(chosen.isoformat())

    def get(self) -> str:
        return self.value_var.get()


class TimeEntry(ttk.Frame):
    def __init__(self, parent: tk.Misc, initial: str = "09:00", minute_step: int = 15) -> None:
        super().__init__(parent)
        # minute_step=15 (el histórico, usado por los horarios de turno) se
        # queda igual en todas las llamadas existentes; un fichaje real
        # necesita minuto exacto, no solo cuartos de hora -- de ahí el param.
        minute_values = [f"{minute:02d}" for minute in range(0, 60, minute_step)]
        hour, _, minute = initial.partition(":")
        self.hour_var = tk.StringVar(value=hour if hour in HOUR_VALUES else "09")
        self.minute_var = tk.StringVar(value=minute if minute in minute_values else minute_values[0])

        self.hour_combo = ttk.Combobox(
            self, state="readonly", width=3, values=HOUR_VALUES, textvariable=self.hour_var
        )
        self.hour_combo.pack(side="left")
        ttk.Label(self, text=":").pack(side="left")
        self.minute_combo = ttk.Combobox(
            self, state="readonly", width=3, values=minute_values, textvariable=self.minute_var
        )
        self.minute_combo.pack(side="left")

    def get(self) -> str:
        return f"{self.hour_var.get()}:{self.minute_var.get()}"

    def set_enabled(self, enabled: bool) -> None:
        state = "readonly" if enabled else "disabled"
        self.hour_combo.configure(state=state)
        self.minute_combo.configure(state=state)


class WeekdaySelector(ttk.Frame):
    def __init__(self, parent: tk.Misc, initial: frozenset[int] = frozenset()) -> None:
        super().__init__(parent)
        self._vars: dict[int, tk.BooleanVar] = {}
        for iso_day, label in enumerate(WEEKDAY_FULL_LABELS, start=1):
            var = tk.BooleanVar(value=iso_day in initial)
            self._vars[iso_day] = var
            ttk.Checkbutton(self, text=label[:3], variable=var).pack(side="left", padx=2)

    def get(self) -> frozenset[int]:
        return frozenset(day for day, var in self._vars.items() if var.get())

    def set_weekdays(self, days: frozenset[int]) -> None:
        for day, var in self._vars.items():
            var.set(day in days)


class ColorSwatchPicker(ttk.Frame):
    def __init__(self, parent: tk.Misc, initial: str | None = None) -> None:
        super().__init__(parent)
        self.color_var = tk.StringVar(value=initial if initial in PRESET_COLORS else PRESET_COLORS[0])
        self._buttons: dict[str, tk.Button] = {}
        for color in PRESET_COLORS:
            button = tk.Button(
                self,
                bg=color,
                activebackground=color,
                width=2,
                relief="flat",
                borderwidth=1,
                command=partial(self._select, color),
            )
            button.pack(side="left", padx=1)
            self._buttons[color] = button
        self._refresh_selection()

    def set(self, color: str) -> None:
        self._select(color if color in PRESET_COLORS else PRESET_COLORS[0])

    def _select(self, color: str) -> None:
        self.color_var.set(color)
        self._refresh_selection()

    def _refresh_selection(self) -> None:
        selected = self.color_var.get()
        for color, button in self._buttons.items():
            is_selected = color == selected
            button.configure(relief="sunken" if is_selected else "flat", borderwidth=3 if is_selected else 1)

    def get(self) -> str:
        return self.color_var.get()


class ToggleSwitch(tk.Canvas):
    """Interruptor deslizante horizontal on/off (estilo interruptor de
    móvil) -- Tkinter/ttk no tiene un widget equivalente nativo, así que se
    dibuja a mano sobre un Canvas: dos círculos + un rectángulo central
    forman la pastilla (no hay primitiva de rectángulo redondeado), y otro
    círculo hace de pomo deslizante."""

    _WIDTH = 44
    _HEIGHT = 22
    _PADDING = 3

    def __init__(
        self,
        parent: tk.Misc,
        initial: bool,
        on_toggle: Callable[[bool], None],
        bg: str,
        on_color: str,
        off_color: str,
        knob_color: str = "#ffffff",
    ) -> None:
        super().__init__(
            parent,
            width=self._WIDTH,
            height=self._HEIGHT,
            highlightthickness=0,
            bd=0,
            bg=bg,
            cursor="hand2",
        )
        self._on = initial
        self._on_toggle = on_toggle
        self._on_color = on_color
        self._off_color = off_color
        self._knob_color = knob_color
        self.bind("<Button-1>", lambda _e: self.toggle())
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        track_color = self._on_color if self._on else self._off_color
        d = self._HEIGHT
        r = d / 2
        # Pastilla: dos círculos en los extremos + un rectángulo central que
        # los une, todos del mismo color -- sin esto (solo el rectángulo)
        # los extremos quedarían cuadrados en vez de redondeados.
        self.create_oval(0, 0, d, d, fill=track_color, outline=track_color)
        self.create_oval(self._WIDTH - d, 0, self._WIDTH, d, fill=track_color, outline=track_color)
        self.create_rectangle(r, 0, self._WIDTH - r, d, fill=track_color, outline=track_color)

        knob_diameter = d - self._PADDING * 2
        knob_x = (self._WIDTH - d + self._PADDING) if self._on else self._PADDING
        self.create_oval(
            knob_x,
            self._PADDING,
            knob_x + knob_diameter,
            self._PADDING + knob_diameter,
            fill=self._knob_color,
            outline=self._knob_color,
        )

    def toggle(self) -> None:
        self.set(not self._on)

    def set(self, value: bool) -> None:
        if value == self._on:
            return
        self._on = value
        self._draw()
        self._on_toggle(self._on)

    def get(self) -> bool:
        return self._on

    def set_colors(self, *, bg: str, on_color: str, off_color: str, knob_color: str = "#ffffff") -> None:
        self._on_color = on_color
        self._off_color = off_color
        self._knob_color = knob_color
        self.configure(bg=bg)
        self._draw()


class ScrollableFrame(ttk.Frame):
    """Contenedor con scroll vertical únicamente, con rueda del ratón
    incluida -- para paneles que pueden no caber en alto pero cuyo
    contenido debe ocupar todo el ancho disponible (p. ej. la barra
    lateral, cuyos botones van con fill="x"). A diferencia de
    ScrollableFrame2D (pensado para una rejilla que puede desbordar en
    cualquier dirección), aquí el ancho del contenido interior se ajusta
    siempre al del canvas -- nunca aparece una barra horizontal."""

    def __init__(self, parent: tk.Misc, bg: str = "SystemButtonFace") -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=bg)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._inner_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind(
            "<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._inner_window, width=e.width),
        )
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # La rueda del ratón solo debe desplazar este panel mientras el
        # cursor esté encima -- bind_all/unbind_all en Enter/Leave evita que
        # la rueda "se quede pegada" desplazando la barra lateral aunque el
        # cursor ya esté sobre el contenido principal.
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _bind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def set_bg(self, bg: str) -> None:
        self.canvas.configure(bg=bg)
        self.inner.configure(bg=bg)


class ScrollableFrame2D(ttk.Frame):
    """Canvas + scrollbars en ambos ejes -- para contenido ancho/alto que
    puede desbordar en cualquier dirección (p. ej. la rejilla del
    calendario). El propio `canvas` se expone directamente para que el
    llamador dibuje sobre él con create_rectangle/create_text (mucho más
    barato que un widget real por celda para cientos de celdas -- ver
    calendar_page.py) y fije su scrollregion él mismo tras dibujar."""

    def __init__(self, parent: tk.Misc, height: int = 380, bg: str = "SystemButtonFace") -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, bg=bg)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def set_height(self, height: int) -> None:
        self.canvas.configure(height=height)

    def set_bg(self, bg: str) -> None:
        self.canvas.configure(bg=bg)
