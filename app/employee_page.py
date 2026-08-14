from __future__ import annotations

import os as os
import tempfile as tempfile
import tkinter as tk
from collections.abc import Callable
from datetime import date, datetime
from functools import partial
from pathlib import Path
from tkinter import filedialog as filedialog
from tkinter import messagebox, ttk

from app import theme, validation, vacation
from app.calendar_widget import DateEntry, ScrollableFrame
from app.data_export import export_employee_data
from app.document_pdf import build_document_pdf
from app.incapacidad_temporal import calculate_it_payment_breakdown
from app.models import (
    AssignedEquipment,
    CollectiveAgreement,
    Department,
    DocumentTemplate,
    Employee,
    Objective,
    ProfessionalCategory,
    SeveranceSettlement,
    Shift,
)
from app.pdf_common import CompanyInfo
from app.photo_utils import (
    SUPPORTED_FILE_TYPES,
    PhotoProcessingError,
    photo_to_tk_image,
    placeholder_tk_image,
    process_uploaded_photo,
)
from app.repository import (
    AUDIT_DATA_EXPORTED,
    AUDIT_DOCUMENT_DELETED,
    AUDIT_EMPLOYEE_ANONYMIZED,
    AUDIT_EMPLOYEE_CREATED,
    AUDIT_EMPLOYEE_DELETED,
    AUDIT_EMPLOYEE_REACTIVATED,
    AUDIT_EMPLOYEE_TERMINATED,
    AUDIT_EQUIPMENT_DELETED,
    AUDIT_IT_EPISODE_DELETED,
    AUDIT_OBJECTIVE_DELETED,
    AUDIT_PERFORMANCE_REVIEW_DELETED,
    AUDIT_SELF_SERVICE_PIN_CLEARED,
    AUDIT_SELF_SERVICE_PIN_SET,
    AUDIT_TRAINING_DELETED,
    AUDIT_WORK_ACCIDENT_DELETED,
    EmployeeInput,
    Repositories,
    RepositoryError,
)
from app.severance import SeveranceCalculation, calculate_severance
from app.window_utils import center_window

_NO_SHIFT_LABEL = "— Sin turno asignado —"
_NO_MANAGER_LABEL = "— Sin supervisor asignado —"
_NO_PROFESSIONAL_CATEGORY_LABEL = "— Sin categoría profesional —"
_STATUS_LABELS = {True: "Activo", False: "Inactivo"}
_ACTIVE_FILTER_OPTIONS = ["Todos", "Activos", "Inactivos"]
PHOTO_DISPLAY_SIZE = (120, 120)

_COLUMNS: list[tuple[str, str, int]] = [
    ("nombre", "Nombre", 130),
    ("puesto", "Puesto", 110),
    # "Departamento" (90px) no cabía ni siquiera con la propia cabecera
    # más la flecha de orden -- se veía recortada a "Departamentc", como
    # una errata real en vez de una columna apretada.
    ("departamento", "Departamento", 125),
    ("salario", "Salario anual", 100),
    ("antiguedad", "Antigüedad", 90),
    ("estado", "Estado", 60),
]
_SORT_ARROW_ASC = " ▲"
_SORT_ARROW_DESC = " ▼"


def _format_currency(value: float) -> str:
    # Formato español (punto de millar, coma decimal) sin depender del
    # módulo locale, que es global al proceso y no debe tocarse por esto.
    us_formatted = f"{value:,.2f}"
    integer_part, decimal_part = us_formatted.split(".")
    integer_part = integer_part.replace(",", ".")
    return f"{integer_part},{decimal_part} €"


def _format_seniority(hire_date: date, today: date) -> str:
    total_months = (today.year - hire_date.year) * 12 + (today.month - hire_date.month)
    if today.day < hire_date.day:
        total_months -= 1
    total_months = max(total_months, 0)
    years, months = divmod(total_months, 12)
    if years > 0 and months > 0:
        return f"{years} {'año' if years == 1 else 'años'}, {months} {'mes' if months == 1 else 'meses'}"
    if years > 0:
        return f"{years} {'año' if years == 1 else 'años'}"
    if months > 0:
        return f"{months} {'mes' if months == 1 else 'meses'}"
    return "Menos de 1 mes"


def _format_file_size(size_bytes: int) -> str:
    size = float(size_bytes)
    if size < 1024:
        return f"{size:.0f} B"
    size /= 1024
    if size < 1024:
        return f"{size:.1f} KB"
    size /= 1024
    return f"{size:.1f} MB"


class VacationSettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, repos: Repositories, on_change: Callable[[], None]) -> None:
        super().__init__(parent)
        self.title("Configurar días de vacaciones")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._on_change = on_change
        current_days = repos.app_settings.get_annual_vacation_days()

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Días de vacaciones al año").grid(
            row=0, column=0, sticky="w", padx=6, pady=4
        )
        self.days_var = tk.StringVar(value=f"{current_days:g}")
        ttk.Entry(frame, textvariable=self.days_var, width=10).grid(
            row=0, column=1, sticky="w", padx=6, pady=4
        )

        ttk.Label(
            frame,
            text="Se aplica a todos los empleados por igual; el primer año se\nprorratea por meses completos trabajados.",
            style="Muted.TLabel",
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 4))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        try:
            days = float(self.days_var.get().strip().replace(",", "."))
        except ValueError:
            self.error_label.configure(text="Debe ser un número, por ejemplo 22 o 22.5")
            return
        try:
            self._repos.app_settings.set_annual_vacation_days(days)
        except validation.ValidationError as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class DocumentUploadDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee_id: int,
        filename: str,
        content: bytes,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Adjuntar documento")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee_id = employee_id
        self._filename = filename
        self._content = content
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Archivo").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(frame, text=filename, style="Muted.TLabel").grid(
            row=0, column=1, sticky="w", padx=6, pady=4
        )

        ttk.Label(frame, text="Categoría *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.category_combo = ttk.Combobox(
            frame, state="readonly", width=20, values=list(validation.DOCUMENT_CATEGORIES)
        )
        self.category_combo.current(0)
        self.category_combo.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Adjuntar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        try:
            self._repos.documents.upload(
                self._employee_id, self._filename, self.category_combo.get(), self._content
            )
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class GenerateDocumentDialog(tk.Toplevel):
    """Generar un documento (oferta, contrato, carta de baja...) a partir de
    una plantilla y los datos reales del empleado -- ver
    app/document_templates.py para la sustitución de {marcadores} y
    app/document_pdf.py para la maquetación en PDF. El texto de la vista
    previa es editable antes de generar el PDF final. Guardar como adjunto
    reutiliza el mismo camino que 'Adjuntar documento...' (no genera ningún
    registro propio aparte); descargar/imprimir no tocan el almacenamiento
    de documentos del empleado en absoluto, igual que en Nóminas."""

    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        templates: list[DocumentTemplate],
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Generar documento — {employee.full_name}")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee = employee
        self._templates = templates
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Plantilla *").grid(row=0, column=0, sticky="w")
        self.template_combo = ttk.Combobox(
            frame, state="readonly", width=40, values=[t.name for t in self._templates]
        )
        self.template_combo.grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.template_combo.bind("<<ComboboxSelected>>", lambda _e: self._handle_render())

        palette = theme.current()
        self.preview_text = tk.Text(
            frame,
            width=70,
            height=18,
            bg=palette.surface,
            fg=palette.text,
            insertbackground=palette.text,
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.primary_light,
        )
        self.preview_text.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 4))

        ttk.Label(
            frame,
            text="Texto base editable -- revíselo antes de guardarlo o copiarlo.",
            style="Muted.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w")

        save_row = ttk.Frame(frame)
        save_row.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(save_row, text="Categoría al guardar").pack(side="left")
        self.category_combo = ttk.Combobox(
            save_row, state="readonly", width=16, values=list(validation.DOCUMENT_CATEGORIES)
        )
        self.category_combo.current(0)
        self.category_combo.pack(side="left", padx=(6, 0))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=460)
        self.error_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Cada botón en su propia fila, no varios en horizontal -- mismo
        # criterio ya usado en el resto de la ficha (ver payroll_ui.py):
        # empaquetar varios botones de acción uno junto a otro se recorta en
        # ventanas/DPI más pequeños.
        button_row = ttk.Frame(frame)
        button_row.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(
            button_row,
            text="Guardar como documento adjunto (PDF)",
            command=self._handle_save_as_document,
            style="Accent.TButton",
        ).pack(side="top", anchor="w", pady=(0, 2))
        ttk.Button(
            button_row, text="Descargar PDF...", command=self._handle_download_pdf
        ).pack(side="top", anchor="w", pady=(0, 2))
        ttk.Button(
            button_row, text="Imprimir", command=self._handle_print_pdf
        ).pack(side="top", anchor="w", pady=(0, 2))
        ttk.Button(
            button_row, text="Copiar al portapapeles", command=self._handle_copy
        ).pack(side="top", anchor="w", pady=(0, 2))
        ttk.Button(button_row, text="Cerrar", command=self.destroy).pack(
            side="top", anchor="w"
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        if self._templates:
            self.template_combo.current(0)
            self._handle_render()

    def _selected_template(self) -> DocumentTemplate | None:
        index = self.template_combo.current()
        if index == -1:
            return None
        return self._templates[index]

    def _handle_render(self) -> None:
        template = self._selected_template()
        if template is None or template.id is None or self._employee.id is None:
            return
        rendered = self._repos.document_templates.render_for_employee(
            template.id, self._employee.id
        )
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", rendered)
        self.error_label.configure(text="")

    def _handle_copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.preview_text.get("1.0", "end-1c"))

    def _build_document_pdf_bytes(self) -> tuple[DocumentTemplate, bytes] | None:
        template = self._selected_template()
        if template is None:
            self.error_label.configure(text="Seleccione una plantilla.")
            return None
        company = CompanyInfo(
            name=self._repos.app_settings.get_company_name(),
            nif=self._repos.app_settings.get_company_nif(),
            ccc=self._repos.app_settings.get_company_ccc(),
            address=self._repos.app_settings.get_company_address(),
        )
        pdf_bytes = build_document_pdf(
            document_title=template.name,
            employee_name=self._employee.full_name,
            body_text=self.preview_text.get("1.0", "end-1c"),
            company=company,
            generated_at=date.today(),
        )
        return template, pdf_bytes

    def _handle_save_as_document(self) -> None:
        result = self._build_document_pdf_bytes()
        if result is None:
            return
        template, pdf_bytes = result
        filename = f"{template.name} - {self._employee.full_name}.pdf"
        assert self._employee.id is not None
        try:
            self._repos.documents.upload(
                self._employee.id, filename, self.category_combo.get(), pdf_bytes
            )
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        messagebox.showinfo(
            "Generar documento", "Documento guardado en Documentos.", parent=self
        )
        self.destroy()

    def _handle_download_pdf(self) -> None:
        result = self._build_document_pdf_bytes()
        if result is None:
            return
        template, pdf_bytes = result
        path_str = filedialog.asksaveasfilename(
            title="Guardar documento en PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile=f"{template.name} - {self._employee.full_name}.pdf",
            parent=self,
        )
        if not path_str:
            return
        try:
            Path(path_str).write_bytes(pdf_bytes)
        except OSError as exc:
            messagebox.showerror("Descargar PDF", str(exc), parent=self)
            return
        messagebox.showinfo("Descargar PDF", "PDF generado correctamente.", parent=self)

    def _handle_print_pdf(self) -> None:
        result = self._build_document_pdf_bytes()
        if result is None:
            return
        template, pdf_bytes = result
        directory = Path(tempfile.gettempdir()) / "contaapp_rh_print"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            _cleanup_stale_print_files(directory)
            temp_path = directory / (
                f"{template.name}_{self._employee.full_name.replace(' ', '_')}_"
                f"{datetime.now():%H%M%S%f}.pdf"
            )
            temp_path.write_bytes(pdf_bytes)
        except OSError as exc:
            messagebox.showerror("Imprimir", str(exc), parent=self)
            return
        try:
            os.startfile(temp_path, "print")
        except OSError as exc:
            messagebox.showerror(
                "Imprimir",
                "No se pudo imprimir. Puede que no haya ninguna aplicación configurada "
                f"para abrir archivos PDF en este equipo.\n\nDetalle técnico: {exc}",
                parent=self,
            )
            return
        messagebox.showinfo("Imprimir", "El documento se ha enviado a imprimir.", parent=self)


def _cleanup_stale_print_files(directory: Path, max_age_seconds: float = 3600) -> None:
    # Duplicado de payroll_ui.py a propósito, no importado -- evita que un
    # módulo de UI dependa de los internos de otro. Los documentos generados
    # aquí pueden contener DNI/domicilio, igual que las nóminas, así que no
    # deben acumularse indefinidamente en el temporal compartido del sistema.
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    cutoff = datetime.now().timestamp() - max_age_seconds
    for entry in entries:
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


