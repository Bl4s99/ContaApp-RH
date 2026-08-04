from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app import theme, validation
from app.models import OnboardingTask
from app.repository import Repositories, RepositoryError
from app.window_utils import center_window

TkParent = tk.Tk | tk.Toplevel


class OnboardingTaskManagerDialog(tk.Toplevel):
    """Punto de entrada de 'Tareas de incorporación...' en la barra
    lateral -- catálogo compartido de tareas (contrato firmado, alta en
    Seguridad Social, equipo entregado, accesos creados...); marcar cuáles
    están hechas para un empleado concreto se hace desde su propia ficha,
    no desde aquí. Mismo patrón de selección-para-editar que
    DayTypeManagerDialog, con un único campo (el nombre)."""

    def __init__(self, parent: TkParent, repos: Repositories) -> None:
        super().__init__(parent)
        self.title("Tareas de incorporación")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._tasks: list[OnboardingTask] = []
        self._editing_id: int | None = None

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text=(
                "Catálogo compartido de tareas para el primer día de un\n"
                "empleado nuevo. Se marcan como hechas desde la ficha de\n"
                "cada empleado, en la sección \"Incorporación\"."
            ),
            style="Muted.TLabel",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        palette = theme.current()
        self.listbox = tk.Listbox(
            frame,
            width=40,
            height=8,
            bg=palette.surface,
            fg=palette.text,
            selectbackground=palette.primary,
            selectforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.primary_light,
        )
        self.listbox.grid(row=1, column=0, columnspan=2, padx=4, pady=4)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._load_selected())

        ttk.Label(frame, text="Nombre").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        self.name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.name_var, width=28).grid(
            row=2, column=1, padx=4, pady=2
        )

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, pady=(6, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Nueva tarea", command=self._clear_form).pack(
            side="left", padx=4
        )
        ttk.Button(button_row, text="Eliminar", command=self._handle_delete).pack(
            side="left", padx=4
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=5, column=0, columnspan=2, pady=(8, 0)
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._refresh()

    def _refresh(self) -> None:
        self._tasks = self._repos.onboarding_tasks.list_all()
        self.listbox.delete(0, tk.END)
        for task in self._tasks:
            self.listbox.insert(tk.END, f"  {task.name}")

    def _load_selected(self) -> None:
        selection: tuple[int, ...] = self.listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            return
        task = self._tasks[selection[0]]
        self._editing_id = task.id
        self.name_var.set(task.name)
        self.error_label.configure(text="")

    def _clear_form(self) -> None:
        self._editing_id = None
        self.name_var.set("")
        self.listbox.selection_clear(0, tk.END)
        self.error_label.configure(text="")

    def _handle_save(self) -> None:
        try:
            if self._editing_id is None:
                self._repos.onboarding_tasks.create(self.name_var.get())
            else:
                self._repos.onboarding_tasks.update(self._editing_id, self.name_var.get())
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._clear_form()
        self._refresh()

    def _handle_delete(self) -> None:
        selection: tuple[int, ...] = self.listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            self.error_label.configure(text="Seleccione una tarea para eliminar.")
            return
        task = self._tasks[selection[0]]
        if not messagebox.askyesno(
            "Confirmar eliminación", f"¿Eliminar la tarea '{task.name}'?", parent=self
        ):
            return
        assert task.id is not None
        try:
            self._repos.onboarding_tasks.delete(task.id)
        except RepositoryError as exc:
            self.error_label.configure(text=str(exc))
            return
        self._clear_form()
        self._refresh()
