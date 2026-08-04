from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk

from app import theme
from app.alerts import (
    DEFAULT_ALERT_WINDOW_DAYS,
    all_alerts,
    retention_review_alerts,
    training_expiry_alerts,
)
from app.repository import Repositories

_CATEGORY_LABELS = {
    "contrato": "Contrato",
    "cumpleanos": "Cumpleaños",
    "revision_medica": "Revisión médica",
    "retencion_rgpd": "Retención RGPD",
    "formacion_prl": "Formación PRL",
    "certificacion": "Certificación",
}


class AlertsPage(ttk.Frame):
    def __init__(
        self, parent: tk.Misc, repos: Repositories, locked_department_id: int | None = None
    ) -> None:
        super().__init__(parent, padding=12)
        self._repos = repos
        self._locked_department_id = locked_department_id
        self._build_widgets()
        self.refresh()

    def _build_widgets(self) -> None:
        ttk.Label(self, text="Alertas", style="PageHeading.TLabel").pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(
            self,
            text=(
                f"Contratos que vencen en los próximos {DEFAULT_ALERT_WINDOW_DAYS} días, "
                "cumpleaños próximos, revisiones médicas próximas o pendientes, formación "
                "PRL pendiente y certificaciones próximas a caducar o ya caducadas, para "
                "empleados activos; y empleados de baja cuyo periodo de conservación de "
                "datos está por vencer o ya venció. Las filas en rojo ya están vencidas."
            ),
            style="Muted.TLabel",
            wraplength=640,
        ).pack(anchor="w", pady=(0, 10))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True)
        columns = ("categoria", "empleado", "fecha", "detalle")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        for col, label, width in [
            ("categoria", "Tipo", 130),
            ("empleado", "Empleado", 180),
            ("fecha", "Fecha", 100),
            ("detalle", "Detalle", 280),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w")
        self.tree.tag_configure("urgent", foreground=theme.current().danger)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.status_label = ttk.Label(self, text="", style="Muted.TLabel")
        self.status_label.pack(anchor="w", pady=(6, 0))

    def apply_theme_change(self) -> None:
        self.tree.tag_configure("urgent", foreground=theme.current().danger)

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        # Sin active_only: las tres alertas "clásicas" se autolimitan a
        # empleados activos y retention_review_alerts() a los inactivos, así
        # que una sola consulta con todos sirve para las cuatro categorías.
        employees = self._repos.employees.search(department_id=self._locked_department_id)
        today = date.today()
        retention_years = self._repos.app_settings.get_data_retention_years()
        # trainings sin acotar por departamento -- training_expiry_alerts()
        # ya descarta las que no pertenecen a `employees` (ver su docstring).
        trainings = self._repos.trainings.list_all()
        alerts = sorted(
            all_alerts(employees, today)
            + retention_review_alerts(employees, today, retention_years)
            + training_expiry_alerts(employees, trainings, today),
            key=lambda a: a.target_date,
        )
        for idx, alert in enumerate(alerts):
            self.tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    _CATEGORY_LABELS[alert.category],
                    alert.employee_name,
                    alert.target_date.strftime("%d/%m/%Y"),
                    alert.detail,
                ),
                tags=("urgent",) if alert.days_remaining < 0 else (),
            )
        self.status_label.configure(text=f"{len(alerts)} alerta(s) activa(s)")