class WorkAccidentDialog(tk.Toplevel):
    """Registro mínimo de un accidente de trabajo (PRL básico): fecha,
    gravedad, descripción, y si causó baja médica / se notificó a la
    autoridad laboral -- no una herramienta de evaluación de riesgos, solo
    constancia de que ocurrió y de qué pasos básicos se han cumplido."""

    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Registrar accidente — {employee.full_name}")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee = employee
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Fecha del accidente *").grid(
            row=0, column=0, sticky="w", padx=6, pady=4
        )
        # Un empleado ya de baja no puede tener un accidente registrado con
        # fecha posterior a su propia baja -- el valor inicial también se
        # acota, no solo el límite del selector, para que nunca arranque
        # mostrando "hoy" si eso ya cae después de la baja.
        initial_accident_date = (
            min(date.today(), employee.termination_date)
            if employee.termination_date is not None
            else None
        )
        self.date_entry = DateEntry(
            frame,
            initial=initial_accident_date,
            min_date=employee.hire_date,
            max_date=employee.termination_date,
        )
        self.date_entry.grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Gravedad *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.severity_combo = ttk.Combobox(
            frame, state="readonly", width=20, values=list(validation.WORK_ACCIDENT_SEVERITIES)
        )
        self.severity_combo.current(0)
        self.severity_combo.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Descripción *").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.description_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.description_var, width=36).grid(
            row=2, column=1, sticky="w", padx=6, pady=4
        )

        self.caused_leave_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="Causó baja médica", variable=self.caused_leave_var
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=(4, 0))

        self.reported_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="Notificado a la autoridad laboral", variable=self.reported_var
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 4))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=5, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=6, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Registrar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        assert self._employee.id is not None
        try:
            accident_date = validation.validate_work_accident_date(
                self.date_entry.get(), self._employee.hire_date, self._employee.termination_date
            )
            severity = validation.validate_work_accident_severity(self.severity_combo.get())
            description = validation.validate_required_text(
                self.description_var.get(), "descripción"
            )
            self._repos.work_accidents.create(
                self._employee.id,
                accident_date,
                severity,
                description,
                self.caused_leave_var.get(),
                self.reported_var.get(),
            )
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class ITEpisodeDialog(tk.Toplevel):
    """Registra el parte de baja de un nuevo episodio de incapacidad
    temporal -- la confirmación y el alta se añaden después, sobre el
    episodio ya creado, desde ITEpisodeDetailDialog (no se piden aquí:
    al dar de baja normalmente no se sabe todavía si habrá confirmaciones
    ni cuándo llegará el alta)."""

    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Registrar baja por IT — {employee.full_name}")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee = employee
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Contingencia *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.contingency_combo = ttk.Combobox(
            frame, state="readonly", width=22, values=list(validation.IT_CONTINGENCIES)
        )
        self.contingency_combo.current(0)
        self.contingency_combo.grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Fecha de baja *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        # Mismo motivo que en WorkAccidentDialog: un empleado ya de baja no
        # puede abrir un episodio de IT con fecha posterior a su propia baja.
        initial_leave_date = (
            min(date.today(), employee.termination_date)
            if employee.termination_date is not None
            else None
        )
        self.leave_date_entry = DateEntry(
            frame,
            initial=initial_leave_date,
            min_date=employee.hire_date,
            max_date=employee.termination_date,
        )
        self.leave_date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Registrar baja", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        assert self._employee.id is not None
        try:
            leave_date = validation.validate_it_leave_date(
                self.leave_date_entry.get(), self._employee.hire_date, self._employee.termination_date
            )
            contingency = validation.validate_it_contingency(self.contingency_combo.get())
            self._repos.it_episodes.create(self._employee.id, contingency, leave_date)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class ITEpisodeDetailDialog(tk.Toplevel):
    """Ver y gestionar un episodio de IT ya registrado: añadir una
    confirmación, dar de alta, y ver el desglose de quién paga qué parte
    del salario (ver app/incapacidad_temporal.py) -- calculado hasta hoy
    si el episodio sigue abierto, o hasta la fecha de alta si ya se
    cerró."""

    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        episode_id: int,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee = employee
        self._episode_id = episode_id
        self._on_change = on_change

        self._frame = ttk.Frame(self, padding=12)
        self._frame.grid(row=0, column=0, sticky="nsew")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._render()
        center_window(self, parent)

    def _render(self) -> None:
        for child in self._frame.winfo_children():
            child.destroy()
        episode = self._repos.it_episodes.get(self._episode_id)
        self.title(f"Incapacidad temporal — {self._employee.full_name}")

        info_rows = [
            ("Contingencia", episode.contingency),
            ("Fecha de baja", episode.leave_date.strftime("%d/%m/%Y")),
            (
                "Última confirmación",
                episode.last_confirmation_date.strftime("%d/%m/%Y")
                if episode.last_confirmation_date
                else "Ninguna",
            ),
            (
                "Fecha de alta",
                episode.return_date.strftime("%d/%m/%Y") if episode.return_date else "En curso",
            ),
        ]
        for row_index, (label, value) in enumerate(info_rows):
            ttk.Label(self._frame, text=label, style="Muted.TLabel").grid(
                row=row_index, column=0, sticky="w", padx=6, pady=3
            )
            ttk.Label(self._frame, text=value).grid(
                row=row_index, column=1, sticky="w", padx=6, pady=3
            )
        row = len(info_rows)

        if episode.is_open:
            ttk.Separator(self._frame, orient="horizontal").grid(
                row=row, column=0, columnspan=2, sticky="ew", pady=8
            )
            row += 1
            confirm_row = ttk.Frame(self._frame)
            confirm_row.grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
            self.confirmation_entry = DateEntry(confirm_row, min_date=episode.leave_date)
            self.confirmation_entry.pack(side="left")
            ttk.Button(
                confirm_row, text="Añadir confirmación", command=self._handle_confirm
            ).pack(side="left", padx=(6, 0))
            row += 1

            return_row = ttk.Frame(self._frame)
            return_row.grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
            self.return_entry = DateEntry(return_row, min_date=episode.leave_date)
            self.return_entry.pack(side="left")
            ttk.Button(return_row, text="Dar de alta", command=self._handle_close).pack(
                side="left", padx=(6, 0)
            )
            row += 1

        self.error_label = ttk.Label(self._frame, text="", style="Error.TLabel", wraplength=340)
        self.error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 6))
        row += 1

        ttk.Separator(self._frame, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=8
        )
        row += 1
        ttk.Label(
            self._frame, text="Desglose de pago (estimado)", style="PageHeading.TLabel"
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1

        as_of = episode.return_date or date.today()
        breakdown = calculate_it_payment_breakdown(
            episode.contingency, episode.leave_date, as_of, self._employee.salary
        )
        breakdown_tree = ttk.Treeview(
            self._frame,
            columns=("pagador", "porcentaje", "dias", "importe"),
            show="headings",
            selectmode="none",
            height=len(breakdown.rows) or 1,
        )
        for col, label, width in [
            ("pagador", "Quién paga", 170),
            ("porcentaje", "%", 50),
            ("dias", "Días", 50),
            ("importe", "Importe", 90),
        ]:
            breakdown_tree.heading(col, text=label)
            breakdown_tree.column(col, width=width, anchor="w")
        for breakdown_row in breakdown.rows:
            breakdown_tree.insert(
                "",
                tk.END,
                values=(
                    breakdown_row.payer,
                    f"{breakdown_row.percentage:g}%",
                    breakdown_row.days,
                    _format_currency(breakdown_row.amount),
                ),
            )
        breakdown_tree.grid(row=row, column=0, columnspan=2, sticky="ew")
        row += 1

        ttk.Label(
            self._frame,
            text=f"Total: {breakdown.total_days} día(s) — {_format_currency(breakdown.total_amount)}",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        ttk.Label(
            self._frame,
            text=(
                "Estimación orientativa (base reguladora aproximada a partir del salario "
                "bruto anual) — no sustituye el cálculo oficial de la mutua/Seguridad Social."
            ),
            style="Muted.TLabel",
            wraplength=340,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        row += 1

        button_row = ttk.Frame(self._frame)
        button_row.grid(row=row, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Eliminar episodio", command=self._handle_delete
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cerrar", command=self.destroy).pack(side="left", padx=4)

    def _handle_confirm(self) -> None:
        episode = self._repos.it_episodes.get(self._episode_id)
        try:
            confirmation_date = validation.validate_it_confirmation_date(
                self.confirmation_entry.get(), episode.leave_date, episode.last_confirmation_date
            )
            if confirmation_date is None:
                raise validation.ValidationError("fecha_confirmacion_it", "obligatoria")
            self._repos.it_episodes.set_confirmation(self._episode_id, confirmation_date)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self._render()

    def _handle_close(self) -> None:
        episode = self._repos.it_episodes.get(self._episode_id)
        try:
            return_date = validation.validate_it_return_date(
                self.return_entry.get(), episode.leave_date, episode.last_confirmation_date
            )
            if return_date is None:
                raise validation.ValidationError("fecha_alta_it", "obligatoria")
            self._repos.it_episodes.close(self._episode_id, return_date)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self._render()
        center_window(self, self.master)

    def _handle_delete(self) -> None:
        if not messagebox.askyesno(
            "Confirmar eliminación", "¿Eliminar este episodio de incapacidad temporal?", parent=self
        ):
            return
        self._repos.it_episodes.delete(self._episode_id)
        self._repos.audit_log.record(
            AUDIT_IT_EPISODE_DELETED, f"Empleado: {self._employee.full_name}"
        )
        self._on_change()
        self.destroy()


class TerminationDialog(tk.Toplevel):
    """Da de baja a un empleado: pide motivo y fecha, muestra una vista
    previa del finiquito en vivo (misma idea que la estimación en vivo de
    Nóminas) que se recalcula al cambiar cualquiera de los dos campos, y al
    confirmar hace las dos cosas juntas -- da de baja y guarda el finiquito
    calculado -- para que nunca quede una baja registrada sin su finiquito
    o viceversa."""

    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        on_change: Callable[[int], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Dar de baja — {employee.full_name}")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee = employee
        self._on_change = on_change
        self._last_calculation: SeveranceCalculation | None = None

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Motivo *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.reason_combo = ttk.Combobox(
            frame, state="readonly", width=26, values=list(validation.TERMINATION_REASONS)
        )
        self.reason_combo.current(0)
        self.reason_combo.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        self.reason_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_preview())

        ttk.Label(frame, text="Fecha de baja *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.date_entry = DateEntry(frame, min_date=employee.hire_date)
        self.date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)
        self.date_entry.value_var.trace_add("write", lambda *_a: self._refresh_preview())

        ttk.Separator(frame, orient="horizontal").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=8
        )

        ttk.Label(frame, text="Finiquito (vista previa)", style="PageHeading.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w"
        )
        self.vacation_preview_label = ttk.Label(frame, text="")
        self.vacation_preview_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=2)
        self.extra_preview_label = ttk.Label(frame, text="")
        self.extra_preview_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=2)
        self.total_preview_label = ttk.Label(frame, text="", font=("TkDefaultFont", 10, "bold"))
        self.total_preview_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 2))

        ttk.Label(
            frame,
            text=(
                "No incluye el salario del mes en curso (genera esa nómina aparte)\n"
                "ni ninguna indemnización por despido."
            ),
            style="Muted.TLabel",
            justify="left",
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 4))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=340)
        self.error_label.grid(row=8, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=9, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Confirmar baja", command=self._handle_confirm, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self.error_label.configure(text="")
        try:
            termination_date = date.fromisoformat(self.date_entry.get())
        except ValueError:
            self._last_calculation = None
            return
        if termination_date < self._employee.hire_date:
            self._last_calculation = None
            self.vacation_preview_label.configure(text="")
            self.extra_preview_label.configure(text="")
            self.total_preview_label.configure(
                text="La fecha de baja no puede ser anterior a la de ingreso."
            )
            return

        assert self._employee.id is not None
        annual_vacation_days = self._repos.app_settings.get_annual_vacation_days()
        used_days = self._repos.absences.count_vacation_days_for_year(
            self._employee.id, termination_date.year
        )
        calculation = calculate_severance(
            hire_date=self._employee.hire_date,
            termination_date=termination_date,
            annual_gross_salary=self._employee.salary,
            annual_vacation_days=annual_vacation_days,
            vacation_days_used_this_year=used_days,
        )
        self._last_calculation = calculation

        self.vacation_preview_label.configure(
            text=(
                f"Vacaciones no disfrutadas: {calculation.vacation_days_pending:g} días → "
                f"{_format_currency(calculation.vacation_amount)}"
            )
        )
        self.extra_preview_label.configure(
            text=(
                f"Parte proporcional de paga extra: {calculation.extra_payment_months_accrued} "
                f"meses → {_format_currency(calculation.extra_payment_amount)}"
            )
        )
        self.total_preview_label.configure(
            text=f"Total finiquito: {_format_currency(calculation.total_amount)}"
        )

    def _handle_confirm(self) -> None:
        assert self._employee.id is not None
        reason = self.reason_combo.get()
        date_str = self.date_entry.get()
        try:
            self._repos.employees.terminate(self._employee.id, date_str, reason)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._repos.audit_log.record(
            AUDIT_EMPLOYEE_TERMINATED,
            f"Empleado: {self._employee.full_name} — Motivo: {reason} — Fecha: {date_str}",
        )

        if self._last_calculation is not None:
            termination_date = date.fromisoformat(date_str)
            annual_vacation_days = self._repos.app_settings.get_annual_vacation_days()
            used_days = self._repos.absences.count_vacation_days_for_year(
                self._employee.id, termination_date.year
            )
            self._repos.severance_settlements.create(
                employee_id=self._employee.id,
                termination_date=termination_date,
                termination_reason=reason,
                hire_date=self._employee.hire_date,
                annual_gross_salary=self._employee.salary,
                annual_vacation_days=annual_vacation_days,
                vacation_days_used_this_year=used_days,
                calculation=self._last_calculation,
            )

        self._on_change(self._employee.id)
        self.destroy()


class TrainingDialog(tk.Toplevel):
    """Registrar un curso de formación o una certificación -- una única
    entidad para ambos (ver EmployeeTraining), con la fecha de caducidad
    como el único campo opcional: un curso puntual no caduca, una
    certificación (carné, idioma, técnica) normalmente sí."""

    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Añadir formación — {employee.full_name}")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee = employee
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Nombre *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.name_var, width=36).grid(
            row=0, column=1, sticky="w", padx=6, pady=4
        )

        ttk.Label(frame, text="Fecha de finalización *").grid(
            row=1, column=0, sticky="w", padx=6, pady=4
        )
        self.completion_date_entry = DateEntry(frame, max_date=date.today())
        self.completion_date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Fecha de caducidad").grid(
            row=2, column=0, sticky="w", padx=6, pady=4
        )
        expiration_row = ttk.Frame(frame)
        expiration_row.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        self.expiration_date_entry = DateEntry(expiration_row)
        self.expiration_date_entry.pack(side="left")
        self.no_expiration_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            expiration_row,
            text="No caduca",
            variable=self.no_expiration_var,
            command=self._handle_no_expiration_toggled,
        ).pack(side="left", padx=(8, 0))
        self._handle_no_expiration_toggled()

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=3, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=4, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_no_expiration_toggled(self) -> None:
        self.expiration_date_entry.set_enabled(not self.no_expiration_var.get())

    def _handle_save(self) -> None:
        assert self._employee.id is not None
        try:
            completion_date = validation.validate_training_completion_date(
                self.completion_date_entry.get()
            )
            name = validation.validate_required_text(self.name_var.get(), "nombre")
            expiration_date = (
                None
                if self.no_expiration_var.get()
                else validation.validate_training_expiration_date(
                    self.expiration_date_entry.get(), completion_date
                )
            )
            self._repos.trainings.create(
                self._employee.id, name, completion_date, expiration_date
            )
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


_OBJECTIVE_STATUS_LABELS = {
    "pendiente": "Pendiente", "cumplido": "Cumplido", "no_cumplido": "No cumplido",
}
_OBJECTIVE_STATUS_BY_LABEL = {label: key for key, label in _OBJECTIVE_STATUS_LABELS.items()}


