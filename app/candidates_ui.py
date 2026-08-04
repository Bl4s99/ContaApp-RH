from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from app import theme, validation
from app.models import Candidate, Department
from app.repository import CandidateInput, Repositories, RepositoryError
from app.window_utils import center_window

_ALL_PHASES_LABEL = "Todas"


class CandidatesPage(ttk.Frame):
    """Seguimiento ligero de candidatos antes de contratar -- una lista
    simple con filtros por departamento y fase, sin selector de vacantes
    propio (una vacante es, en este modelo, un puesto + departamento, igual
    que en la ficha de empleado). Cambiar de fase es el mismo diálogo que
    crear/editar: no hay una acción rápida aparte para eso, a propósito,
    para no duplicar el formulario."""

    def __init__(
        self, parent: tk.Misc, repos: Repositories, locked_department_id: int | None = None
    ) -> None:
        super().__init__(parent, padding=12)
        self._repos = repos
        self._locked_department_id = locked_department_id
        self._departments: list[Department] = []
        self._candidates: list[Candidate] = []
        self._build_widgets()
        self.refresh()

    def _build_widgets(self) -> None:
        ttk.Label(self, text="Candidatos", style="PageHeading.TLabel").pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(
            self,
            text=(
                "Seguimiento ligero de quién se ha presentado a una vacante (puesto + "
                "departamento) y en qué fase está — sin selector de candidatos complejo."
            ),
            style="Muted.TLabel",
            wraplength=640,
        ).pack(anchor="w", pady=(0, 10))

        filter_row = ttk.Frame(self)
        filter_row.pack(anchor="w", fill="x")
        ttk.Label(filter_row, text="Departamento:").pack(side="left")
        self.department_filter_var = tk.StringVar(value="Todos")
        self.department_filter_combo = ttk.Combobox(
            filter_row,
            state="disabled" if self._locked_department_id is not None else "readonly",
            width=16,
            textvariable=self.department_filter_var,
            values=["Todos"],
        )
        self.department_filter_combo.pack(side="left", padx=(4, 12))
        self.department_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        ttk.Label(filter_row, text="Fase:").pack(side="left")
        self.phase_filter_var = tk.StringVar(value=_ALL_PHASES_LABEL)
        phase_filter_combo = ttk.Combobox(
            filter_row,
            state="readonly",
            width=12,
            textvariable=self.phase_filter_var,
            values=[_ALL_PHASES_LABEL, *validation.CANDIDATE_PHASES],
        )
        phase_filter_combo.pack(side="left", padx=(4, 0))
        phase_filter_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, pady=(10, 0))
        columns = ("nombre", "puesto", "departamento", "fase", "email", "telefono")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        for col, label, width in [
            ("nombre", "Nombre", 150),
            ("puesto", "Puesto", 140),
            ("departamento", "Departamento", 120),
            ("fase", "Fase", 90),
            ("email", "Email", 170),
            ("telefono", "Teléfono", 100),
        ]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self._handle_edit())

        button_row = ttk.Frame(self)
        button_row.pack(fill="x", pady=(10, 0))
        ttk.Button(
            button_row, text="Nuevo candidato...", command=self._handle_new, style="Accent.TButton"
        ).pack(side="left", padx=(0, 6))
        ttk.Button(button_row, text="Editar...", command=self._handle_edit).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(button_row, text="Eliminar", command=self._handle_delete).pack(side="left")

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
        self.department_filter_combo.configure(values=["Todos", *names])
        if self._locked_department_id is not None and visible:
            self.department_filter_var.set(visible[0].name)
        elif self.department_filter_var.get() not in ("Todos", *names):
            self.department_filter_var.set("Todos")

        department_filter_id: int | None = self._locked_department_id
        if department_filter_id is None and self.department_filter_var.get() != "Todos":
            department_filter_id = next(
                (d.id for d in self._departments if d.name == self.department_filter_var.get()),
                None,
            )
        phase_filter = (
            None if self.phase_filter_var.get() == _ALL_PHASES_LABEL else self.phase_filter_var.get()
        )

        self.tree.delete(*self.tree.get_children())
        departments_by_id = {d.id: d for d in self._departments}
        self._candidates = self._repos.candidates.list_all(
            department_id=department_filter_id, phase=phase_filter
        )
        for candidate in self._candidates:
            assert candidate.id is not None
            department = departments_by_id.get(candidate.department_id)
            self.tree.insert(
                "",
                tk.END,
                iid=str(candidate.id),
                values=(
                    candidate.full_name,
                    candidate.position,
                    department.name if department else "?",
                    candidate.phase,
                    candidate.email,
                    candidate.phone,
                ),
            )
        self.status_label.configure(text=f"{len(self._candidates)} candidato(s)")

    def _selected_candidate(self) -> Candidate | None:
        selection = self.tree.selection()
        if not selection:
            return None
        candidate_id = int(selection[0])
        return next((c for c in self._candidates if c.id == candidate_id), None)

    def _handle_new(self) -> None:
        visible = self._visible_departments()
        if not visible:
            messagebox.showinfo(
                "Candidatos", "Cree al menos un departamento antes de añadir un candidato.",
                parent=self,
            )
            return
        CandidateDialog(
            self, self._repos, visible, candidate=None, on_change=self.refresh
        )

    def _handle_edit(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            messagebox.showinfo("Candidatos", "Seleccione un candidato de la lista.", parent=self)
            return
        CandidateDialog(
            self, self._repos, self._visible_departments(), candidate=candidate,
            on_change=self.refresh,
        )

    def _handle_delete(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            messagebox.showinfo("Candidatos", "Seleccione un candidato de la lista.", parent=self)
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", f"¿Eliminar a {candidate.full_name} de la lista de candidatos?",
            parent=self,
        ):
            return
        assert candidate.id is not None
        self._repos.candidates.delete(candidate.id)
        self.refresh()


class CandidateDialog(tk.Toplevel):
    """Crear o editar un candidato -- mismo diálogo para ambos casos, según
    se pase o no un Candidate existente. También es el único sitio donde se
    cambia la fase, a propósito: no hay una acción rápida aparte."""

    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        departments: list[Department],
        candidate: Candidate | None,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Editar candidato" if candidate is not None else "Nuevo candidato")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._departments = departments
        self._candidate_id = candidate.id if candidate is not None else None
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Nombre *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.first_name_var = tk.StringVar(value=candidate.first_name if candidate else "")
        ttk.Entry(frame, textvariable=self.first_name_var, width=26).grid(
            row=0, column=1, padx=6, pady=4
        )

        ttk.Label(frame, text="Apellidos *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.last_name_var = tk.StringVar(value=candidate.last_name if candidate else "")
        ttk.Entry(frame, textvariable=self.last_name_var, width=26).grid(
            row=1, column=1, padx=6, pady=4
        )

        ttk.Label(frame, text="Email *").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.email_var = tk.StringVar(value=candidate.email if candidate else "")
        ttk.Entry(frame, textvariable=self.email_var, width=26).grid(
            row=2, column=1, padx=6, pady=4
        )

        ttk.Label(frame, text="Teléfono").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        self.phone_var = tk.StringVar(value=candidate.phone if candidate else "")
        ttk.Entry(frame, textvariable=self.phone_var, width=26).grid(
            row=3, column=1, padx=6, pady=4
        )

        ttk.Label(frame, text="Puesto (vacante) *").grid(
            row=4, column=0, sticky="w", padx=6, pady=4
        )
        self.position_var = tk.StringVar(value=candidate.position if candidate else "")
        ttk.Entry(frame, textvariable=self.position_var, width=26).grid(
            row=4, column=1, padx=6, pady=4
        )

        ttk.Label(frame, text="Departamento *").grid(row=5, column=0, sticky="w", padx=6, pady=4)
        self.department_combo = ttk.Combobox(
            frame, state="readonly", width=24, values=[d.name for d in self._departments]
        )
        self.department_combo.grid(row=5, column=1, sticky="w", padx=6, pady=4)
        if candidate is not None:
            index = next(
                (i for i, d in enumerate(self._departments) if d.id == candidate.department_id),
                -1,
            )
            if index != -1:
                self.department_combo.current(index)
        elif len(self._departments) == 1:
            self.department_combo.current(0)

        ttk.Label(frame, text="Fase *").grid(row=6, column=0, sticky="w", padx=6, pady=4)
        self.phase_combo = ttk.Combobox(
            frame, state="readonly", width=24, values=list(validation.CANDIDATE_PHASES)
        )
        self.phase_combo.grid(row=6, column=1, sticky="w", padx=6, pady=4)
        self.phase_combo.current(
            validation.CANDIDATE_PHASES.index(candidate.phase) if candidate is not None else 0
        )

        ttk.Label(frame, text="Notas").grid(row=7, column=0, sticky="nw", padx=6, pady=4)
        palette = theme.current()
        self.notes_text = tk.Text(
            frame,
            width=30,
            height=4,
            bg=palette.surface,
            fg=palette.text,
            insertbackground=palette.text,
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.primary_light,
        )
        self.notes_text.grid(row=7, column=1, padx=6, pady=4)
        if candidate is not None:
            self.notes_text.insert("1.0", candidate.notes)

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=8, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=9, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        department_index = self.department_combo.current()
        if department_index == -1:
            self.error_label.configure(text="Seleccione un departamento.")
            return
        phase_index = self.phase_combo.current()
        if phase_index == -1:
            self.error_label.configure(text="Seleccione una fase.")
            return
        department = self._departments[department_index]
        assert department.id is not None
        data = CandidateInput(
            first_name=self.first_name_var.get(),
            last_name=self.last_name_var.get(),
            email=self.email_var.get(),
            phone=self.phone_var.get(),
            position=self.position_var.get(),
            department_id=department.id,
            phase=validation.CANDIDATE_PHASES[phase_index],
            notes=self.notes_text.get("1.0", "end-1c"),
        )
        try:
            if self._candidate_id is None:
                self._repos.candidates.create(data)
            else:
                self._repos.candidates.update(self._candidate_id, data)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()
