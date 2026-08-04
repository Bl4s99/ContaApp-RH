from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.models import Department, Employee
from app.repository import Repositories


class OrgChartPage(ttk.Frame):
    """Quién supervisa directamente a quién dentro de cada departamento --
    construido enteramente a partir de Employee.manager_id, sin ninguna
    tabla ni entidad propia. Es solo lectura: asignar/cambiar un supervisor
    sigue haciéndose desde la ficha del empleado, no aquí.

    Solo empleados ACTIVOS entran en el árbol: quien ya no trabaja aquí no
    aporta nada a "cómo está organizado el equipo hoy". Un empleado cuyo
    supervisor no aparece en ese conjunto (sin supervisor asignado, o el
    supervisor ya de baja) se muestra como raíz, no como huérfano oculto."""

    def __init__(
        self, parent: tk.Misc, repos: Repositories, locked_department_id: int | None = None
    ) -> None:
        super().__init__(parent, padding=12)
        self._repos = repos
        self._locked_department_id = locked_department_id
        self._departments: list[Department] = []
        self._build_widgets()
        self.refresh()

    def _build_widgets(self) -> None:
        ttk.Label(self, text="Organigrama", style="PageHeading.TLabel").pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(
            self,
            text=(
                "Quién supervisa directamente a quién dentro de cada departamento, "
                "según el supervisor asignado en la ficha de cada empleado activo."
            ),
            style="Muted.TLabel",
            wraplength=640,
        ).pack(anchor="w", pady=(0, 10))

        filter_row = ttk.Frame(self)
        filter_row.pack(anchor="w", fill="x")
        ttk.Label(filter_row, text="Departamento:").pack(side="left")
        self.department_filter_var = tk.StringVar()
        self.department_filter_combo = ttk.Combobox(
            filter_row,
            state="disabled" if self._locked_department_id is not None else "readonly",
            width=22,
            textvariable=self.department_filter_var,
        )
        self.department_filter_combo.pack(side="left", padx=(4, 0))
        self.department_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self._render_tree())

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.tree = ttk.Treeview(
            tree_frame, columns=("puesto",), show="tree headings", selectmode="browse"
        )
        self.tree.heading("#0", text="Empleado")
        self.tree.heading("puesto", text="Puesto")
        self.tree.column("#0", width=240, anchor="w")
        self.tree.column("puesto", width=220, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.status_label = ttk.Label(self, text="", style="Muted.TLabel")
        self.status_label.pack(anchor="w", pady=(6, 0))

    def _visible_departments(self) -> list[Department]:
        if self._locked_department_id is None:
            return self._departments
        return [d for d in self._departments if d.id == self._locked_department_id]

    def refresh(self) -> None:
        self._departments = self._repos.departments.list_all()
        visible = self._visible_departments()
        names = [d.name for d in visible]
        self.department_filter_combo.configure(values=names)
        if self._locked_department_id is not None and visible:
            self.department_filter_var.set(visible[0].name)
        elif self.department_filter_var.get() not in names:
            self.department_filter_var.set(names[0] if names else "")
        self._render_tree()

    def _selected_department_id(self) -> int | None:
        if self._locked_department_id is not None:
            return self._locked_department_id
        return next(
            (d.id for d in self._departments if d.name == self.department_filter_var.get()),
            None,
        )

    def _render_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        department_id = self._selected_department_id()
        if department_id is None:
            self.status_label.configure(text="Cree al menos un departamento.")
            return

        employees = self._repos.employees.search(department_id=department_id, active_only=True)
        visible_ids = {e.id for e in employees}
        children_by_manager: dict[int | None, list[Employee]] = {}
        for employee in employees:
            manager_key = employee.manager_id if employee.manager_id in visible_ids else None
            children_by_manager.setdefault(manager_key, []).append(employee)
        for group in children_by_manager.values():
            group.sort(key=lambda e: e.full_name)

        # `visited` es una red de seguridad, no algo que deba dispararse
        # nunca en la práctica: la creación de ciclos ya se rechaza en
        # EmployeeRepository (ver _would_create_management_cycle), pero
        # recorrer el árbol confiando ciegamente en esa garantía dejaría a
        # esta pantalla sin defensa si algún día un dato llegara corrupto
        # por otra vía (edición manual de la base de datos, etc.).
        visited: set[int] = set()

        def insert_subtree(parent_iid: str, manager_key: int | None) -> None:
            for employee in children_by_manager.get(manager_key, []):
                assert employee.id is not None
                if employee.id in visited:
                    continue
                visited.add(employee.id)
                self.tree.insert(
                    parent_iid,
                    tk.END,
                    iid=str(employee.id),
                    text=employee.full_name,
                    values=(employee.position,),
                    open=True,
                )
                insert_subtree(str(employee.id), employee.id)

        insert_subtree("", None)
        self.status_label.configure(text=f"{len(employees)} empleado(s) activo(s)")