class ObjectiveDialog(tk.Toplevel):
    """Registrar un objetivo de desempeño nuevo -- siempre nace en estado
    'pendiente' (ver ObjectiveRepository.create()); cambiar el estado más
    adelante es una acción propia (ChangeObjectiveStatusDialog), no algo
    que se edite aquí."""

    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Nuevo objetivo — {employee.full_name}")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee = employee
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Título *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.title_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.title_var, width=34).grid(
            row=0, column=1, padx=6, pady=4
        )

        ttk.Label(frame, text="Fecha objetivo *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.target_date_entry = DateEntry(frame)
        self.target_date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Notas").grid(row=2, column=0, sticky="nw", padx=6, pady=4)
        self.notes_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.notes_var, width=34).grid(
            row=2, column=1, padx=6, pady=4
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=3, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=4, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        assert self._employee.id is not None
        try:
            target_date = validation.validate_objective_target_date(self.target_date_entry.get())
            title = validation.validate_required_text(self.title_var.get(), "titulo")
            self._repos.objectives.create(
                self._employee.id, title, target_date, self.notes_var.get()
            )
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class ChangeObjectiveStatusDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        objective: Objective,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Cambiar estado del objetivo")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._objective = objective
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text=objective.title, style="PageHeading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )
        ttk.Label(frame, text="Estado").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.status_combo = ttk.Combobox(
            frame, state="readonly", width=20,
            values=list(_OBJECTIVE_STATUS_LABELS.values()),
        )
        self.status_combo.set(_OBJECTIVE_STATUS_LABELS[objective.status])
        self.status_combo.grid(row=1, column=1, padx=6, pady=4)

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=280)
        self.error_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        assert self._objective.id is not None
        status = _OBJECTIVE_STATUS_BY_LABEL[self.status_combo.get()]
        try:
            self._repos.objectives.update_status(self._objective.id, status)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class PerformanceReviewDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Nueva evaluación — {employee.full_name}")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee = employee
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Fecha *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.review_date_entry = DateEntry(frame, max_date=date.today())
        self.review_date_entry.grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Comentarios *").grid(row=1, column=0, sticky="nw", padx=6, pady=4)
        palette = theme.current()
        self.comments_text = tk.Text(
            frame,
            width=34,
            height=6,
            bg=palette.surface,
            fg=palette.text,
            insertbackground=palette.text,
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.primary_light,
        )
        self.comments_text.grid(row=1, column=1, padx=6, pady=4)

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        assert self._employee.id is not None
        try:
            review_date = validation.validate_review_date(self.review_date_entry.get())
            comments = validation.validate_required_text(
                self.comments_text.get("1.0", "end").strip(), "comentarios"
            )
            self._repos.performance_reviews.create(self._employee.id, review_date, comments)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class SetSelfServicePinDialog(tk.Toplevel):
    """Establece (o reemplaza) el PIN de autoservicio de un empleado. Se
    pide dos veces, igual que al crear una contraseña, para detectar una
    errata de tecleo antes de guardar algo que el propio empleado necesitará
    volver a escribir correctamente más tarde para consultar sus datos."""

    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Establecer PIN de autoservicio")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee = employee
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        self.pin_var = tk.StringVar()
        self.confirm_pin_var = tk.StringVar()

        ttk.Label(frame, text="PIN (4-6 dígitos)").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.pin_var, show="•", width=20).grid(
            row=0, column=1, pady=3
        )
        ttk.Label(frame, text="Repetir PIN").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.confirm_pin_var, show="•", width=20).grid(
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
        assert self._employee.id is not None
        if self.pin_var.get() != self.confirm_pin_var.get():
            self.error_label.configure(text="Los dos PIN no coinciden.")
            return
        try:
            self._repos.employees.set_self_service_pin(self._employee.id, self.pin_var.get())
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class EquipmentDialog(tk.Toplevel):
    """Registrar material entregado a un empleado -- la descripción y la
    fecha de entrega no se editan después (si están mal, se elimina y se
    crea de nuevo, igual que Objective/WorkAccident); marcarlo devuelto más
    adelante es una acción propia (MarkEquipmentReturnedDialog)."""

    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title(f"Nuevo equipo asignado — {employee.full_name}")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee = employee
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Descripción *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.description_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.description_var, width=34).grid(
            row=0, column=1, padx=6, pady=4
        )

        ttk.Label(frame, text="Fecha de entrega *").grid(
            row=1, column=0, sticky="w", padx=6, pady=4
        )
        self.assigned_date_entry = DateEntry(frame, max_date=date.today())
        self.assigned_date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frame, text="Notas").grid(row=2, column=0, sticky="nw", padx=6, pady=4)
        self.notes_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.notes_var, width=34).grid(
            row=2, column=1, padx=6, pady=4
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=3, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=4, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        assert self._employee.id is not None
        try:
            assigned_date = validation.validate_equipment_assigned_date(
                self.assigned_date_entry.get()
            )
            description = validation.validate_required_text(
                self.description_var.get(), "descripcion"
            )
            self._repos.assigned_equipment.create(
                self._employee.id, description, assigned_date, self.notes_var.get()
            )
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class MarkEquipmentReturnedDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        equipment: AssignedEquipment,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Marcar equipo como devuelto")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._equipment = equipment
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text=equipment.description, style="PageHeading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )
        ttk.Label(frame, text="Fecha de devolución *").grid(
            row=1, column=0, sticky="w", padx=6, pady=4
        )
        self.returned_date_entry = DateEntry(
            frame, min_date=equipment.assigned_date, max_date=date.today()
        )
        self.returned_date_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=280)
        self.error_label.grid(row=2, column=0, columnspan=2, sticky="w", padx=6)

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_save(self) -> None:
        assert self._equipment.id is not None
        try:
            returned_date = validation.validate_equipment_returned_date(
                self.returned_date_entry.get(), self._equipment.assigned_date
            )
            self._repos.assigned_equipment.mark_returned(self._equipment.id, returned_date)
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class SeveranceViewDialog(tk.Toplevel):
    """Muestra un finiquito, con navegación " < Anterior / Siguiente > " si
    el empleado tiene más de uno (tras varios ciclos baja→reactivar→baja) --
    antes solo se podía ver el más reciente: los anteriores seguían
    intactos en la base de datos (y en la exportación RGPD) pero eran
    inaccesibles desde la ficha. `settlements` ya viene ordenada más
    reciente primero (SeveranceSettlementRepository.list_for_employee())."""

    def __init__(
        self, parent: tk.Misc, employee: Employee, settlements: list[SeveranceSettlement]
    ) -> None:
        super().__init__(parent)
        self._employee = employee
        self._settlements = settlements
        self._index = 0
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._frame = ttk.Frame(self, padding=12)
        self._frame.grid(row=0, column=0, sticky="nsew")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._render()
        center_window(self, parent)

    def _go_previous(self) -> None:
        self._index += 1  # más antiguo, ya que el índice 0 es el más reciente
        self._render()

    def _go_next(self) -> None:
        self._index -= 1  # más reciente
        self._render()

    def _render(self) -> None:
        for widget in self._frame.winfo_children():
            widget.destroy()
        settlement = self._settlements[self._index]
        self.title(f"Finiquito — {self._employee.full_name}")

        row = 0
        if len(self._settlements) > 1:
            nav_row = ttk.Frame(self._frame)
            nav_row.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 6))
            ttk.Button(
                nav_row, text="< Anterior", width=10, command=self._go_previous,
                state="disabled" if self._index >= len(self._settlements) - 1 else "normal",
            ).pack(side="left")
            ttk.Label(
                nav_row, text=f"{self._index + 1} de {len(self._settlements)}", padding=(8, 0),
            ).pack(side="left")
            ttk.Button(
                nav_row, text="Siguiente >", width=10, command=self._go_next,
                state="disabled" if self._index <= 0 else "normal",
            ).pack(side="left")
            row += 1

        rows = [
            ("Fecha de baja", settlement.termination_date.strftime("%d/%m/%Y")),
            ("Motivo", settlement.termination_reason),
            (
                "Vacaciones no disfrutadas",
                f"{settlement.vacation_days_pending:g} días → "
                f"{_format_currency(settlement.vacation_amount)}",
            ),
            (
                "Parte proporcional de paga extra",
                f"{settlement.extra_payment_months_accrued} meses → "
                f"{_format_currency(settlement.extra_payment_amount)}",
            ),
            ("Total finiquito", _format_currency(settlement.total_amount)),
            ("Calculado el", settlement.generated_at.strftime("%d/%m/%Y %H:%M")),
        ]
        first_data_row = row
        for offset, (label, value) in enumerate(rows):
            ttk.Label(self._frame, text=label, style="Muted.TLabel").grid(
                row=first_data_row + offset, column=0, sticky="w", padx=6, pady=3
            )
            ttk.Label(self._frame, text=value).grid(
                row=first_data_row + offset, column=1, sticky="w", padx=6, pady=3
            )
        row = first_data_row + len(rows)

        ttk.Label(
            self._frame,
            text=(
                "No incluye el salario del mes en curso ni ninguna indemnización\n"
                "por despido."
            ),
            style="Muted.TLabel",
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 4))
        row += 1

        ttk.Button(self._frame, text="Cerrar", command=self.destroy).grid(
            row=row, column=0, columnspan=2, pady=(8, 0)
        )


