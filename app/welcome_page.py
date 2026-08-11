from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import date, datetime
from tkinter import ttk

from app import theme
from app.calendar_widget import MONTH_NAMES, WEEKDAY_FULL_LABELS
from app.repository import Repositories, gather_alerts

# Tercera copia de estas tablas (ya duplicadas en alerts_ui.py/email_digest.py,
# ver README) -- no es el momento de unificarlas, mismo criterio ya
# documentado en los otros dos sitios. Solo se necesita singular/plural en
# minúsculas aquí (desglose de una línea, "1 contrato · 2 cumpleaños"), a
# diferencia de alerts_ui.py, que usa Title Case como encabezado de sección.
# El singular no se deriva con un simple .lower() porque eso minuscularía
# también las siglas (RGPD, PRL), que deben quedarse en mayúsculas.
_CATEGORY_LABELS_SINGULAR = {
    "contrato": "contrato",
    "cumpleanos": "cumpleaños",
    "revision_medica": "revisión médica",
    "retencion_rgpd": "retención RGPD",
    "formacion_prl": "formación PRL",
    "certificacion": "certificación",
    "salario_minimo": "salario mínimo",
}
# Plural correcto de cada categoría -- un "+s" ingenuo falla para casi todas
# (p. ej. "revisión médicas", "cumpleañoss"), así que se escribe a mano en
# vez de intentar derivarlo.
_CATEGORY_LABELS_PLURAL = {
    "contrato": "contratos",
    "cumpleanos": "cumpleaños",
    "revision_medica": "revisiones médicas",
    "retencion_rgpd": "retenciones RGPD",
    "formacion_prl": "formaciones PRL",
    "certificacion": "certificaciones",
    "salario_minimo": "salarios mínimos",
}


def _greeting(hour: int) -> str:
    if 6 <= hour < 13:
        return "¡Buenos días!"
    if 13 <= hour < 20:
        return "¡Buenas tardes!"
    return "¡Buenas noches!"


def _payroll_needs_warning(payroll_count: int, active_in_scope: int, today: date) -> bool:
    # Solo se resalta a partir del día 29 -- antes de eso, que falten
    # nóminas por generar es lo normal, no algo que avisar (pedido así
    # explícitamente, no un valor arbitrario).
    return payroll_count < active_in_scope and today.day >= 29


