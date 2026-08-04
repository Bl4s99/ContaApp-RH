from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk

from app.calendar_widget import MONTH_NAMES
from app.repository import Repositories


def _format_currency(value: float) -> str:
    # Formato español (punto de millar, coma decimal), igual que
    # employee_page._format_currency -- se duplica en vez de importarse
    # porque esa es privada al módulo y esta app no tiene todavía un sitio
    # común de utilidades de formato compartido entre páginas.
    us_formatted = f"{value:,.2f}"
    integer_part, decimal_part = us_formatted.split(".")
    integer_part = integer_part.replace(",", ".")
    return f"{integer_part},{decimal_part} €"


class CostReportPage(ttk.Frame):
    """Vista agregada de coste de personal -- tendencia mensual de un año y,
    para administradores, desglose por departamento del mes seleccionado.
    Se construye solo a partir de nóminas ya GENERADAS (payroll_records),
    nunca de una estimación en vivo -- ver el aviso propio de la página."""

    def __init__(
        self, parent: tk.Misc, repos: Repositories, locked_department_id: int | None = None
    ) -> None:
        super().__init__(parent, padding=12)
        self._repos = repos
        self._locked_department_id = locked_department_id
        today = date.today()
        self._view_year = today.year
        self._selected_month = today.month
        self.department_tree: ttk.Treeview | None = None
        self._build_widgets()
        self.refresh()

    def _build_widgets(self) -> None:
        ttk.Label(self, text="Coste de personal", style="PageHeading.TLabel").pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(
            self,
            text=(
                "Se calcula solo a partir de las nóminas ya generadas (página Nóminas), "
                "no de una estimación en vivo: un mes o empleado sin nómina generada no "
                "suma a estos totales, así que un total bajo puede significar coste bajo "
                "o, sencillamente, nóminas todavía sin generar — la columna \"Nóminas "
                "generadas\" indica cuántas componen cada cifra. El desglose por "
                "departamento usa el departamento ACTUAL de cada empleado, no el que "
                "tuviera en meses anteriores si desde entonces ha cambiado de departamento."
            ),
            style="Muted.TLabel",
            wraplength=640,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        year_nav = ttk.Frame(self)
        year_nav.pack(anchor="w", pady=(0, 8))
        ttk.Button(year_nav, text="<", width=3, command=self._go_previous_year).pack(side="left")
        self._year_label = ttk.Label(year_nav, width=10, anchor="center")
        self._year_label.pack(side="left", padx=4)
        ttk.Button(year_nav, text=">", width=3, command=self._go_next_year).pack(side="left")

        ttk.Label(self, text="Tendencia mensual", font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w", pady=(4, 2)
        )
        monthly_frame = ttk.Frame(self)
        monthly_frame.pack(fill="x")
        self.monthly_tree = ttk.Treeview(
            monthly_frame,
            columns=("mes", "nominas", "bruto", "coste"),
            show="headings",
            selectmode="browse",
            height=12,
        )
        for col, label, width in [
            ("mes", "Mes", 110),
            ("nominas", "Nóminas generadas", 130),
            ("bruto", "Bruto total", 130),
            ("coste", "Coste total empresa", 150),
        ]:
            self.monthly_tree.heading(col, text=label)
            self.monthly_tree.column(col, width=width, anchor="w")
        self.monthly_tree.pack(side="left", fill="x", expand=True)
        self.monthly_tree.bind("<<TreeviewSelect>>", self._handle_month_selected)

        self._year_total_label = ttk.Label(self, text="", font=("TkDefaultFont", 10, "bold"))
        self._year_total_label.pack(anchor="w", pady=(6, 12))

        if self._locked_department_id is None:
            self._department_heading = ttk.Label(
                self, text="", font=("TkDefaultFont", 10, "bold")
            )
            self._department_heading.pack(anchor="w", pady=(0, 2))
            department_frame = ttk.Frame(self)
            department_frame.pack(fill="x")
            self.department_tree = ttk.Treeview(
                department_frame,
                columns=("departamento", "nominas", "bruto", "coste"),
                show="headings",
                selectmode="none",
            )
            for col, label, width in [
                ("departamento", "Departamento", 160),
                ("nominas", "Nóminas generadas", 130),
                ("bruto", "Bruto total", 130),
                ("coste", "Coste total empresa", 150),
            ]:
                self.department_tree.heading(col, text=label)
                self.department_tree.column(col, width=width, anchor="w")
            self.department_tree.pack(side="left", fill="x", expand=True)

    def _go_previous_year(self) -> None:
        self._view_year -= 1
        self.refresh()

    def _go_next_year(self) -> None:
        self._view_year += 1
        self.refresh()

    def _handle_month_selected(self, _event: object) -> None:
        selection = self.monthly_tree.selection()
        if not selection:
            return
        self._selected_month = int(selection[0])
        self._refresh_department_table()

    def refresh(self) -> None:
        self._year_label.configure(text=str(self._view_year))
        self.monthly_tree.delete(*self.monthly_tree.get_children())
        summaries = self._repos.payroll_records.monthly_totals(
            self._view_year, department_id=self._locked_department_id
        )
        for summary in summaries:
            self.monthly_tree.insert(
                "",
                tk.END,
                iid=str(summary.month),
                values=(
                    MONTH_NAMES[summary.month - 1],
                    summary.payroll_count,
                    _format_currency(summary.total_gross),
                    _format_currency(summary.total_employer_cost),
                ),
            )
        total_payroll_count = sum(s.payroll_count for s in summaries)
        if total_payroll_count == 0:
            self._year_total_label.configure(
                text=f"Sin nóminas generadas en {self._view_year} todavía."
            )
        else:
            year_gross = sum(s.total_gross for s in summaries)
            year_cost = sum(s.total_employer_cost for s in summaries)
            self._year_total_label.configure(
                text=(
                    f"Total {self._view_year}: {_format_currency(year_gross)} bruto — "
                    f"{_format_currency(year_cost)} coste total empresa "
                    f"({total_payroll_count} nómina(s) generada(s))"
                )
            )
        self.monthly_tree.selection_set(str(self._selected_month))
        self._refresh_department_table()

    def _refresh_department_table(self) -> None:
        if self.department_tree is None:
            return
        self._department_heading.configure(
            text=f"Por departamento — {MONTH_NAMES[self._selected_month - 1]} {self._view_year}"
        )
        self.department_tree.delete(*self.department_tree.get_children())
        for summary in self._repos.payroll_records.department_totals(
            self._view_year, self._selected_month
        ):
            self.department_tree.insert(
                "",
                tk.END,
                iid=str(summary.department_id),
                values=(
                    summary.department_name,
                    summary.payroll_count,
                    _format_currency(summary.total_gross),
                    _format_currency(summary.total_employer_cost),
                ),
            )
