from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from app import theme, validation
from app.models import CollectiveAgreement, ProfessionalCategory
from app.repository import ProfessionalCategoryInput, Repositories, RepositoryError
from app.window_utils import center_window

TkParent = tk.Tk | tk.Toplevel


def _format_currency(value: float) -> str:
    # Formato español (punto de millar, coma decimal), igual que
    # employee_page._format_currency -- se duplica en vez de importarse
    # porque esa es privada al módulo y esta app no tiene todavía un sitio
    # común de utilidades de formato compartido entre páginas.
    us_formatted = f"{value:,.2f}"
    integer_part, decimal_part = us_formatted.split(".")
    integer_part = integer_part.replace(",", ".")
    return f"{integer_part},{decimal_part} €"


class CollectiveAgreementManagerDialog(tk.Toplevel):
    """Punto de entrada de 'Convenios...' en la barra lateral -- lista de
    convenios colectivos; 'Ver / gestionar categorías...' abre las
    categorías profesionales del convenio seleccionado (ver
    CollectiveAgreementDetailDialog) -- mismo patrón de dos niveles que
    HolidayTemplateManagerDialog/HolidayTemplateDetailDialog. Sin
    on_change externo, igual que DocumentTemplateManagerDialog/
    OnboardingTaskManagerDialog: nada fuera de este diálogo cachea la
    lista de convenios/categorías, la ficha la vuelve a leer entera cada
    vez que se abre un empleado."""

    def __init__(self, parent: TkParent, repos: Repositories) -> None:
        super().__init__(parent)
        self.title("Convenios colectivos")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._agreements: list[CollectiveAgreement] = []

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text="Convenios colectivos: cada uno agrupa sus categorías\n"
            "profesionales, con el salario mínimo que le corresponde a cada\n"
            "una, para poder asignarle después la suya a cada empleado.",
            style="Muted.TLabel",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        palette = theme.current()
        self.listbox = tk.Listbox(
            frame,
            width=54,
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

        button_row = ttk.Frame(frame)
        button_row.grid(row=2, column=0, columnspan=2, pady=(4, 10))
        ttk.Button(
            button_row,
            text="Ver / gestionar categorías...",
            command=self._handle_view,
            style="Accent.TButton",
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Eliminar", command=self._handle_delete).pack(
            side="left", padx=4
        )

        ttk.Separator(frame, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8)
        )

        ttk.Label(frame, text="Nuevo convenio").grid(row=4, column=0, columnspan=2, sticky="w")
        new_row = ttk.Frame(frame)
        new_row.grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.name_var = tk.StringVar()
        ttk.Entry(new_row, textvariable=self.name_var, width=36).pack(side="left")
        ttk.Button(new_row, text="Crear", command=self._handle_create).pack(
            side="left", padx=(6, 0)
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=400)
        self.error_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=7, column=0, columnspan=2, pady=(8, 0)
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._refresh()

    def _refresh(self) -> None:
        self._agreements = self._repos.collective_agreements.list_all()
        self.listbox.delete(0, tk.END)
        for agreement in self._agreements:
            assert agreement.id is not None
            count = len(self._repos.professional_categories.list_for_agreement(agreement.id))
            plural = "categoría" if count == 1 else "categorías"
            self.listbox.insert(tk.END, f"  {agreement.name}  —  {count} {plural}")

    def _selected_agreement(self) -> CollectiveAgreement | None:
        selection: tuple[int, ...] = self.listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            return None
        return self._agreements[selection[0]]

    def _handle_create(self) -> None:
        try:
            self._repos.collective_agreements.create(self.name_var.get())
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self.name_var.set("")
        self.error_label.configure(text="")
        self._refresh()

    def _handle_view(self) -> None:
        agreement = self._selected_agreement()
        if agreement is None:
            self.error_label.configure(text="Seleccione un convenio para ver o gestionar.")
            return
        self.error_label.configure(text="")
        assert agreement.id is not None
        CollectiveAgreementDetailDialog(self, self._repos, agreement.id)
        self._refresh()

    def _handle_delete(self) -> None:
        agreement = self._selected_agreement()
        if agreement is None:
            self.error_label.configure(text="Seleccione un convenio para eliminar.")
            return
        assert agreement.id is not None
        count = len(self._repos.professional_categories.list_for_agreement(agreement.id))
        extra = f" y sus {count} categorías" if count else ""
        if not messagebox.askyesno(
            "Confirmar eliminación",
            f"¿Eliminar el convenio '{agreement.name}'{extra}?\n"
            "Quien tuviera una de esas categorías asignada se queda sin "
            "categoría profesional.",
            parent=self,
        ):
            return
        try:
            self._repos.collective_agreements.delete(agreement.id)
        except RepositoryError as exc:
            self.error_label.configure(text=str(exc))
            return
        self.error_label.configure(text="")
        self._refresh()