class WelcomePage(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        on_go_employees: Callable[[], None],
        on_go_payroll: Callable[[], None],
        on_go_departments: Callable[[], None],
        on_export: Callable[[], None],
        on_go_calendar: Callable[[], None],
        on_go_alerts: Callable[[], None],
        on_go_org_chart: Callable[[], None],
        on_go_candidates: Callable[[], None],
        is_admin: bool = True,
        locked_department_id: int | None = None,
    ) -> None:
        super().__init__(parent, padding=24)
        self._repos = repos
        self._on_go_employees = on_go_employees
        self._on_go_payroll = on_go_payroll
        self._on_go_departments = on_go_departments
        self._on_export = on_export
        self._on_go_calendar = on_go_calendar
        self._on_go_alerts = on_go_alerts
        self._on_go_org_chart = on_go_org_chart
        self._on_go_candidates = on_go_candidates
        self._is_admin = is_admin
        self._locked_department_id = locked_department_id

        # Sin pack() aquí -- refresh() lo empaqueta solo si hay alertas
        # activas, con before=self._greeting_label para que quede arriba
        # del todo. Si se empaquetara aquí sin más, iría DETRÁS de todo lo
        # que se construye a continuación (al final de la página, no arriba).
        self._alert_banner = tk.Frame(self)

        self._greeting_label = ttk.Label(self, style="PageHeading.TLabel")
        self._greeting_label.pack(anchor="w")
        self._date_label = ttk.Label(self, style="Muted.TLabel")
        self._date_label.pack(anchor="w", pady=(0, 20))

        self._cards_frame = ttk.Frame(self)
        self._cards_frame.pack(anchor="w", fill="x", pady=(0, 16))

        self._details_frame = ttk.Frame(self)
        self._details_frame.pack(anchor="w", fill="x", pady=(0, 24))

        quick_access = ttk.Labelframe(self, text="Accesos rápidos", padding=12)
        quick_access.pack(anchor="w")
        ttk.Button(
            quick_access,
            text="Lista de empleados",
            width=24,
            command=self._on_go_employees,
            style="Accent.TButton",
        ).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(
            quick_access,
            text="Nóminas",
            width=24,
            command=self._on_go_payroll,
            style="Accent.TButton",
        ).grid(row=0, column=1, padx=4, pady=4)
        # "Departamentos" gestiona alta/baja de cualquier departamento y da
        # acceso a su calendario laboral completo -- solo para admin, igual
        # que en la barra lateral. No basta con ocultar el botón aquí:
        # _open_department_manager() en MainWindow también comprueba
        # is_admin por su cuenta, para que ningún otro camino futuro pueda
        # volver a abrirlo sin pasar por este control.
        export_column = 3
        if self._is_admin:
            ttk.Button(
                quick_access,
                text="Departamentos",
                width=24,
                command=self._on_go_departments,
                style="Accent.TButton",
            ).grid(row=0, column=2, padx=4, pady=4)
        else:
            export_column = 2
        ttk.Button(
            quick_access,
            text="Exportar CSV...",
            width=24,
            command=self._on_export,
            style="Accent.TButton",
        ).grid(row=0, column=export_column, padx=4, pady=4)
        ttk.Button(
            quick_access,
            text="Calendario",
            width=24,
            command=self._on_go_calendar,
            style="Accent.TButton",
        ).grid(row=1, column=0, padx=4, pady=4)
        ttk.Button(
            quick_access,
            text="Alertas",
            width=24,
            command=self._on_go_alerts,
            style="Accent.TButton",
        ).grid(row=1, column=1, padx=4, pady=4)
        ttk.Button(
            quick_access,
            text="Organigrama",
            width=24,
            command=self._on_go_org_chart,
            style="Accent.TButton",
        ).grid(row=1, column=2, padx=4, pady=4)
        ttk.Button(
            quick_access,
            text="Candidatos",
            width=24,
            command=self._on_go_candidates,
            style="Accent.TButton",
        ).grid(row=1, column=3, padx=4, pady=4)

        self.refresh()

    def _make_card(
        self, row: int, column: int, value: str, caption: str, *, warning: bool = False
    ) -> None:
        frame_style = "CardWarning.TFrame" if warning else "Card.TFrame"
        value_style = "CardWarningValue.TLabel" if warning else "CardValue.TLabel"
        caption_style = "CardWarningCaption.TLabel" if warning else "CardCaption.TLabel"
        card = ttk.Frame(self._cards_frame, padding=12, style=frame_style)
        card.grid(row=row, column=column, padx=(0, 12), pady=(0, 12), sticky="w")
        ttk.Label(card, text=value, style=value_style).pack()
        ttk.Label(card, text=caption, style=caption_style, wraplength=130).pack()

    def apply_theme_change(self) -> None:
        # El banner de alertas es un tk.Frame/tk.Label con color fijado
        # directamente (ver refresh()), así que no se repinta solo con
        # apply_theme() -- refresh() ya lo reconstruye con theme.current()
        # vigente, más simple que reconfigurar los widgets existentes a mano.
        self.refresh()

    def refresh(self) -> None:
        now = datetime.now()
        today = now.date()
        self._greeting_label.configure(text=_greeting(now.hour))
        weekday = WEEKDAY_FULL_LABELS[today.isoweekday() - 1]
        month_name = MONTH_NAMES[today.month - 1].lower()
        self._date_label.configure(
            text=f"{weekday}, {today.day} de {month_name} de {today.year}"
        )

        for widget in self._alert_banner.winfo_children():
            widget.destroy()
        alerts = gather_alerts(self._repos, self._locked_department_id, today)
        if alerts:
            palette = theme.current()
            self._alert_banner.configure(background=palette.alert_bg)
            counts: dict[str, int] = {}
            for alert in alerts:
                counts[alert.category] = counts.get(alert.category, 0) + 1
            breakdown = " · ".join(
                f"{count} "
                f"{_CATEGORY_LABELS_SINGULAR[category] if count == 1 else _CATEGORY_LABELS_PLURAL[category]}"
                for category, count in counts.items()
            )
            heading = (
                "⚠ 1 alerta requiere tu atención"
                if len(alerts) == 1
                else f"⚠ {len(alerts)} alertas requieren tu atención"
            )
            text_frame = tk.Frame(self._alert_banner, background=palette.alert_bg)
            text_frame.pack(side="left", fill="both", expand=True, padx=10, pady=8)
            tk.Label(
                text_frame,
                text=heading,
                background=palette.alert_bg,
                foreground=palette.alert_fg,
                font=("TkDefaultFont", 10, "bold"),
                anchor="w",
                justify="left",
            ).pack(anchor="w")
            tk.Label(
                text_frame,
                text=breakdown,
                background=palette.alert_bg,
                foreground=palette.alert_fg,
                wraplength=640,
                anchor="w",
                justify="left",
            ).pack(anchor="w")
            ttk.Button(
                self._alert_banner, text="Ver alertas", command=self._on_go_alerts
            ).pack(side="right", padx=10, pady=8)
            self._alert_banner.pack(
                side="top", fill="x", pady=(0, 16), before=self._greeting_label
            )
        else:
            self._alert_banner.pack_forget()

        all_employees = self._repos.employees.search()
        active_count = sum(1 for e in all_employees if e.active)
        employees_by_id = {e.id: e for e in all_employees}
        departments = self._repos.departments.list_all()
        departments_by_id = {d.id: d for d in departments}
        day_types_by_id = {dt.id: dt for dt in self._repos.day_types.list_all()}
        absences_today = self._repos.absences.list_for_date(today)
        closures_today = self._repos.closures.list_for_date(today)

        # Tarjetas 5-7 (nuevas) SÍ se acotan por locked_department_id, a
        # diferencia de las 4 de abajo (deliberadamente compañía-completa,
        # ver comentario más abajo) -- porque las páginas a las que apuntan
        # (Coste de personal, Solicitudes de ausencia, Candidatos) ya están
        # bloqueadas por departamento para un encargado, sin ninguna vista
        # de compañía completa: mostrar aquí un número que esa página nunca
        # revela sería engañoso.
        active_in_scope = sum(
            1
            for e in all_employees
            if e.active
            and (
                self._locked_department_id is None
                or e.department_id == self._locked_department_id
            )
        )
        payroll_count = self._repos.payroll_records.monthly_totals(
            today.year, department_id=self._locked_department_id
        )[today.month - 1].payroll_count
        payroll_warning = _payroll_needs_warning(payroll_count, active_in_scope, today)

        pending_requests = (
            self._repos.absences.list_pending_for_department(self._locked_department_id)
            if self._locked_department_id is not None
            else self._repos.absences.list_pending()
        )

        candidates = self._repos.candidates.list_all(department_id=self._locked_department_id)
        candidates_in_process = [
            c for c in candidates if c.phase not in ("Contratado", "Descartado")
        ]

        for widget in self._cards_frame.winfo_children():
            widget.destroy()
        cards: list[tuple[str, str, bool]] = [
            (str(active_count), "Empleados activos", False),
            (str(len(departments)), "Departamentos", False),
            (str(len(absences_today)), "Ausentes hoy", False),
            (str(len(closures_today)), "Cierres hoy", False),
            (
                f"{payroll_count}/{active_in_scope}",
                "Nóminas generadas (mes actual)",
                payroll_warning,
            ),
            (str(len(pending_requests)), "Solicitudes pendientes", False),
            (str(len(candidates_in_process)), "Candidatos en proceso", False),
        ]
        for index, (value, caption, warning) in enumerate(cards):
            self._make_card(index // 4, index % 4, value, caption, warning=warning)

        for widget in self._details_frame.winfo_children():
            widget.destroy()

        # Las 4 tarjetas de conteo de arriba son agregadas a propósito,
        # incluso para un encargado (se consideró de baja sensibilidad, ver
        # README) -- pero estas líneas de detalle van más allá de un
        # simple contador: nombran a personas concretas junto a la
        # categoría de su ausencia (que puede ser una baja médica). Eso sí
        # se restringe al propio departamento del encargado, igual que el
        # resto de páginas con locked_department_id.
        if self._locked_department_id is not None:
            absences_today = [
                a
                for a in absences_today
                if employees_by_id.get(a.employee_id) is not None
                and employees_by_id[a.employee_id].department_id == self._locked_department_id
            ]
            closures_today = [
                c for c in closures_today if c.department_id == self._locked_department_id
            ]

        if absences_today:
            absence_names = [
                f"{employees_by_id[a.employee_id].full_name} "
                f"({day_types_by_id[a.day_type_id].name})"
                for a in absences_today
                if a.employee_id in employees_by_id and a.day_type_id in day_types_by_id
            ]
            if absence_names:
                ttk.Label(
                    self._details_frame,
                    text="Ausentes hoy: " + ", ".join(absence_names),
                    wraplength=760,
                    justify="left",
                ).pack(anchor="w", pady=(0, 4))

        if closures_today:
            closure_names = [
                f"{departments_by_id[c.department_id].name} "
                f"({day_types_by_id[c.day_type_id].name})"
                for c in closures_today
                if c.department_id in departments_by_id and c.day_type_id in day_types_by_id
            ]
            if closure_names:
                ttk.Label(
                    self._details_frame,
                    text="Cierres hoy: " + ", ".join(closure_names),
                    wraplength=760,
                    justify="left",
                ).pack(anchor="w")
