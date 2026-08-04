from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from app import theme, validation
from app.document_templates import PLACEHOLDER_DESCRIPTIONS
from app.models import DocumentTemplate
from app.repository import Repositories, RepositoryError
from app.window_utils import center_window

TkParent = tk.Tk | tk.Toplevel

_PLACEHOLDER_HELP_TEXT = "  ".join(
    f"{{{name}}}" for name in PLACEHOLDER_DESCRIPTIONS
)


class DocumentTemplateManagerDialog(tk.Toplevel):
    """Punto de entrada de 'Plantillas de documentos...' en la barra
    lateral -- lista de plantillas reutilizables (oferta, contrato, carta
    de baja...); generar un documento a partir de una se hace desde la
    propia ficha del empleado (ver GenerateDocumentDialog en
    employee_page.py), no desde aquí."""

    def __init__(self, parent: TkParent, repos: Repositories) -> None:
        super().__init__(parent)
        self.title("Plantillas de documentos")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._templates: list[DocumentTemplate] = []

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text=(
                "Texto base reutilizable para documentos (oferta, contrato, carta de\n"
                "baja...) con marcadores que se rellenan con los datos del empleado al\n"
                "generar el documento desde su ficha."
            ),
            style="Muted.TLabel",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        palette = theme.current()
        self.listbox = tk.Listbox(
            frame,
            width=50,
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
        button_row.grid(row=2, column=0, columnspan=2, pady=(4, 0))
        ttk.Button(
            button_row, text="Nueva plantilla...", command=self._handle_new, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Editar...", command=self._handle_edit).pack(
            side="left", padx=4
        )
        ttk.Button(button_row, text="Eliminar", command=self._handle_delete).pack(
            side="left", padx=4
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=380)
        self.error_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Button(frame, text="Cerrar", command=self.destroy).grid(
            row=4, column=0, columnspan=2, pady=(8, 0)
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._refresh()

    def _refresh(self) -> None:
        self._templates = self._repos.document_templates.list_all()
        self.listbox.delete(0, tk.END)
        for template in self._templates:
            created = template.created_at.strftime("%d/%m/%Y")
            self.listbox.insert(tk.END, f"  {template.name}  (creada {created})")

    def _selected_template(self) -> DocumentTemplate | None:
        selection: tuple[int, ...] = self.listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            return None
        return self._templates[selection[0]]

    def _handle_new(self) -> None:
        self.error_label.configure(text="")
        DocumentTemplateEditorDialog(self, self._repos, template=None, on_change=self._refresh)

    def _handle_edit(self) -> None:
        template = self._selected_template()
        if template is None:
            self.error_label.configure(text="Seleccione una plantilla para editar.")
            return
        self.error_label.configure(text="")
        DocumentTemplateEditorDialog(
            self, self._repos, template=template, on_change=self._refresh
        )

    def _handle_delete(self) -> None:
        template = self._selected_template()
        if template is None:
            self.error_label.configure(text="Seleccione una plantilla para eliminar.")
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", f"¿Eliminar la plantilla '{template.name}'?", parent=self
        ):
            return
        assert template.id is not None
        try:
            self._repos.document_templates.delete(template.id)
        except RepositoryError as exc:
            self.error_label.configure(text=str(exc))
            return
        self.error_label.configure(text="")
        self._refresh()


class DocumentTemplateEditorDialog(tk.Toplevel):
    """Crear o editar una plantilla -- mismo diálogo para ambos casos,
    según se pase o no un DocumentTemplate existente."""

    def __init__(
        self,
        parent: TkParent,
        repos: Repositories,
        template: DocumentTemplate | None,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Editar plantilla" if template is not None else "Nueva plantilla")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._repos = repos
        self._template_id = template.id if template is not None else None
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Nombre *").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=template.name if template is not None else "")
        ttk.Entry(frame, textvariable=self.name_var, width=50).grid(
            row=1, column=0, sticky="ew", pady=(2, 8)
        )

        ttk.Label(frame, text="Marcadores disponibles (se sustituyen al generar):").grid(
            row=2, column=0, sticky="w"
        )
        ttk.Label(
            frame,
            text=_PLACEHOLDER_HELP_TEXT,
            style="Muted.TLabel",
            wraplength=460,
            justify="left",
        ).grid(row=3, column=0, sticky="w", pady=(2, 8))

        ttk.Label(frame, text="Texto de la plantilla *").grid(row=4, column=0, sticky="w")
        palette = theme.current()
        self.body_text = tk.Text(
            frame,
            width=60,
            height=16,
            bg=palette.surface,
            fg=palette.text,
            insertbackground=palette.text,
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.primary_light,
        )
        self.body_text.grid(row=5, column=0, sticky="ew", pady=(2, 8))
        if template is not None:
            self.body_text.insert("1.0", template.body)

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=460)
        self.error_label.grid(row=6, column=0, sticky="w")

        button_row = ttk.Frame(frame)
        button_row.grid(row=7, column=0, sticky="w", pady=(8, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        name = self.name_var.get()
        body = self.body_text.get("1.0", "end-1c")
        try:
            if self._template_id is None:
                self._repos.document_templates.create(name, body)
            else:
                self._repos.document_templates.update(self._template_id, name, body)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()