class CollectiveAgreementDetailDialog(tk.Toplevel):
    """Ver/gestionar las categorías profesionales de un convenio: crear,
    editar (nombre y salario mínimo) y eliminar. Vuelve a dibujar todo su
    contenido tras cada acción, igual que HolidayTemplateDetailDialog --
    más simple que llevar dos caminos de actualización parcial divergentes."""

    def __init__(self, parent: TkParent, repos: Repositories, agreement_id: int) -> None:
        super().__init__(parent)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._agreement_id = agreement_id
        self._categories: list[ProfessionalCategory] = []

        self._frame = ttk.Frame(self, padding=12)
        self._frame.grid(row=0, column=0, sticky="nsew")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._render()
        center_window(self, parent)

    def _render(self) -> None:
        for widget in self._frame.winfo_children():
            widget.destroy()

        agreement = self._repos.collective_agreements.get(self._agreement_id)
        self.title(f"Convenio — {agreement.name}")
        self._categories = self._repos.professional_categories.list_for_agreement(
            self._agreement_id
        )

        row = 0
        ttk.Label(self._frame, text=agreement.name, style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1

        tree_frame = ttk.Frame(self._frame)
        tree_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.categories_tree = ttk.Treeview(
            tree_frame,
            columns=("nombre", "minimo"),
            show="headings",
            selectmode="browse",
            height=8,
        )
        for col, label, width in [
            ("nombre", "Categoría profesional", 220),
            ("minimo", "Salario mínimo", 130),
        ]:
            self.categories_tree.heading(col, text=label)
            self.categories_tree.column(col, width=width, anchor="w")
        categories_vsb = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.categories_tree.yview
        )
        self.categories_tree.configure(yscrollcommand=categories_vsb.set)
        self.categories_tree.pack(side="left", fill="x", expand=True)
        categories_vsb.pack(side="left", fill="y")
        for category in self._categories:
            assert category.id is not None
            self.categories_tree.insert(
                "",
                tk.END,
                iid=str(category.id),
                values=(category.name, _format_currency(category.minimum_salary)),
            )
        row += 1

        button_row = ttk.Frame(self._frame)
        button_row.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(
            button_row, text="Añadir categoría...", command=self._handle_add
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            button_row, text="Editar categoría...", command=self._handle_edit
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            button_row, text="Eliminar categoría", command=self._handle_delete
        ).pack(side="left")
        row += 1

        self.error_label = ttk.Label(self._frame, text="", style="Error.TLabel", wraplength=380)
        self.error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        row += 1

        ttk.Button(self._frame, text="Cerrar", command=self.destroy).grid(
            row=row, column=0, columnspan=2, pady=(8, 0)
        )

    def _selected_category_id(self) -> int | None:
        selection = self.categories_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_add(self) -> None:
        ProfessionalCategoryFormDialog(
            self, self._repos, self._agreement_id, category=None, on_change=self._render
        )

    def _handle_edit(self) -> None:
        category_id = self._selected_category_id()
        if category_id is None:
            self.error_label.configure(text="Seleccione una categoría para editar.")
            return
        category = self._repos.professional_categories.get(category_id)
        ProfessionalCategoryFormDialog(
            self, self._repos, self._agreement_id, category=category, on_change=self._render
        )

    def _handle_delete(self) -> None:
        category_id = self._selected_category_id()
        if category_id is None:
            self.error_label.configure(text="Seleccione una categoría para eliminar.")
            return
        category = self._repos.professional_categories.get(category_id)
        if not messagebox.askyesno(
            "Confirmar eliminación",
            f"¿Eliminar la categoría '{category.name}'?\n"
            "Quien la tuviera asignada se queda sin categoría profesional.",
            parent=self,
        ):
            return
        try:
            self._repos.professional_categories.delete(category_id)
        except RepositoryError as exc:
            self.error_label.configure(text=str(exc))
            return
        self._render()


class ProfessionalCategoryFormDialog(tk.Toplevel):
    """Crear una categoría profesional nueva, o editar una existente si se
    pasa `category` -- un único formulario para ambos casos, igual que el
    resto de la app evita duplicar un diálogo de creación y otro de edición
    casi idénticos. `on_change` aquí es puramente interno: avisa a su
    propio diálogo padre (CollectiveAgreementDetailDialog) para que se
    vuelva a dibujar, no un callback compartido con el resto de la app."""

    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        agreement_id: int,
        category: ProfessionalCategory | None,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Editar categoría" if category is not None else "Nueva categoría")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._agreement_id = agreement_id
        self._category = category
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        self.name_var = tk.StringVar(value=category.name if category is not None else "")
        self.minimum_salary_var = tk.StringVar(
            value=f"{category.minimum_salary:.2f}" if category is not None else ""
        )

        ttk.Label(frame, text="Nombre").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.name_var, width=30).grid(row=0, column=1, pady=3)
        ttk.Label(frame, text="Salario mínimo anual (€)").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.minimum_salary_var, width=30).grid(
            row=1, column=1, pady=3
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, pady=(8, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        try:
            minimum_salary = float(self.minimum_salary_var.get().strip().replace(",", "."))
        except ValueError:
            self.error_label.configure(text="salario_minimo: debe ser un número")
            return
        data = ProfessionalCategoryInput(
            collective_agreement_id=self._agreement_id,
            name=self.name_var.get(),
            minimum_salary=minimum_salary,
        )
        try:
            if self._category is not None:
                assert self._category.id is not None
                self._repos.professional_categories.update(self._category.id, data)
            else:
                self._repos.professional_categories.create(data)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()
