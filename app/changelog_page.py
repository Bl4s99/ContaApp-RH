"""Página de solo lectura: historial de versiones publicadas de ContaApp RH.
Contenido fijo desde app/changelog.py -- sin consultas a la base de datos, sin
diferencias por rol o departamento (todo el mundo ve lo mismo)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app import theme
from app.calendar_widget import MONTH_NAMES, ScrollableFrame
from app.changelog import CHANGELOG, ChangelogEntry
from app.version import VERSION


class ChangelogPage(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, padding=12)
        ttk.Label(self, text="Historial de versiones", style="PageHeading.TLabel").pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(
            self,
            text=(
                "Todas las actualizaciones publicadas de ContaApp RH, "
                "de la más reciente a la primera."
            ),
            style="Muted.TLabel",
            wraplength=640,
        ).pack(anchor="w", pady=(0, 10))

        self._scroll = ScrollableFrame(self, bg=theme.current().bg)
        self._scroll.pack(fill="both", expand=True)
        for entry in CHANGELOG:
            self._build_entry(self._scroll.inner, entry)

    def _build_entry(self, parent: tk.Misc, entry: ChangelogEntry) -> None:
        section = ttk.Frame(parent, padding=(0, 0, 0, 20))
        section.pack(anchor="w", fill="x")

        header = ttk.Frame(section)
        header.pack(anchor="w", fill="x")
        title = f"Versión {entry.version}"
        if entry.version == VERSION:
            title += "  ·  actual"
        ttk.Label(header, text=title, style="PageHeading.TLabel").pack(side="left")
        ttk.Label(header, text=_format_date(entry.date), style="Muted.TLabel").pack(
            side="left", padx=(10, 0), pady=(6, 0)
        )

        for note in entry.notes:
            ttk.Label(section, text=f"•  {note}", wraplength=640, justify="left").pack(
                anchor="w", pady=(6, 0)
            )

    def apply_theme_change(self) -> None:
        self._scroll.set_bg(theme.current().bg)


def _format_date(iso_date: str) -> str:
    # MONTH_NAMES está en mayúscula inicial para uso como etiqueta suelta
    # ("Julio 2026" en el calendario) -- aquí va en mitad de la frase, así
    # que se pasa a minúscula ("1 de julio de 2026"), igual que exige el
    # español (a diferencia del inglés, que sí capitaliza los meses).
    year, month, day = (int(part) for part in iso_date.split("-"))
    return f"{day} de {MONTH_NAMES[month - 1].lower()} de {year}"
