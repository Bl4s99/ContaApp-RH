from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app.repository import (
    AUDIT_ABSENCE_APPROVED,
    AUDIT_ABSENCE_REJECTED,
    Repositories,
    RepositoryError,
)


class AbsenceRequestsPage(ttk.Frame):
    def __init__(
        self, parent: tk.Misc, repos: Repositories, locked_department_id: int | None = None
    ) -> None:
        super().__init__(parent, padding=12)
        self._repos = repos
        self._locked_department_id = locked_department_id
        self._build_widgets()
        self.refresh()

    def _build_widgets(self) -> None:
        ttk.Label(self, text="Solicitudes de ausencia", style="PageHeading.TLabel").pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(
            self,
            text=(
                "Solicitudes pendientes de aprobación — no cuentan en el calendario ni en el "
                "saldo de vacaciones hasta que se aprueben."
            ),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True)
        columns = ("empleado", "tipo", "fecha", "nota")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        for col, label, width in [
            ("empleado", "Empleado", 180),
            ("tipo", "Tipo", 140),
            ("fecha", "Fecha", 100),
            ("nota", "Nota", 260),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        button_row = ttk.Frame(self)
        button_row.pack(fill="x", pady=(10, 0))
        ttk.Button(
            button_row, text="Aprobar", command=self._handle_approve, style="Accent.TButton"
        ).pack(side="left", padx=(0, 6))
        ttk.Button(button_row, text="Rechazar", command=self._handle_reject).pack(side="left")

        self.status_label = ttk.Label(self, text="", style="Muted.TLabel")
        self.status_label.pack(anchor="w", pady=(6, 0))

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        employees_by_id = {e.id: e for e in self._repos.employees.list_all() if e.id is not None}
        day_types_by_id = {
            dt.id: dt for dt in self._repos.day_types.list_all() if dt.id is not None
        }
        pending = (
            self._repos.absences.list_pending_for_department(self._locked_department_id)
            if self._locked_department_id is not None
            else self._repos.absences.list_pending()
        )
        for absence in pending:
            assert absence.id is not None
            employee = employees_by_id.get(absence.employee_id)
            day_type = day_types_by_id.get(absence.day_type_id)
            self.tree.insert(
                "",
                tk.END,
                iid=str(absence.id),
                values=(
                    employee.full_name if employee else "?",
                    day_type.name if day_type else "?",
                    absence.absence_date.strftime("%d/%m/%Y"),
                    absence.note,
                ),
            )
        self.status_label.configure(text=f"{len(pending)} solicitud(es) pendiente(s)")

    def _selected_absence_id(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _selected_absence_details(self, absence_id: int) -> str:
        values = self.tree.item(str(absence_id))["values"]
        return f"Empleado: {values[0]} — {values[1]} — Fecha: {values[2]}"

    def _handle_approve(self) -> None:
        absence_id = self._selected_absence_id()
        if absence_id is None:
            messagebox.showinfo("Solicitudes", "Seleccione una solicitud de la lista.", parent=self)
            return
        details = self._selected_absence_details(absence_id)
        try:
            self._repos.absences.approve(absence_id)
        except RepositoryError as exc:
            messagebox.showerror("Solicitudes", str(exc), parent=self)
            return
        self._repos.audit_log.record(AUDIT_ABSENCE_APPROVED, details)
        self.refresh()

    def _handle_reject(self) -> None:
        absence_id = self._selected_absence_id()
        if absence_id is None:
            messagebox.showinfo("Solicitudes", "Seleccione una solicitud de la lista.", parent=self)
            return
        if not messagebox.askyesno(
            "Confirmar rechazo", "¿Rechazar esta solicitud de ausencia?", parent=self
        ):
            return
        details = self._selected_absence_details(absence_id)
        try:
            self._repos.absences.reject(absence_id)
        except RepositoryError as exc:
            messagebox.showerror("Solicitudes", str(exc), parent=self)
            return
        self._repos.audit_log.record(AUDIT_ABSENCE_REJECTED, details)
        self.refresh()