class EmployeeFichaPanel(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        on_saved: Callable[[int], None],
        on_deleted: Callable[[], None],
        on_view_calendar: Callable[[Employee], None],
        locked_department_id: int | None = None,
        is_admin: bool = True,
    ) -> None:
        super().__init__(parent, padding=12)
        self._repos = repos
        self._on_saved = on_saved
        self._on_deleted = on_deleted
        self._on_view_calendar = on_view_calendar
        self._locked_department_id = locked_department_id
        self._is_admin = is_admin
        self._departments: list[Department] = []
        self._shifts: list[Shift] = []
        self._manager_candidates: list[Employee] = []
        self._collective_agreements: list[CollectiveAgreement] = []
        self._professional_categories: list[ProfessionalCategory] = []
        self._current_employee: Employee | None = None
        self._photo_bytes: bytes | None = None
        self._photo_dirty = False
        self._tk_photo_ref: object = None  # keep alive: Tk drops images with no live ref

        # La ficha ya no cabe entera en el alto por defecto de la ventana
        # (1200x680) desde que se acumularon suficientes secciones -- DNI,
        # tipo de contrato, RGPD, Documentos, Historial, Accidentes de
        # trabajo... -- así que, igual que la barra lateral en su momento
        # (ver ScrollableFrame), todo el contenido va dentro de un
        # contenedor con scroll vertical en vez de directamente en self.
        self._scroll = ScrollableFrame(self, bg=theme.current().bg)
        self._scroll.pack(fill="both", expand=True)
        self._scroll.inner.columnconfigure(1, weight=1)
        self._build_widgets()
        self.reload_departments()
        self.reload_professional_categories()
        self.show_employee(None)

    def apply_theme_change(self) -> None:
        self._scroll.set_bg(theme.current().bg)

    def _build_widgets(self) -> None:
        fields_parent = self._scroll.inner
        photo_frame = ttk.Frame(fields_parent)
        photo_frame.grid(row=0, column=0, sticky="n", padx=(0, 16))
        self.photo_label = tk.Label(photo_frame)
        self.photo_label.pack()
        self.change_photo_button = ttk.Button(
            photo_frame, text="Cambiar foto...", command=self._handle_change_photo
        )
        self.change_photo_button.pack(fill="x", pady=(6, 2))
        self.remove_photo_button = ttk.Button(
            photo_frame, text="Quitar foto", command=self._handle_remove_photo
        )
        self.remove_photo_button.pack(fill="x")

        fields = ttk.Frame(fields_parent)
        fields.grid(row=0, column=1, sticky="nsew")
        fields.columnconfigure(1, weight=1)

        self.first_name_var = tk.StringVar()
        self.last_name_var = tk.StringVar()
        self.dni_nie_var = tk.StringVar()
        self.email_var = tk.StringVar()
        self.phone_var = tk.StringVar()
        self.position_var = tk.StringVar()
        self.salary_var = tk.StringVar()
        self.bank_account_var = tk.StringVar()
        self.ss_number_var = tk.StringVar()
        self.dependent_children_var = tk.IntVar(value=0)

        row = 0
        self.name_heading = ttk.Label(
            fields, text="Nuevo empleado", style="PageHeading.TLabel"
        )
        self.name_heading.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 10))

        row += 1
        row = self._add_entry_row(fields, row, "Nombre *", self.first_name_var)
        row = self._add_entry_row(fields, row, "Apellido *", self.last_name_var)
        row = self._add_entry_row(fields, row, "DNI/NIE", self.dni_nie_var)

        row, birth_date_row = self._add_optional_date_row(fields, row, "Fecha de nacimiento")
        self.birth_date_entry = DateEntry(birth_date_row, max_date=date.today())
        self.birth_date_entry.grid(row=0, column=0, sticky="w")
        self.no_birth_date_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            birth_date_row,
            text="No indicada",
            variable=self.no_birth_date_var,
            command=self._handle_no_birth_date_toggled,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))

        row = self._add_entry_row(fields, row, "Email *", self.email_var)
        row = self._add_entry_row(fields, row, "Teléfono", self.phone_var)
        row = self._add_entry_row(fields, row, "Puesto *", self.position_var)

        ttk.Label(fields, text="Categoría profesional").grid(
            row=row, column=0, sticky="w", pady=3
        )
        self.professional_category_combo = ttk.Combobox(
            fields, state="readonly", width=48, values=[_NO_PROFESSIONAL_CATEGORY_LABEL]
        )
        self.professional_category_combo.current(0)
        self.professional_category_combo.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        ttk.Label(fields, text="Departamento *").grid(row=row, column=0, sticky="w", pady=3)
        self.department_combo = ttk.Combobox(
            fields,
            state="disabled" if self._locked_department_id is not None else "readonly",
            width=34,
        )
        self.department_combo.grid(row=row, column=1, sticky="w", pady=3)
        self.department_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._handle_department_selection_changed()
        )
        row += 1

        ttk.Label(fields, text="Turno").grid(row=row, column=0, sticky="w", pady=3)
        self.shift_combo = ttk.Combobox(
            fields, state="readonly", width=34, values=[_NO_SHIFT_LABEL]
        )
        self.shift_combo.current(0)
        self.shift_combo.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        ttk.Label(fields, text="Supervisor directo").grid(row=row, column=0, sticky="w", pady=3)
        self.manager_combo = ttk.Combobox(
            fields, state="readonly", width=34, values=[_NO_MANAGER_LABEL]
        )
        self.manager_combo.current(0)
        self.manager_combo.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        # head_row con grid() interno (no pack(side="left") como antes, ni
        # columnas 1/2 directas contra "fields" tampoco -- eso se probó y
        # forzaba la columna 1 compartida por TODOS los Entry/Combobox de
        # la ficha a comprimirse casi a 0, dejando en blanco Nombre/Email/
        # etc.): mismo patrón ya usado para las filas de fecha opcional de
        # más arriba, un frame propio con su propio grid(row=0,
        # column=0/1) interno, que no compite por la columna 1 de "fields".
        ttk.Label(fields, text="Encargado/a de departamento").grid(
            row=row, column=0, sticky="w", pady=3
        )
        head_row = ttk.Frame(fields)
        head_row.grid(row=row, column=1, sticky="w", pady=3)
        self.is_department_head_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            head_row,
            variable=self.is_department_head_var,
            command=self._handle_department_head_toggled,
        ).grid(row=0, column=0, sticky="w")
        self.head_of_department_combo = ttk.Combobox(head_row, state="disabled", width=24)
        self.head_of_department_combo.grid(row=0, column=1, sticky="w", padx=(6, 0))
        row += 1

        row = self._add_entry_row(fields, row, "Salario *", self.salary_var)

        ttk.Label(fields, text="Fecha de ingreso *").grid(row=row, column=0, sticky="w", pady=3)
        self.hire_date_entry = DateEntry(fields, max_date=date.today())
        self.hire_date_entry.grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        ttk.Label(fields, text="Tipo de contrato *").grid(row=row, column=0, sticky="w", pady=3)
        self.contract_type_combo = ttk.Combobox(
            fields, state="readonly", width=30, values=list(validation.CONTRACT_TYPES)
        )
        self.contract_type_combo.current(0)
        self.contract_type_combo.grid(row=row, column=1, sticky="w", pady=3)
        self.contract_type_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._handle_contract_type_changed()
        )
        row += 1

        row, end_date_row = self._add_optional_date_row(
            fields, row, "Fecha de fin de contrato"
        )
        self.contract_end_date_entry = DateEntry(end_date_row)
        self.contract_end_date_entry.grid(row=0, column=0, sticky="w")
        self.no_end_date_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            end_date_row,
            # "Sin fecha" (no "Sin fecha prevista"): la propia etiqueta de
            # la fila ya dice "Fecha de fin de contrato", así que el texto
            # largo era redundante -- y a 19 caracteres era mucho más largo
            # que "No indicada"/"Pendiente" de las otras filas de fecha
            # opcional, sin motivo real, por lo que era la casilla que peor
            # cabía.
            text="Sin fecha",
            variable=self.no_end_date_var,
            command=self._handle_no_end_date_toggled,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))

        row = self._add_entry_row(fields, row, "Cuenta bancaria (IBAN)", self.bank_account_var)
        row = self._add_entry_row(fields, row, "Núm. Seguridad Social", self.ss_number_var)

        row, checkup_row = self._add_optional_date_row(fields, row, "Próxima revisión médica")
        self.next_medical_checkup_entry = DateEntry(checkup_row)
        self.next_medical_checkup_entry.grid(row=0, column=0, sticky="w")
        self.no_medical_checkup_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            checkup_row,
            text="No indicada",
            variable=self.no_medical_checkup_var,
            command=self._handle_no_medical_checkup_toggled,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))

        row, prl_row = self._add_optional_date_row(fields, row, "Fecha de formación PRL")
        self.prl_training_entry = DateEntry(prl_row)
        self.prl_training_entry.grid(row=0, column=0, sticky="w")
        self.no_prl_training_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            prl_row,
            text="Pendiente",
            variable=self.no_prl_training_var,
            command=self._handle_no_prl_training_toggled,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Label(fields, text="Hijos a cargo").grid(row=row, column=0, sticky="w", pady=3)
        ttk.Spinbox(
            fields,
            from_=0,
            to=validation.MAX_DEPENDENT_CHILDREN,
            textvariable=self.dependent_children_var,
            state="readonly",
            width=5,
        ).grid(row=row, column=1, sticky="w", pady=3)
        row += 1

        # Etiqueta y botones en filas separadas (no la misma fila empaquetada
        # side="left"): "Inactivo desde DD/MM/AAAA (motivo)" puede ser bastante
        # más largo que "Activo", y con los tres botones compitiendo por sitio
        # en la misma fila un panel estrecho (el panedwindow es redimensionable
        # por el usuario) los empujaba fuera del área visible por completo.
        self.status_label = ttk.Label(fields, text="", style="Muted.TLabel")
        self.status_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(3, 0))
        row += 1

        status_button_row = ttk.Frame(fields)
        status_button_row.grid(row=row, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self.terminate_button = ttk.Button(
            status_button_row, text="Dar de baja...", command=self._handle_terminate
        )
        self.terminate_button.pack(side="left")
        self.reactivate_button = ttk.Button(
            status_button_row, text="Reactivar", command=self._handle_reactivate
        )
        self.reactivate_button.pack(side="left", padx=(6, 0))
        row += 1

        # Fila propia (no junto a los dos de arriba): tres botones en la
        # misma fila no cabían en el ancho por defecto del panel de ficha,
        # empujando "Ver finiquito..." fuera del área visible.
        self.view_severance_button = ttk.Button(
            fields, text="Ver finiquito...", command=self._handle_view_severance
        )
        self.view_severance_button.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 3))
        row += 1

        # Cada botón en su propia fila (mismo motivo que view_severance_button
        # arriba): "Exportar datos (RGPD)..." + "Anonimizar datos..." juntos en
        # una fila no caben en el ancho por defecto del panel y el segundo
        # queda recortado. RGPD (art. 15/17) -- exportar es admin-only por
        # consistencia con el resto de acciones sensibles de la ficha, no
        # porque el derecho de acceso en sí lo exija. Anonimizar solo tiene
        # sentido con la baja ya tramitada, ver _refresh_rgpd_buttons().
        self.export_data_button = ttk.Button(
            fields, text="Exportar datos (RGPD)...", command=self._handle_export_data
        )
        self.export_data_button.grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 2))
        row += 1
        self.anonymize_button = ttk.Button(
            fields, text="Anonimizar datos...", command=self._handle_anonymize
        )
        self.anonymize_button.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 3))
        row += 1

        # El texto del saldo es dinámico y puede ser largo ("Vacaciones 2026:
        # usa 5 de 22 días (quedan 17)") -- en la misma fila que el botón,
        # el conjunto no cabía y el botón (empaquetado el último) se recortaba
        # a "Cor". Cada uno en su propia fila, mismo criterio ya aplicado a
        # "Añadir equipo/Marcar como devuelto/Eliminar equipo" más abajo.
        self.vacation_balance_label = ttk.Label(fields, text="", style="Muted.TLabel")
        self.vacation_balance_label.grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        row += 1
        self.vacation_settings_button = ttk.Button(
            fields,
            text="Configurar días de vacaciones...",
            command=self._handle_open_vacation_settings,
        )
        self.vacation_settings_button.grid(row=row, column=0, columnspan=2, sticky="w")
        if not self._is_admin:
            self.vacation_settings_button.state(["disabled"])
        row += 1

        self.error_label = ttk.Label(fields, text="", style="Error.TLabel", wraplength=380)
        self.error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        row += 1

        # Cada botón en su propia fila (mismo motivo que view_severance_button
        # más abajo): los tres juntos no caben en el ancho por defecto del
        # panel de ficha y "Ver calendario..." quedaba recortado.
        self.save_button = ttk.Button(
            fields,
            text="Guardar cambios",
            command=self._handle_save,
            style="Accent.TButton",
        )
        self.save_button.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 2))
        row += 1
        self.calendar_button = ttk.Button(
            fields, text="Ver calendario...", command=self._handle_view_calendar
        )
        self.calendar_button.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1
        self.delete_button = ttk.Button(fields, text="Eliminar", command=self._handle_delete)
        self.delete_button.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 3))
        row += 1

        ttk.Label(fields, text="Incorporación", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        row += 1
        self.onboarding_frame = ttk.Frame(fields)
        self.onboarding_frame.grid(row=row, column=0, columnspan=2, sticky="ew")
        row += 1

        ttk.Label(fields, text="Documentos", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        row += 1

        doc_tree_frame = ttk.Frame(fields)
        doc_tree_frame.grid(row=row, column=0, columnspan=2, sticky="ew")
        self.documents_tree = ttk.Treeview(
            doc_tree_frame,
            columns=("filename", "category", "size", "uploaded"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for col, label, width in [
            ("filename", "Archivo", 170),
            ("category", "Categoría", 100),
            ("size", "Tamaño", 85),
            ("uploaded", "Subido el", 130),
        ]:
            self.documents_tree.heading(col, text=label)
            self.documents_tree.column(col, width=width, anchor="w")
        doc_vsb = ttk.Scrollbar(
            doc_tree_frame, orient="vertical", command=self.documents_tree.yview
        )
        self.documents_tree.configure(yscrollcommand=doc_vsb.set)
        self.documents_tree.pack(side="left", fill="x", expand=True)
        doc_vsb.pack(side="left", fill="y")
        row += 1

        # Cada botón en su propia fila (mismo motivo que en "Guardar
        # cambios"/"Ver calendario..." más arriba): los cuatro juntos no
        # caben ni de lejos en el ancho por defecto del panel de ficha.
        self.upload_document_button = ttk.Button(
            fields, text="Adjuntar documento...", command=self._handle_upload_document
        )
        self.upload_document_button.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 2))
        row += 1
        self.generate_document_button = ttk.Button(
            fields, text="Generar documento...", command=self._handle_generate_document
        )
        self.generate_document_button.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1
        ttk.Button(fields, text="Descargar", command=self._handle_download_document).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 2)
        )
        row += 1
        ttk.Button(
            fields, text="Eliminar documento", command=self._handle_delete_document
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1
        self.documents_error_label = ttk.Label(fields, text="", style="Error.TLabel", wraplength=380)
        self.documents_error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        ttk.Label(fields, text="Historial de puesto y salario", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        row += 1

        history_tree_frame = ttk.Frame(fields)
        history_tree_frame.grid(row=row, column=0, columnspan=2, sticky="ew")
        self.history_tree = ttk.Treeview(
            history_tree_frame,
            columns=("fecha", "puesto", "salario", "nota"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for col, label, width in [
            ("fecha", "Desde", 95),
            ("puesto", "Puesto", 160),
            ("salario", "Salario anual", 115),
            ("nota", "Nota", 130),
        ]:
            self.history_tree.heading(col, text=label)
            self.history_tree.column(col, width=width, anchor="w")
        history_vsb = ttk.Scrollbar(
            history_tree_frame, orient="vertical", command=self.history_tree.yview
        )
        self.history_tree.configure(yscrollcommand=history_vsb.set)
        self.history_tree.pack(side="left", fill="x", expand=True)
        history_vsb.pack(side="left", fill="y")
        row += 1

        ttk.Label(fields, text="Accidentes de trabajo", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        row += 1

        accident_tree_frame = ttk.Frame(fields)
        accident_tree_frame.grid(row=row, column=0, columnspan=2, sticky="ew")
        self.accidents_tree = ttk.Treeview(
            accident_tree_frame,
            columns=("fecha", "gravedad", "baja", "notificado", "descripcion"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for col, label, width in [
            ("fecha", "Fecha", 95),
            ("gravedad", "Gravedad", 100),
            ("baja", "Con baja", 95),
            ("notificado", "Notificado", 105),
            ("descripcion", "Descripción", 160),
        ]:
            self.accidents_tree.heading(col, text=label)
            self.accidents_tree.column(col, width=width, anchor="w")
        accident_vsb = ttk.Scrollbar(
            accident_tree_frame, orient="vertical", command=self.accidents_tree.yview
        )
        self.accidents_tree.configure(yscrollcommand=accident_vsb.set)
        self.accidents_tree.pack(side="left", fill="x", expand=True)
        accident_vsb.pack(side="left", fill="y")
        row += 1

        # Cada botón en su propia fila (mismo motivo que en "Guardar
        # cambios"/"Ver calendario..." más arriba): juntos no caben en el
        # ancho por defecto del panel de ficha.
        ttk.Button(
            fields, text="Registrar accidente...", command=self._handle_register_accident
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 2))
        row += 1
        ttk.Button(
            fields, text="Eliminar accidente", command=self._handle_delete_accident
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1
        self.accidents_error_label = ttk.Label(fields, text="", style="Error.TLabel", wraplength=380)
        self.accidents_error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        ttk.Label(fields, text="Incapacidad temporal", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        row += 1

        it_tree_frame = ttk.Frame(fields)
        it_tree_frame.grid(row=row, column=0, columnspan=2, sticky="ew")
        self.it_episodes_tree = ttk.Treeview(
            it_tree_frame,
            columns=("contingencia", "baja", "confirmacion", "alta"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for col, label, width in [
            ("contingencia", "Contingencia", 130),
            ("baja", "Fecha de baja", 100),
            ("confirmacion", "Confirmación", 105),
            ("alta", "Alta", 90),
        ]:
            self.it_episodes_tree.heading(col, text=label)
            self.it_episodes_tree.column(col, width=width, anchor="w")
        it_vsb = ttk.Scrollbar(
            it_tree_frame, orient="vertical", command=self.it_episodes_tree.yview
        )
        self.it_episodes_tree.configure(yscrollcommand=it_vsb.set)
        self.it_episodes_tree.pack(side="left", fill="x", expand=True)
        it_vsb.pack(side="left", fill="y")
        self.it_episodes_tree.bind("<Double-1>", lambda _e: self._handle_view_it_episode())
        row += 1

        # Cada botón en su propia fila (mismo motivo que en "Guardar
        # cambios"/"Ver calendario..." más arriba).
        ttk.Button(
            fields, text="Registrar baja (IT)...", command=self._handle_register_it_episode
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 2))
        row += 1
        ttk.Button(
            fields, text="Ver / gestionar...", command=self._handle_view_it_episode
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1
        self.it_episodes_error_label = ttk.Label(
            fields, text="", style="Error.TLabel", wraplength=380
        )
        self.it_episodes_error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        ttk.Label(fields, text="Formación y certificaciones", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        row += 1

        training_tree_frame = ttk.Frame(fields)
        training_tree_frame.grid(row=row, column=0, columnspan=2, sticky="ew")
        self.trainings_tree = ttk.Treeview(
            training_tree_frame,
            columns=("nombre", "finalizacion", "caducidad"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for col, label, width in [
            ("nombre", "Nombre", 190),
            ("finalizacion", "Finalización", 105),
            ("caducidad", "Caducidad", 100),
        ]:
            self.trainings_tree.heading(col, text=label)
            self.trainings_tree.column(col, width=width, anchor="w")
        training_vsb = ttk.Scrollbar(
            training_tree_frame, orient="vertical", command=self.trainings_tree.yview
        )
        self.trainings_tree.configure(yscrollcommand=training_vsb.set)
        self.trainings_tree.pack(side="left", fill="x", expand=True)
        training_vsb.pack(side="left", fill="y")
        row += 1

        # Cada botón en su propia fila (mismo motivo que en "Guardar
        # cambios"/"Ver calendario..." más arriba).
        ttk.Button(
            fields, text="Añadir formación...", command=self._handle_add_training
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 2))
        row += 1
        ttk.Button(
            fields, text="Eliminar formación", command=self._handle_delete_training
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1
        self.trainings_error_label = ttk.Label(
            fields, text="", style="Error.TLabel", wraplength=380
        )
        self.trainings_error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        ttk.Label(fields, text="Autoservicio", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        row += 1
        ttk.Label(
            fields,
            text=(
                "Un PIN de 4-6 dígitos que el propio empleado usa, junto a su "
                "email, para consultar su nómina, saldo de vacaciones y fichajes "
                "desde la ventana de inicio de sesión, sin necesitar una cuenta."
            ),
            style="Muted.TLabel",
            justify="left",
            wraplength=380,
        ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.self_service_status_label = ttk.Label(fields, text="", style="Muted.TLabel")
        self.self_service_status_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        # Cada botón en su propia fila (mismo motivo que en "Guardar
        # cambios"/"Ver calendario..." más arriba).
        ttk.Button(
            fields, text="Establecer PIN...", command=self._handle_set_self_service_pin
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 2))
        row += 1
        ttk.Button(
            fields, text="Quitar PIN", command=self._handle_clear_self_service_pin
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1

        self.self_service_error_label = ttk.Label(
            fields, text="", style="Error.TLabel", wraplength=380
        )
        self.self_service_error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 2

        ttk.Label(fields, text="Desempeño", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        row += 1

        ttk.Label(fields, text="Objetivos").grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        objectives_tree_frame = ttk.Frame(fields)
        objectives_tree_frame.grid(row=row, column=0, columnspan=2, sticky="ew")
        self.objectives_tree = ttk.Treeview(
            objectives_tree_frame,
            columns=("titulo", "fecha", "estado"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for col, label, width in [
            ("titulo", "Título", 190),
            ("fecha", "Fecha objetivo", 125),
            ("estado", "Estado", 90),
        ]:
            self.objectives_tree.heading(col, text=label)
            self.objectives_tree.column(col, width=width, anchor="w")
        objectives_vsb = ttk.Scrollbar(
            objectives_tree_frame, orient="vertical", command=self.objectives_tree.yview
        )
        self.objectives_tree.configure(yscrollcommand=objectives_vsb.set)
        self.objectives_tree.pack(side="left", fill="x", expand=True)
        objectives_vsb.pack(side="left", fill="y")
        row += 1

        # Cada botón en su propia fila (mismo motivo que en "Guardar
        # cambios"/"Ver calendario..." más arriba): los tres juntos no caben.
        ttk.Button(
            fields, text="Añadir objetivo...", command=self._handle_add_objective
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 2))
        row += 1
        ttk.Button(
            fields, text="Cambiar estado...", command=self._handle_change_objective_status
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1
        ttk.Button(
            fields, text="Eliminar objetivo", command=self._handle_delete_objective
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1

        self.objectives_error_label = ttk.Label(
            fields, text="", style="Error.TLabel", wraplength=380
        )
        self.objectives_error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 2

        ttk.Label(fields, text="Evaluaciones").grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        reviews_tree_frame = ttk.Frame(fields)
        reviews_tree_frame.grid(row=row, column=0, columnspan=2, sticky="ew")
        self.reviews_tree = ttk.Treeview(
            reviews_tree_frame,
            columns=("fecha", "comentarios"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for col, label, width in [("fecha", "Fecha", 100), ("comentarios", "Comentarios", 290)]:
            self.reviews_tree.heading(col, text=label)
            self.reviews_tree.column(col, width=width, anchor="w")
        reviews_vsb = ttk.Scrollbar(
            reviews_tree_frame, orient="vertical", command=self.reviews_tree.yview
        )
        self.reviews_tree.configure(yscrollcommand=reviews_vsb.set)
        self.reviews_tree.pack(side="left", fill="x", expand=True)
        reviews_vsb.pack(side="left", fill="y")
        row += 1

        # Cada botón en su propia fila (mismo motivo que en "Guardar
        # cambios"/"Ver calendario..." más arriba): "Eliminar evaluación"
        # quedaba recortado a "Eliminar ev".
        ttk.Button(
            fields, text="Añadir evaluación...", command=self._handle_add_review
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 2))
        row += 1
        ttk.Button(
            fields, text="Eliminar evaluación", command=self._handle_delete_review
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1

        self.reviews_error_label = ttk.Label(fields, text="", style="Error.TLabel", wraplength=380)
        self.reviews_error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        ttk.Label(fields, text="Equipo asignado", style="PageHeading.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(16, 4)
        )
        row += 1

        equipment_tree_frame = ttk.Frame(fields)
        equipment_tree_frame.grid(row=row, column=0, columnspan=2, sticky="ew")
        self.equipment_tree = ttk.Treeview(
            equipment_tree_frame,
            columns=("descripcion", "entrega", "devolucion"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for col, label, width in [
            ("descripcion", "Descripción", 190),
            ("entrega", "Fecha entrega", 115),
            ("devolucion", "Fecha devolución", 140),
        ]:
            self.equipment_tree.heading(col, text=label)
            self.equipment_tree.column(col, width=width, anchor="w")
        equipment_vsb = ttk.Scrollbar(
            equipment_tree_frame, orient="vertical", command=self.equipment_tree.yview
        )
        self.equipment_tree.configure(yscrollcommand=equipment_vsb.set)
        self.equipment_tree.pack(side="left", fill="x", expand=True)
        equipment_vsb.pack(side="left", fill="y")
        row += 1

        # Cada botón en su propia fila (mismo motivo que en "Guardar
        # cambios"/"Ver calendario..." más arriba): los tres juntos no caben.
        ttk.Button(
            fields, text="Añadir equipo...", command=self._handle_add_equipment
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 2))
        row += 1
        ttk.Button(
            fields, text="Marcar como devuelto...", command=self._handle_mark_equipment_returned
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1
        ttk.Button(
            fields, text="Eliminar equipo", command=self._handle_delete_equipment
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1

        self.equipment_error_label = ttk.Label(
            fields, text="", style="Error.TLabel", wraplength=380
        )
        self.equipment_error_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

    def _add_entry_row(
        self, parent: ttk.Frame, row: int, label: str, var: tk.StringVar
    ) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        # 38, no 34: con el panel de ficha ya ensanchado (ver _build_widgets
        # del EmployeePage) sigue habiendo sitio de sobra, y un IBAN
        # completo ("ES91 2100 0418 4502 0005 1332", 29 caracteres) o un
        # email largo necesitaban más margen del que 34 daba.
        ttk.Entry(parent, textvariable=var, width=38).grid(
            row=row, column=1, sticky="w", pady=3
        )
        return row + 1

    def _add_optional_date_row(
        self, parent: ttk.Frame, row: int, label: str
    ) -> tuple[int, ttk.Frame]:
        """Coloca la etiqueta y un frame propio (con su propio grid()
        interno) para un DateEntry + casilla (fecha de nacimiento, fin de
        contrato, revisión médica, formación PRL) -- el DateEntry y la
        casilla en sí los construye cada llamador contra el frame
        devuelto, ya que cada uno necesita su propia variable/callback/
        kwargs. El frame usa grid(), no pack(side="left") como antes: con
        pack(), cuando la columna se quedaba sin ancho suficiente, Tk
        directamente dejaba de dibujar la casilla (el último hijo
        empaquetado) en vez de encogerla -- desaparecía del todo, no solo
        se recortaba.

        Nota: se probó también poner el DateEntry y la casilla como
        columnas 1/2 directas de `parent` (protegiendo la casilla de
        cualquier compresión, ya que una columna del grid sin weight
        nunca se sacrifica) -- pero eso hacía que la columna 1, compartida
        por TODOS los Entry/Combobox de la ficha, se comprimiera casi a 0
        para poder darle a la casilla su ancho natural en la columna 2,
        dejando en blanco Nombre/Email/Puesto/etc. Con el frame propio
        (como aquí), el DateEntry y la casilla compiten solo entre ellos
        dos, no con el resto de la ficha."""
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        date_row = ttk.Frame(parent)
        date_row.grid(row=row, column=1, sticky="w", pady=3)
        return row + 1, date_row

    def reload_departments(self) -> None:
        self._departments = self._repos.departments.list_all()
        if self._locked_department_id is not None:
            self._departments = [
                d for d in self._departments if d.id == self._locked_department_id
            ]
        self.department_combo.configure(values=[d.name for d in self._departments])
        if self._current_employee is not None:
            self._select_department_in_combo(self._current_employee.department_id)
        elif self._locked_department_id is not None:
            self._select_department_in_combo(self._locked_department_id)
        self.head_of_department_combo.configure(values=[d.name for d in self._departments])
        self._refresh_head_of_department_field(
            self._current_employee.head_of_department_id
            if self._current_employee is not None
            else None
        )
        self._reload_shifts_for_selected_department()
        self._reload_manager_options_for_selected_department()

    def _handle_department_selection_changed(self) -> None:
        self._reload_shifts_for_selected_department()
        self._reload_manager_options_for_selected_department()

    def _select_department_in_combo(self, department_id: int) -> None:
        for idx, dept in enumerate(self._departments):
            if dept.id == department_id:
                self.department_combo.current(idx)
                return

    def _selected_department_id(self) -> int | None:
        if self._locked_department_id is not None:
            return self._locked_department_id
        idx = self.department_combo.current()
        if idx == -1:
            return None
        return self._departments[idx].id

    def _reload_shifts_for_selected_department(self) -> None:
        department_id = self._selected_department_id()
        self._shifts = (
            self._repos.shifts.list_for_department(department_id)
            if department_id is not None
            else []
        )
        values = [_NO_SHIFT_LABEL] + [
            f"{s.name} ({s.start_time}-{s.end_time})" for s in self._shifts
        ]
        self.shift_combo.configure(values=values)

        target_shift_id = self._current_employee.shift_id if self._current_employee else None
        selected_index = 0
        if target_shift_id is not None:
            for idx, shift in enumerate(self._shifts, start=1):
                if shift.id == target_shift_id:
                    selected_index = idx
                    break
        self.shift_combo.current(selected_index)

    def _reload_manager_options_for_selected_department(self) -> None:
        department_id = self._selected_department_id()
        candidates = (
            self._repos.employees.search(department_id=department_id, active_only=True)
            if department_id is not None
            else []
        )
        self_id = self._current_employee.id if self._current_employee is not None else None
        self._manager_candidates = [e for e in candidates if e.id != self_id]

        target_manager_id = (
            self._current_employee.manager_id if self._current_employee is not None else None
        )
        labels = [_NO_MANAGER_LABEL] + [e.full_name for e in self._manager_candidates]
        if target_manager_id is not None and not any(
            e.id == target_manager_id for e in self._manager_candidates
        ):
            # El supervisor ya asignado se dio de baja después de
            # asignarse (el único caso realista, ya que crear/editar exige
            # un supervisor activo del mismo departamento) -- se añade
            # igualmente al final, marcado, para que el valor actual nunca
            # desaparezca en silencio del desplegable (mismo criterio que
            # reload_departments() en payroll_ui.py con un department_id
            # bloqueado que ya no está en la lista fresca).
            try:
                current_manager = self._repos.employees.get(target_manager_id)
                self._manager_candidates.append(current_manager)
                labels.append(f"{current_manager.full_name} (de baja)")
            except RepositoryError:
                pass

        self.manager_combo.configure(values=labels)

        selected_index = 0
        if target_manager_id is not None:
            for idx, candidate in enumerate(self._manager_candidates, start=1):
                if candidate.id == target_manager_id:
                    selected_index = idx
                    break
        self.manager_combo.current(selected_index)

    def reload_professional_categories(self) -> None:
        self._collective_agreements = self._repos.collective_agreements.list_all()
        agreements_by_id = {
            a.id: a for a in self._collective_agreements if a.id is not None
        }
        # Filtrado y no solo mapeado: así self._professional_categories y
        # las etiquetas del combo quedan siempre en el mismo orden e índice
        # (igual que self._manager_candidates con manager_combo), sin
        # depender de que la FK a collective_agreements nunca falle.
        self._professional_categories = [
            c
            for c in self._repos.professional_categories.list_all()
            if c.collective_agreement_id in agreements_by_id
        ]
        labels = [_NO_PROFESSIONAL_CATEGORY_LABEL] + [
            f"{agreements_by_id[c.collective_agreement_id].name} — {c.name}"
            for c in self._professional_categories
        ]
        self.professional_category_combo.configure(values=labels)
        self._refresh_professional_category_field(
            self._current_employee.professional_category_id
            if self._current_employee is not None
            else None
        )

    def _refresh_professional_category_field(
        self, professional_category_id: int | None
    ) -> None:
        # A diferencia de manager_id (puede quedarse "huérfano" si el
        # supervisor deja de estar activo) o shift_id (si cambia el
        # departamento), una categoría profesional no tiene ninguna
        # restricción de la que pueda "salirse": si el id no es None, la
        # categoría existe con certeza (professional_category_id se pone a
        # NULL automáticamente si la categoría se elimina), así que nunca
        # hace falta un caso "(de baja)" como con el supervisor.
        selected_index = 0
        if professional_category_id is not None:
            for idx, category in enumerate(self._professional_categories, start=1):
                if category.id == professional_category_id:
                    selected_index = idx
                    break
        self.professional_category_combo.current(selected_index)

    def _handle_department_head_toggled(self) -> None:
        self.head_of_department_combo.configure(
            state="readonly" if self.is_department_head_var.get() else "disabled"
        )

    def _refresh_head_of_department_field(self, head_of_department_id: int | None) -> None:
        self.is_department_head_var.set(head_of_department_id is not None)
        if head_of_department_id is not None:
            for idx, dept in enumerate(self._departments):
                if dept.id == head_of_department_id:
                    self.head_of_department_combo.current(idx)
                    break
        else:
            self.head_of_department_combo.set("")
        self._handle_department_head_toggled()

    def _handle_contract_type_changed(self) -> None:
        # Switching to Indefinido forces "sin fecha" back on; switching away
        # from it un-checks it automatically so the date field doesn't stay
        # stuck disabled after picking a type that can have an end date --
        # the user can still re-check it manually if the date isn't known yet.
        self.no_end_date_var.set(self.contract_type_combo.get() == "Indefinido")
        self._handle_no_end_date_toggled()

    def _handle_no_end_date_toggled(self) -> None:
        is_indefinido = self.contract_type_combo.get() == "Indefinido"
        if is_indefinido:
            self.no_end_date_var.set(True)
        self.contract_end_date_entry.set_enabled(not self.no_end_date_var.get())

    def _handle_no_birth_date_toggled(self) -> None:
        self.birth_date_entry.set_enabled(not self.no_birth_date_var.get())

    def _handle_no_medical_checkup_toggled(self) -> None:
        self.next_medical_checkup_entry.set_enabled(not self.no_medical_checkup_var.get())

    def _handle_no_prl_training_toggled(self) -> None:
        self.prl_training_entry.set_enabled(not self.no_prl_training_var.get())

    def show_employee(self, employee: Employee | None) -> None:
        self._current_employee = employee
        self._photo_bytes = employee.photo if employee else None
        self._photo_dirty = False
        self.error_label.configure(text="")

        if employee is None:
            self.name_heading.configure(text="Nuevo empleado")
            self.first_name_var.set("")
            self.last_name_var.set("")
            self.dni_nie_var.set("")
            self.email_var.set("")
            self.phone_var.set("")
            self.position_var.set("")
            self.salary_var.set("")
            self.bank_account_var.set("")
            self.ss_number_var.set("")
            self.dependent_children_var.set(0)
            self.hire_date_entry.value_var.set(date.today().isoformat())
            self.contract_type_combo.current(0)
            self.no_end_date_var.set(True)
            self.contract_end_date_entry.value_var.set(date.today().isoformat())
            self._handle_no_end_date_toggled()
            self.no_birth_date_var.set(True)
            self.birth_date_entry.value_var.set(date.today().isoformat())
            self._handle_no_birth_date_toggled()
            self.no_medical_checkup_var.set(True)
            self.next_medical_checkup_entry.value_var.set(date.today().isoformat())
            self._handle_no_medical_checkup_toggled()
            self.no_prl_training_var.set(True)
            self.prl_training_entry.value_var.set(date.today().isoformat())
            self._handle_no_prl_training_toggled()
            if self._locked_department_id is not None:
                self._select_department_in_combo(self._locked_department_id)
            else:
                self.department_combo.set("")
            self.delete_button.state(["disabled"])
            self.calendar_button.state(["disabled"])
        else:
            self.name_heading.configure(text=employee.full_name)
            self.first_name_var.set(employee.first_name)
            self.last_name_var.set(employee.last_name)
            self.dni_nie_var.set(employee.dni_nie or "")
            self.email_var.set(employee.email)
            self.phone_var.set(employee.phone)
            self.position_var.set(employee.position)
            self.salary_var.set(f"{employee.salary:.2f}")
            self.bank_account_var.set(employee.bank_account)
            self.ss_number_var.set(employee.ss_number or "")
            self.dependent_children_var.set(employee.dependent_children)
            self.hire_date_entry.value_var.set(employee.hire_date.isoformat())
            self.contract_type_combo.set(employee.contract_type)
            if employee.contract_end_date is not None:
                self.no_end_date_var.set(False)
                self.contract_end_date_entry.value_var.set(
                    employee.contract_end_date.isoformat()
                )
            else:
                self.no_end_date_var.set(True)
                self.contract_end_date_entry.value_var.set(date.today().isoformat())
            self._handle_no_end_date_toggled()
            if employee.birth_date is not None:
                self.no_birth_date_var.set(False)
                self.birth_date_entry.value_var.set(employee.birth_date.isoformat())
            else:
                self.no_birth_date_var.set(True)
                self.birth_date_entry.value_var.set(date.today().isoformat())
            self._handle_no_birth_date_toggled()
            if employee.next_medical_checkup_date is not None:
                self.no_medical_checkup_var.set(False)
                self.next_medical_checkup_entry.value_var.set(
                    employee.next_medical_checkup_date.isoformat()
                )
            else:
                self.no_medical_checkup_var.set(True)
                self.next_medical_checkup_entry.value_var.set(date.today().isoformat())
            self._handle_no_medical_checkup_toggled()
            if employee.prl_training_date is not None:
                self.no_prl_training_var.set(False)
                self.prl_training_entry.value_var.set(employee.prl_training_date.isoformat())
            else:
                self.no_prl_training_var.set(True)
                self.prl_training_entry.value_var.set(date.today().isoformat())
            self._handle_no_prl_training_toggled()
            self._select_department_in_combo(employee.department_id)
            self.delete_button.state(["!disabled"])
            self.calendar_button.state(["!disabled"])

        self._reload_shifts_for_selected_department()
        self._reload_manager_options_for_selected_department()
        self._refresh_head_of_department_field(
            employee.head_of_department_id if employee is not None else None
        )
        self._refresh_professional_category_field(
            employee.professional_category_id if employee is not None else None
        )
        self._refresh_photo_display()
        self._refresh_vacation_balance()
        self._refresh_onboarding_checklist()
        self._refresh_documents()
        self._refresh_history()
        self._refresh_accidents()
        self._refresh_it_episodes()
        self._refresh_trainings()
        self._refresh_self_service_status()
        self._refresh_objectives()
        self._refresh_reviews()
        self._refresh_equipment()
        self._refresh_termination_status()
        self._refresh_rgpd_buttons()
        self._refresh_anonymized_lock()

    def _refresh_termination_status(self) -> None:
        employee = self._current_employee
        if employee is None:
            self.status_label.configure(text="")
            self.terminate_button.state(["disabled"])
            self.reactivate_button.state(["disabled"])
            self.view_severance_button.state(["disabled"])
            return
        assert employee.id is not None
        if employee.active:
            self.status_label.configure(text="Activo")
            self.terminate_button.state(["!disabled"])
            self.reactivate_button.state(["disabled"])
        else:
            fecha = employee.termination_date.strftime("%d/%m/%Y") if employee.termination_date else "?"
            motivo = employee.termination_reason or "sin motivo registrado"
            self.status_label.configure(text=f"Inactivo desde {fecha} ({motivo})")
            self.terminate_button.state(["disabled"])
            self.reactivate_button.state(["!disabled"])
        has_settlement = bool(self._repos.severance_settlements.list_for_employee(employee.id))
        self.view_severance_button.state(["!disabled" if has_settlement else "disabled"])

    def _refresh_rgpd_buttons(self) -> None:
        employee = self._current_employee
        if employee is None or not self._is_admin:
            self.export_data_button.state(["disabled"])
            self.anonymize_button.state(["disabled"])
            return
        self.export_data_button.state(["!disabled"])
        can_anonymize = not employee.active and not employee.anonymized
        self.anonymize_button.state(["!disabled" if can_anonymize else "disabled"])

    def _refresh_anonymized_lock(self) -> None:
        # Un empleado ya anonimizado no se puede volver a editar --
        # EmployeeRepository.update()/set_photo() y
        # EmployeeDocumentRepository.upload() ya lo rechazan a nivel de
        # repositorio (esa es la protección real); esto solo evita el paso
        # extra de hacer clic y encontrarse con un error, deshabilitando de
        # entrada los botones que llevarían ahí. Independiente de
        # _refresh_rgpd_buttons(), que solo gestiona los botones de
        # exportar/anonimizar y solo para administradores.
        employee = self._current_employee
        locked = employee is not None and employee.anonymized
        state = ["disabled"] if locked else ["!disabled"]
        self.save_button.state(state)
        self.change_photo_button.state(state)
        self.upload_document_button.state(state)
        self.generate_document_button.state(state)

    def _refresh_vacation_balance(self) -> None:
        employee = self._current_employee
        if employee is None:
            self.vacation_balance_label.configure(text="")
            return
        assert employee.id is not None
        annual_days = self._repos.app_settings.get_annual_vacation_days()
        if employee.active or employee.termination_date is None:
            year = date.today().year
            used_days = self._repos.absences.count_vacation_days_for_year(employee.id, year)
            balance = vacation.calculate_balance(employee.hire_date, year, annual_days, used_days)
        else:
            # Un empleado de baja no sigue devengando vacaciones después de
            # su fecha de baja -- el mismo criterio que ya usa el finiquito
            # (severance.py), solo que aquí es para mostrarlo en la ficha.
            # Sin esto, se mostraba el devengo completo del año en curso
            # (hasta el 31 de diciembre) para alguien que puede llevar
            # tiempo sin trabajar allí, sobrestimando los días "disponibles".
            year = employee.termination_date.year
            used_days = self._repos.absences.count_vacation_days_for_year(employee.id, year)
            balance = vacation.calculate_balance_up_to(
                employee.hire_date, employee.termination_date, annual_days, used_days
            )
        self.vacation_balance_label.configure(
            text=(
                f"Vacaciones {year}: usa {balance.used_days} de {balance.entitled_days:g} días "
                f"(quedan {balance.remaining_days:g})"
            )
        )

    def _handle_open_vacation_settings(self) -> None:
        VacationSettingsDialog(self, self._repos, on_change=self._refresh_vacation_balance)

    def _refresh_onboarding_checklist(self) -> None:
        for widget in self.onboarding_frame.winfo_children():
            widget.destroy()
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        statuses = self._repos.onboarding_tasks.checklist_for_employee(employee.id)
        if not statuses:
            ttk.Label(
                self.onboarding_frame,
                text="(sin tareas de incorporación definidas)",
                style="Muted.TLabel",
            ).pack(anchor="w")
            return
        for status in statuses:
            assert status.task.id is not None
            row_frame = ttk.Frame(self.onboarding_frame)
            row_frame.pack(anchor="w", fill="x")
            var = tk.BooleanVar(value=status.is_complete)
            ttk.Checkbutton(
                row_frame,
                text=status.task.name,
                variable=var,
                command=partial(self._handle_toggle_onboarding_task, status.task.id, var),
            ).pack(side="left")
            if status.completed_at is not None:
                ttk.Label(
                    row_frame,
                    text=f"  ({status.completed_at.strftime('%d/%m/%Y')})",
                    style="Muted.TLabel",
                ).pack(side="left")

    def _handle_toggle_onboarding_task(self, task_id: int, var: tk.BooleanVar) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        if var.get():
            self._repos.onboarding_tasks.mark_complete(employee.id, task_id, date.today())
        else:
            self._repos.onboarding_tasks.mark_incomplete(employee.id, task_id)
        self._refresh_onboarding_checklist()

    def _refresh_documents(self) -> None:
        self.documents_tree.delete(*self.documents_tree.get_children())
        self.documents_error_label.configure(text="")
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        for doc in self._repos.documents.list_for_employee(employee.id):
            self.documents_tree.insert(
                "",
                tk.END,
                iid=str(doc.id),
                values=(
                    doc.filename,
                    doc.category,
                    _format_file_size(doc.size_bytes),
                    doc.uploaded_at.strftime("%d/%m/%Y %H:%M"),
                ),
            )

    def _refresh_history(self) -> None:
        self.history_tree.delete(*self.history_tree.get_children())
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        for entry in self._repos.history.list_for_employee(employee.id):
            assert entry.id is not None
            self.history_tree.insert(
                "",
                tk.END,
                iid=str(entry.id),
                values=(
                    entry.effective_date.strftime("%d/%m/%Y"),
                    entry.position,
                    _format_currency(entry.salary),
                    entry.note,
                ),
            )

    def _refresh_accidents(self) -> None:
        self.accidents_tree.delete(*self.accidents_tree.get_children())
        self.accidents_error_label.configure(text="")
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        for accident in self._repos.work_accidents.list_for_employee(employee.id):
            assert accident.id is not None
            self.accidents_tree.insert(
                "",
                tk.END,
                iid=str(accident.id),
                values=(
                    accident.accident_date.strftime("%d/%m/%Y"),
                    accident.severity,
                    "Sí" if accident.caused_leave else "No",
                    "Sí" if accident.reported_to_authority else "No",
                    accident.description,
                ),
            )

    def _selected_accident_id(self) -> int | None:
        selection = self.accidents_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_register_accident(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            messagebox.showinfo(
                "Accidentes de trabajo",
                "Guarde primero la ficha del empleado antes de registrar un accidente.",
                parent=self,
            )
            return
        WorkAccidentDialog(
            self, self._repos, employee, on_change=self._refresh_accidents
        )

    def _handle_delete_accident(self) -> None:
        accident_id = self._selected_accident_id()
        if accident_id is None:
            self.accidents_error_label.configure(text="Seleccione un accidente para eliminar.")
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", "¿Eliminar este registro de accidente?", parent=self
        ):
            return
        try:
            accident = self._repos.work_accidents.get(accident_id)
            self._repos.work_accidents.delete(accident_id)
        except RepositoryError as exc:
            self.accidents_error_label.configure(text=str(exc))
            return
        employee_name = self._current_employee.full_name if self._current_employee else "?"
        self._repos.audit_log.record(
            AUDIT_WORK_ACCIDENT_DELETED,
            f"Empleado: {employee_name} — Fecha: {accident.accident_date.isoformat()}",
        )
        self._refresh_accidents()

    def _refresh_trainings(self) -> None:
        self.trainings_tree.delete(*self.trainings_tree.get_children())
        self.trainings_error_label.configure(text="")
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        for training in self._repos.trainings.list_for_employee(employee.id):
            assert training.id is not None
            self.trainings_tree.insert(
                "",
                tk.END,
                iid=str(training.id),
                values=(
                    training.name,
                    training.completion_date.strftime("%d/%m/%Y"),
                    training.expiration_date.strftime("%d/%m/%Y")
                    if training.expiration_date is not None
                    else "—",
                ),
            )

    def _selected_training_id(self) -> int | None:
        selection = self.trainings_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_add_training(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            messagebox.showinfo(
                "Formación y certificaciones",
                "Guarde primero la ficha del empleado antes de añadir formación.",
                parent=self,
            )
            return
        TrainingDialog(self, self._repos, employee, on_change=self._refresh_trainings)

    def _handle_delete_training(self) -> None:
        training_id = self._selected_training_id()
        if training_id is None:
            self.trainings_error_label.configure(text="Seleccione una formación para eliminar.")
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", "¿Eliminar este registro de formación?", parent=self
        ):
            return
        try:
            training = self._repos.trainings.get(training_id)
            self._repos.trainings.delete(training_id)
        except RepositoryError as exc:
            self.trainings_error_label.configure(text=str(exc))
            return
        employee_name = self._current_employee.full_name if self._current_employee else "?"
        self._repos.audit_log.record(
            AUDIT_TRAINING_DELETED, f"Empleado: {employee_name} — Nombre: {training.name}"
        )
        self._refresh_trainings()

    def _refresh_self_service_status(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            self.self_service_status_label.configure(text="")
            return
        has_pin = self._repos.employees.has_self_service_pin(employee.id)
        self.self_service_status_label.configure(
            text="PIN de acceso configurado." if has_pin else "Sin PIN de acceso configurado."
        )

    def _handle_set_self_service_pin(self) -> None:
        self.self_service_error_label.configure(text="")
        employee = self._current_employee
        if employee is None or employee.id is None:
            messagebox.showinfo(
                "Autoservicio",
                "Guarde primero la ficha del empleado antes de establecer un PIN.",
                parent=self,
            )
            return
        SetSelfServicePinDialog(
            self, self._repos, employee, on_change=self._handle_self_service_pin_changed
        )

    def _handle_self_service_pin_changed(self) -> None:
        assert self._current_employee is not None and self._current_employee.id is not None
        self._repos.audit_log.record(
            AUDIT_SELF_SERVICE_PIN_SET, f"Empleado: {self._current_employee.full_name}"
        )
        self._refresh_self_service_status()

    def _handle_clear_self_service_pin(self) -> None:
        self.self_service_error_label.configure(text="")
        employee = self._current_employee
        if employee is None or employee.id is None:
            messagebox.showinfo(
                "Autoservicio",
                "Guarde primero la ficha del empleado antes de gestionar su PIN.",
                parent=self,
            )
            return
        if not self._repos.employees.has_self_service_pin(employee.id):
            self.self_service_error_label.configure(text="Este empleado no tiene ningún PIN.")
            return
        if not messagebox.askyesno(
            "Confirmar",
            f"¿Quitar el PIN de autoservicio de {employee.full_name}? "
            "Dejará de poder consultar sus datos hasta que se le asigne uno nuevo.",
            parent=self,
        ):
            return
        self._repos.employees.clear_self_service_pin(employee.id)
        self._repos.audit_log.record(
            AUDIT_SELF_SERVICE_PIN_CLEARED, f"Empleado: {employee.full_name}"
        )
        self._refresh_self_service_status()

    def _refresh_objectives(self) -> None:
        self.objectives_tree.delete(*self.objectives_tree.get_children())
        self.objectives_error_label.configure(text="")
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        for objective in self._repos.objectives.list_for_employee(employee.id):
            assert objective.id is not None
            self.objectives_tree.insert(
                "",
                tk.END,
                iid=str(objective.id),
                values=(
                    objective.title,
                    objective.target_date.strftime("%d/%m/%Y"),
                    _OBJECTIVE_STATUS_LABELS[objective.status],
                ),
            )

    def _selected_objective_id(self) -> int | None:
        selection = self.objectives_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_add_objective(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            messagebox.showinfo(
                "Desempeño",
                "Guarde primero la ficha del empleado antes de añadir un objetivo.",
                parent=self,
            )
            return
        ObjectiveDialog(self, self._repos, employee, on_change=self._refresh_objectives)

    def _handle_change_objective_status(self) -> None:
        objective_id = self._selected_objective_id()
        if objective_id is None:
            self.objectives_error_label.configure(text="Seleccione un objetivo.")
            return
        objective = self._repos.objectives.get(objective_id)
        ChangeObjectiveStatusDialog(
            self, self._repos, objective, on_change=self._refresh_objectives
        )

    def _handle_delete_objective(self) -> None:
        objective_id = self._selected_objective_id()
        if objective_id is None:
            self.objectives_error_label.configure(text="Seleccione un objetivo para eliminar.")
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", "¿Eliminar este objetivo?", parent=self
        ):
            return
        try:
            objective = self._repos.objectives.get(objective_id)
            self._repos.objectives.delete(objective_id)
        except RepositoryError as exc:
            self.objectives_error_label.configure(text=str(exc))
            return
        employee_name = self._current_employee.full_name if self._current_employee else "?"
        self._repos.audit_log.record(
            AUDIT_OBJECTIVE_DELETED, f"Empleado: {employee_name} — Título: {objective.title}"
        )
        self._refresh_objectives()

    def _refresh_reviews(self) -> None:
        self.reviews_tree.delete(*self.reviews_tree.get_children())
        self.reviews_error_label.configure(text="")
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        for review in self._repos.performance_reviews.list_for_employee(employee.id):
            assert review.id is not None
            self.reviews_tree.insert(
                "",
                tk.END,
                iid=str(review.id),
                values=(review.review_date.strftime("%d/%m/%Y"), review.comments),
            )

    def _selected_review_id(self) -> int | None:
        selection = self.reviews_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_add_review(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            messagebox.showinfo(
                "Desempeño",
                "Guarde primero la ficha del empleado antes de añadir una evaluación.",
                parent=self,
            )
            return
        PerformanceReviewDialog(self, self._repos, employee, on_change=self._refresh_reviews)

    def _handle_delete_review(self) -> None:
        review_id = self._selected_review_id()
        if review_id is None:
            self.reviews_error_label.configure(text="Seleccione una evaluación para eliminar.")
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", "¿Eliminar esta evaluación?", parent=self
        ):
            return
        try:
            self._repos.performance_reviews.get(review_id)
            self._repos.performance_reviews.delete(review_id)
        except RepositoryError as exc:
            self.reviews_error_label.configure(text=str(exc))
            return
        employee_name = self._current_employee.full_name if self._current_employee else "?"
        self._repos.audit_log.record(
            AUDIT_PERFORMANCE_REVIEW_DELETED, f"Empleado: {employee_name}"
        )
        self._refresh_reviews()

    def _refresh_equipment(self) -> None:
        self.equipment_tree.delete(*self.equipment_tree.get_children())
        self.equipment_error_label.configure(text="")
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        for item in self._repos.assigned_equipment.list_for_employee(employee.id):
            assert item.id is not None
            self.equipment_tree.insert(
                "",
                tk.END,
                iid=str(item.id),
                values=(
                    item.description,
                    item.assigned_date.strftime("%d/%m/%Y"),
                    item.returned_date.strftime("%d/%m/%Y") if item.returned_date else "—",
                ),
            )

    def _selected_equipment_id(self) -> int | None:
        selection = self.equipment_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_add_equipment(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            messagebox.showinfo(
                "Equipo asignado",
                "Guarde primero la ficha del empleado antes de añadir equipo.",
                parent=self,
            )
            return
        EquipmentDialog(self, self._repos, employee, on_change=self._refresh_equipment)

    def _handle_mark_equipment_returned(self) -> None:
        equipment_id = self._selected_equipment_id()
        if equipment_id is None:
            self.equipment_error_label.configure(text="Seleccione un equipo.")
            return
        try:
            equipment = self._repos.assigned_equipment.get(equipment_id)
        except RepositoryError as exc:
            self.equipment_error_label.configure(text=str(exc))
            return
        MarkEquipmentReturnedDialog(
            self, self._repos, equipment, on_change=self._refresh_equipment
        )

    def _handle_delete_equipment(self) -> None:
        equipment_id = self._selected_equipment_id()
        if equipment_id is None:
            self.equipment_error_label.configure(text="Seleccione un equipo para eliminar.")
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", "¿Eliminar este registro de equipo?", parent=self
        ):
            return
        try:
            equipment = self._repos.assigned_equipment.get(equipment_id)
            self._repos.assigned_equipment.delete(equipment_id)
        except RepositoryError as exc:
            self.equipment_error_label.configure(text=str(exc))
            return
        employee_name = self._current_employee.full_name if self._current_employee else "?"
        self._repos.audit_log.record(
            AUDIT_EQUIPMENT_DELETED, f"Empleado: {employee_name} — Descripción: {equipment.description}"
        )
        self._refresh_equipment()

    def _refresh_it_episodes(self) -> None:
        self.it_episodes_tree.delete(*self.it_episodes_tree.get_children())
        self.it_episodes_error_label.configure(text="")
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        for episode in self._repos.it_episodes.list_for_employee(employee.id):
            assert episode.id is not None
            self.it_episodes_tree.insert(
                "",
                tk.END,
                iid=str(episode.id),
                values=(
                    episode.contingency,
                    episode.leave_date.strftime("%d/%m/%Y"),
                    episode.last_confirmation_date.strftime("%d/%m/%Y")
                    if episode.last_confirmation_date
                    else "",
                    episode.return_date.strftime("%d/%m/%Y") if episode.return_date else "En curso",
                ),
            )

    def _selected_it_episode_id(self) -> int | None:
        selection = self.it_episodes_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_register_it_episode(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            messagebox.showinfo(
                "Incapacidad temporal",
                "Guarde primero la ficha del empleado antes de registrar una baja por IT.",
                parent=self,
            )
            return
        ITEpisodeDialog(self, self._repos, employee, on_change=self._refresh_it_episodes)

    def _handle_view_it_episode(self) -> None:
        employee = self._current_employee
        episode_id = self._selected_it_episode_id()
        if employee is None or episode_id is None:
            self.it_episodes_error_label.configure(
                text="Seleccione un episodio para ver o gestionar."
            )
            return
        ITEpisodeDetailDialog(
            self, self._repos, employee, episode_id, on_change=self._refresh_it_episodes
        )

    def _selected_document_id(self) -> int | None:
        selection = self.documents_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_upload_document(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            messagebox.showinfo(
                "Documentos", "Guarde primero la ficha del empleado antes de adjuntar documentos.",
                parent=self,
            )
            return
        path_str = filedialog.askopenfilename(title="Elegir documento", parent=self)
        if not path_str:
            return
        path = Path(path_str)
        try:
            content = path.read_bytes()
        except OSError as exc:
            self.documents_error_label.configure(text=f"No se pudo leer el archivo: {exc}")
            return
        DocumentUploadDialog(
            self, self._repos, employee.id, path.name, content, on_change=self._refresh_documents
        )

    def _handle_generate_document(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            messagebox.showinfo(
                "Generar documento",
                "Guarde primero la ficha del empleado antes de generar un documento.",
                parent=self,
            )
            return
        templates = self._repos.document_templates.list_all()
        if not templates:
            messagebox.showinfo(
                "Generar documento",
                "Cree al menos una plantilla de documento (\"Plantillas de "
                "documentos...\" en la barra lateral) antes de generar uno.",
                parent=self,
            )
            return
        GenerateDocumentDialog(
            self, self._repos, employee, templates, on_change=self._refresh_documents
        )

    def _handle_download_document(self) -> None:
        document_id = self._selected_document_id()
        if document_id is None:
            self.documents_error_label.configure(text="Seleccione un documento para descargar.")
            return
        document = self._repos.documents.get(document_id)
        path_str = filedialog.asksaveasfilename(
            title="Guardar documento", initialfile=document.filename, parent=self
        )
        if not path_str:
            return
        try:
            Path(path_str).write_bytes(document.content)
        except OSError as exc:
            self.documents_error_label.configure(text=f"No se pudo guardar el archivo: {exc}")
            return
        self.documents_error_label.configure(text="")

    def _handle_delete_document(self) -> None:
        document_id = self._selected_document_id()
        if document_id is None:
            self.documents_error_label.configure(text="Seleccione un documento para eliminar.")
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", "¿Eliminar este documento?", parent=self
        ):
            return
        try:
            document = self._repos.documents.get(document_id)
            self._repos.documents.delete(document_id)
        except RepositoryError as exc:
            self.documents_error_label.configure(text=str(exc))
            return
        employee_name = self._current_employee.full_name if self._current_employee else "?"
        self._repos.audit_log.record(
            AUDIT_DOCUMENT_DELETED, f"Empleado: {employee_name} — Archivo: {document.filename}"
        )
        self._refresh_documents()

    def _refresh_photo_display(self) -> None:
        display_name = self.name_heading.cget("text") or "?"
        try:
            if self._photo_bytes is not None:
                tk_image = photo_to_tk_image(self._photo_bytes, PHOTO_DISPLAY_SIZE)
            else:
                tk_image = placeholder_tk_image(display_name, PHOTO_DISPLAY_SIZE)
        except Exception:
            # Defensive UI boundary: never let a corrupt/unreadable stored photo
            # crash the ficha — fall back to the initials placeholder instead.
            tk_image = placeholder_tk_image(display_name, PHOTO_DISPLAY_SIZE)
        self._tk_photo_ref = tk_image
        self.photo_label.configure(image=tk_image)
        self.remove_photo_button.state(["!disabled" if self._photo_bytes else "disabled"])

    def _handle_change_photo(self) -> None:
        path_str = filedialog.askopenfilename(
            title="Elegir foto", filetypes=SUPPORTED_FILE_TYPES, parent=self
        )
        if not path_str:
            return
        try:
            processed = process_uploaded_photo(Path(path_str))
        except PhotoProcessingError as exc:
            messagebox.showerror("Foto no válida", str(exc), parent=self)
            return

        if self._current_employee is not None:
            assert self._current_employee.id is not None
            employee_id = self._current_employee.id
            self._repos.employees.set_photo(employee_id, processed)
            self._current_employee = self._repos.employees.get(employee_id)
            self._on_saved(employee_id)
        self._photo_bytes = processed
        self._photo_dirty = True
        self._refresh_photo_display()

    def _handle_remove_photo(self) -> None:
        if self._current_employee is not None:
            assert self._current_employee.id is not None
            employee_id = self._current_employee.id
            self._repos.employees.set_photo(employee_id, None)
            self._current_employee = self._repos.employees.get(employee_id)
            self._on_saved(employee_id)
        self._photo_bytes = None
        self._photo_dirty = True
        self._refresh_photo_display()

    def _handle_save(self) -> None:
        department_id = self._selected_department_id()
        if department_id is None:
            self._show_error("Debe seleccionar un departamento.")
            return

        shift_index = self.shift_combo.current()
        shift_id = self._shifts[shift_index - 1].id if shift_index > 0 else None

        manager_index = self.manager_combo.current()
        manager_id = (
            self._manager_candidates[manager_index - 1].id if manager_index > 0 else None
        )

        professional_category_index = self.professional_category_combo.current()
        professional_category_id = (
            self._professional_categories[professional_category_index - 1].id
            if professional_category_index > 0
            else None
        )

        head_of_department_id: int | None = None
        if self.is_department_head_var.get():
            head_index = self.head_of_department_combo.current()
            if head_index == -1:
                self._show_error("Seleccione de qué departamento es encargado/a.")
                return
            head_of_department_id = self._departments[head_index].id

        salary_text = self.salary_var.get().strip().replace(",", ".")
        try:
            salary = float(salary_text)
        except ValueError:
            self._show_error("El salario debe ser un número, por ejemplo 30000.50")
            return

        data = EmployeeInput(
            first_name=self.first_name_var.get(),
            last_name=self.last_name_var.get(),
            email=self.email_var.get(),
            phone=self.phone_var.get(),
            position=self.position_var.get(),
            department_id=department_id,
            salary=salary,
            hire_date=self.hire_date_entry.get(),
            shift_id=shift_id,
            bank_account=self.bank_account_var.get(),
            dependent_children=self.dependent_children_var.get(),
            # El estado activo/inactivo ya no se edita aquí (checkbox
            # retirado): solo lo cambian "Dar de baja..."/"Reactivar", para
            # que un empleado inactivo nunca quede sin fecha ni motivo de
            # baja registrados. Guardar cambios simplemente preserva lo que
            # ya había.
            active=(self._current_employee.active if self._current_employee is not None else True),
            dni_nie=self.dni_nie_var.get(),
            ss_number=self.ss_number_var.get(),
            contract_type=self.contract_type_combo.get(),
            contract_end_date=(
                "" if self.no_end_date_var.get() else self.contract_end_date_entry.get()
            ),
            birth_date=("" if self.no_birth_date_var.get() else self.birth_date_entry.get()),
            next_medical_checkup_date=(
                "" if self.no_medical_checkup_var.get() else self.next_medical_checkup_entry.get()
            ),
            prl_training_date=(
                "" if self.no_prl_training_var.get() else self.prl_training_entry.get()
            ),
            manager_id=manager_id,
            head_of_department_id=head_of_department_id,
            professional_category_id=professional_category_id,
        )

        is_new = self._current_employee is None
        try:
            if self._current_employee is None:
                saved = self._repos.employees.create(data)
            else:
                assert self._current_employee.id is not None
                saved = self._repos.employees.update(self._current_employee.id, data)
        except (validation.ValidationError, RepositoryError) as exc:
            self._show_error(str(exc))
            return

        assert saved.id is not None
        employee_id = saved.id
        if is_new:
            # Solo el ALTA se audita, no cada "Guardar cambios" rutinario
            # (editar un teléfono, etc.) -- ver el comentario en
            # AuditLogRepository sobre por qué eso generaría demasiado ruido.
            self._repos.audit_log.record(AUDIT_EMPLOYEE_CREATED, f"Empleado: {saved.full_name}")
        if self._photo_dirty:
            self._repos.employees.set_photo(employee_id, self._photo_bytes)
            saved = self._repos.employees.get(employee_id)

        self.show_employee(saved)
        self._on_saved(employee_id)

    def _handle_delete(self) -> None:
        if self._current_employee is None:
            return
        employee = self._current_employee
        if not messagebox.askyesno(
            "Confirmar eliminación",
            f"¿Eliminar a {employee.full_name}? Esta acción no se puede deshacer.",
            parent=self,
        ):
            return
        assert employee.id is not None
        try:
            self._repos.employees.delete(employee.id)
        except RepositoryError as exc:
            messagebox.showerror("Error al eliminar", str(exc), parent=self)
            return
        self._repos.audit_log.record(AUDIT_EMPLOYEE_DELETED, f"Empleado: {employee.full_name}")
        self.show_employee(None)
        self._on_deleted()

    def _handle_view_calendar(self) -> None:
        if self._current_employee is None:
            return
        self._on_view_calendar(self._current_employee)

    def _handle_terminate(self) -> None:
        if self._current_employee is None:
            return
        TerminationDialog(self, self._repos, self._current_employee, on_change=self._handle_termination_change)

    def _handle_termination_change(self, employee_id: int) -> None:
        self._current_employee = self._repos.employees.get(employee_id)
        self.show_employee(self._current_employee)
        self._on_saved(employee_id)

    def _handle_reactivate(self) -> None:
        if self._current_employee is None:
            return
        employee = self._current_employee
        if not messagebox.askyesno(
            "Reactivar empleado",
            f"¿Reactivar a {employee.full_name}? Volverá a aparecer como activo.",
            parent=self,
        ):
            return
        assert employee.id is not None
        try:
            updated = self._repos.employees.reactivate(employee.id)
        except RepositoryError as exc:
            self._show_error(str(exc))
            return
        self._repos.audit_log.record(
            AUDIT_EMPLOYEE_REACTIVATED, f"Empleado: {updated.full_name}"
        )
        assert updated.id is not None
        self.show_employee(updated)
        self._on_saved(updated.id)

    def _handle_view_severance(self) -> None:
        if self._current_employee is None or self._current_employee.id is None:
            return
        settlements = self._repos.severance_settlements.list_for_employee(
            self._current_employee.id
        )
        if not settlements:
            return
        SeveranceViewDialog(self, self._current_employee, settlements)

    def _handle_export_data(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        path_str = filedialog.asksaveasfilename(
            title="Exportar datos (RGPD)",
            defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")],
            initialfile=f"datos_{employee.id}.zip",
            parent=self,
        )
        if not path_str:
            return
        zip_bytes = export_employee_data(self._repos, employee.id)
        try:
            Path(path_str).write_bytes(zip_bytes)
        except OSError as exc:
            self._show_error(f"No se pudo guardar el archivo: {exc}")
            return
        self._repos.audit_log.record(AUDIT_DATA_EXPORTED, f"Empleado: {employee.full_name}")
        self._show_error("")
        messagebox.showinfo("Exportar datos", "Datos exportados correctamente.", parent=self)

    def _handle_anonymize(self) -> None:
        employee = self._current_employee
        if employee is None or employee.id is None:
            return
        if not messagebox.askyesno(
            "Anonimizar datos",
            f"¿Anonimizar los datos de {employee.full_name}?\n\n"
            "Se borrarán de forma permanente el nombre, email, teléfono, "
            "DNI/NIE, número de Seguridad Social, cuenta bancaria, fecha de "
            "nacimiento, próxima revisión médica, foto y documentos "
            "adjuntos. Los datos estructurales (puesto, departamento, "
            "salario, fechas laborales) se conservan por obligación legal. "
            "Un empleado anonimizado ya no se puede editar.\n\n"
            "Esta acción no se puede deshacer.",
            parent=self,
            icon="warning",
        ):
            return
        try:
            updated = self._repos.employees.anonymize(employee.id)
        except RepositoryError as exc:
            self._show_error(str(exc))
            return
        # Deliberadamente sin el nombre (a diferencia del resto de acciones
        # auditadas): guardar aquí el nombre original dejaría la propia
        # entrada de auditoría -- inmutable, sin fecha de caducidad -- como
        # un registro permanente de la identidad que se acaba de anonimizar,
        # contradiciendo el propósito de la propia acción.
        assert updated.id is not None
        self._repos.audit_log.record(AUDIT_EMPLOYEE_ANONYMIZED, f"Empleado id {updated.id}")
        self.show_employee(updated)
        self._on_saved(updated.id)

    def _show_error(self, message: str) -> None:
        self.error_label.configure(text=message)


class EmployeePage(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        on_view_calendar: Callable[[Employee], None],
        locked_department_id: int | None = None,
        is_admin: bool = True,
    ) -> None:
        super().__init__(parent)
        self._repos = repos
        self._on_view_calendar = on_view_calendar
        self._locked_department_id = locked_department_id
        self._is_admin = is_admin
        self._departments: list[Department] = []
        self._departments_by_id: dict[int, Department] = {}
        self._current_results: list[Employee] = []
        self._sort_column = "nombre"
        self._sort_reverse = False

        self._build_widgets()
        self.reload_departments()
        self.refresh_employees()

    def _build_widgets(self) -> None:
        # Panedwindow (no pack de ancho fijo) para que el usuario pueda
        # arrastrar el separador. 660px (no 580): con las columnas
        # Puesto/Departamento ensanchadas (ver _COLUMNS) 580 se quedaba
        # corto incluso para las propias cabeceras ("Departamento" con su
        # flecha de orden no cabía en 90px); 660 es la suma real de las 6
        # columnas más el margen del propio Treeview (scrollbar + padding),
        # verificado en vivo tras el primer intento a 620 quedarse aún
        # unos px corto. Sigue sin caber cualquier valor largo posible --
        # para eso el usuario puede seguir arrastrando el separador, o cada
        # columna del Treeview por su cuenta -- pero ya no recorta la
        # cabecera en sí.
        self._paned = ttk.Panedwindow(self, orient="horizontal")
        self._paned.pack(side="top", fill="both", expand=True)

        list_frame = ttk.Frame(self._paned, padding=(12, 12, 6, 12), width=660)
        self._paned.add(list_frame, weight=0)
        list_frame.pack_propagate(False)

        filter_row = ttk.Frame(list_frame)
        filter_row.pack(side="top", fill="x")
        ttk.Label(filter_row, text="Buscar:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(filter_row, textvariable=self.search_var, width=18)
        self.search_entry.pack(side="left", padx=(4, 0))
        self.search_entry.bind("<KeyRelease>", lambda _e: self.refresh_employees())

        filter_row2 = ttk.Frame(list_frame)
        filter_row2.pack(side="top", fill="x", pady=(6, 0))
        ttk.Label(filter_row2, text="Depto:").pack(side="left")
        self.department_filter_var = tk.StringVar(value="Todos")
        self.department_filter_combo = ttk.Combobox(
            filter_row2,
            state="disabled" if self._locked_department_id is not None else "readonly",
            width=13,
            textvariable=self.department_filter_var,
            values=["Todos"],
        )
        self.department_filter_combo.pack(side="left", padx=(4, 8))
        self.department_filter_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self.refresh_employees()
        )

        ttk.Label(filter_row2, text="Estado:").pack(side="left")
        self.active_filter_var = tk.StringVar(value="Todos")
        active_combo = ttk.Combobox(
            filter_row2,
            state="readonly",
            width=9,
            textvariable=self.active_filter_var,
            values=_ACTIVE_FILTER_OPTIONS,
        )
        active_combo.pack(side="left", padx=(4, 0))
        active_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_employees())

        tree_frame = ttk.Frame(list_frame)
        tree_frame.pack(side="top", fill="both", expand=True, pady=(8, 0))
        columns = tuple(col for col, _label, _width in _COLUMNS)
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        for col, _label, width in _COLUMNS:
            self.tree.heading(col, command=partial(self._handle_sort_click, col))
            self.tree.column(col, width=width, anchor="w")
        self._update_heading_labels()
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._handle_selection_changed())

        self.status_label = ttk.Label(list_frame, text="")
        self.status_label.pack(side="top", anchor="w", pady=(4, 0))

        ttk.Button(
            list_frame,
            text="+ Nuevo empleado",
            command=self._handle_new,
            style="Accent.TButton",
        ).pack(side="top", fill="x", pady=(8, 0))

        self.ficha = EmployeeFichaPanel(
            self._paned,
            self._repos,
            on_saved=self._handle_ficha_saved,
            on_deleted=self._handle_ficha_deleted,
            on_view_calendar=self._on_view_calendar,
            locked_department_id=self._locked_department_id,
            is_admin=self._is_admin,
        )
        # Sin minsize (a diferencia de la vieja tk.PanedWindow, ttk::panedwindow
        # solo acepta "weight" como opción de panel -- comprobado contra el
        # propio docstring de tkinter.ttk.Panedwindow.pane() antes de
        # insistir, tras dos intentos fallidos con TclError): el usuario
        # puede seguir arrastrando el separador libremente, igual que
        # siempre. El ancho por defecto ya mejorado (ventana 1360x760 +
        # lista fija a 620px) es lo que evita el caso realmente reportado.
        self._paned.add(self.ficha, weight=1)

    def apply_theme_change(self) -> None:
        self.ficha.apply_theme_change()

    def reload_departments(self) -> None:
        self._departments = self._repos.departments.list_all()
        self._departments_by_id = {d.id: d for d in self._departments if d.id is not None}
        if self._locked_department_id is not None:
            names = [self._departments_by_id[self._locked_department_id].name]
            self.department_filter_var.set(names[0])
        else:
            names = ["Todos"] + [d.name for d in self._departments]
            if self.department_filter_var.get() not in names:
                self.department_filter_var.set("Todos")
        self.department_filter_combo.configure(values=names)
        self.ficha.reload_departments()

    def reload_professional_categories(self) -> None:
        self.ficha.reload_professional_categories()

    def _selected_department_filter_id(self) -> int | None:
        if self._locked_department_id is not None:
            return self._locked_department_id
        name = self.department_filter_var.get()
        for dept in self._departments:
            if dept.name == name:
                return dept.id
        return None

    def _selected_active_filter(self) -> bool | None:
        value = self.active_filter_var.get()
        if value == "Activos":
            return True
        if value == "Inactivos":
            return False
        return None

    def _handle_sort_click(self, column: str) -> None:
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False
        self._update_heading_labels()
        self.refresh_employees()

    def _update_heading_labels(self) -> None:
        for col, label, _width in _COLUMNS:
            if col == self._sort_column:
                arrow = _SORT_ARROW_DESC if self._sort_reverse else _SORT_ARROW_ASC
                self.tree.heading(col, text=label + arrow)
            else:
                self.tree.heading(col, text=label)

    def _sort_key(self, employee: Employee, today: date) -> str:
        column = self._sort_column
        if column == "nombre":
            return f"{employee.last_name.lower()}\x00{employee.first_name.lower()}"
        if column == "puesto":
            return employee.position.lower()
        if column == "departamento":
            department = self._departments_by_id.get(employee.department_id)
            return department.name.lower() if department else ""
        if column == "salario":
            return f"{round(employee.salary * 100):012d}"
        if column == "antiguedad":
            return f"{(today - employee.hire_date).days:010d}"
        if column == "estado":
            return _STATUS_LABELS[employee.active]
        raise AssertionError(f"columna de orden desconocida: {column}")

    def refresh_employees(self) -> None:
        results = self._repos.employees.search(
            query=self.search_var.get(),
            department_id=self._selected_department_filter_id(),
            active_only=self._selected_active_filter(),
        )
        today = date.today()
        results = sorted(
            results, key=lambda e: self._sort_key(e, today), reverse=self._sort_reverse
        )
        self._current_results = results

        self.tree.delete(*self.tree.get_children())
        for emp in results:
            department_name = self._departments_by_id.get(emp.department_id)
            self.tree.insert(
                "",
                tk.END,
                iid=str(emp.id),
                values=(
                    emp.full_name,
                    emp.position,
                    department_name.name if department_name else "?",
                    _format_currency(emp.salary),
                    _format_seniority(emp.hire_date, today),
                    _STATUS_LABELS[emp.active],
                ),
            )
        self.status_label.configure(text=f"{len(results)} empleado(s)")

    def _selected_employee_id(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_selection_changed(self) -> None:
        employee_id = self._selected_employee_id()
        if employee_id is None:
            return
        # search()/list_all() never include photo bytes (kept cheap for the
        # list); fetch the full record so the ficha can show the real photo.
        full_employee = self._repos.employees.get(employee_id)
        self.ficha.show_employee(full_employee)

    def _handle_new(self) -> None:
        if not self._departments:
            messagebox.showinfo(
                "Sin departamentos",
                "Primero debe crear al menos un departamento (sección Departamentos).",
                parent=self,
            )
            return
        selection = self.tree.selection()
        if selection:
            self.tree.selection_remove(*selection)
        self.ficha.show_employee(None)

    def _handle_ficha_saved(self, employee_id: int) -> None:
        self.refresh_employees()
        iid = str(employee_id)
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def _handle_ficha_deleted(self) -> None:
        self.refresh_employees()

    def export_current_results(self) -> list[Employee]:
        return self._current_results

    def departments_by_id(self) -> dict[int, Department]:
        return self._departments_by_id

    def focus_search(self) -> None:
        self.search_entry.focus_set()
