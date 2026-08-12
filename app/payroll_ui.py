from __future__ import annotations

import os as os
import tempfile as tempfile
import tkinter as tk
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app import theme, validation
from app.calendar_widget import MONTH_NAMES, DateEntry, ScrollableFrame, shift_month
from app.gestoria_export import build_gestoria_rows, write_gestoria_csv
from app.models import Department, Employee
from app.payroll import MonthlyPayroll, calculate_monthly_payroll, estimate_irpf_withholding_rate
from app.payroll_pdf import CompanyInfo, build_payroll_pdf
from app.repository import Repositories, RepositoryError
from app.sepa_export import SepaPayment, build_sepa_payments, build_sepa_xml
from app.window_utils import center_window

def _format_currency(value: float) -> str:
    # employee_page._format_currency -- se duplica en vez de importarse
    # (ver el comentario allí sobre por qué). Formato español (punto de
    # millar, coma decimal) sin depender del módulo locale, que es global
    # al proceso y no debe tocarse por esto. Antes de este fix, esta
    # página era la única de toda la app que mostraba importes con el
    # formato de EE. UU. (f"{v:,.2f}" sin más) en vez de este.
    us_formatted = f"{value:,.2f}"
    integer_part, decimal_part = us_formatted.split(".")
    integer_part = integer_part.replace(",", ".")
    return f"{integer_part},{decimal_part} €"


def _cleanup_stale_print_files(directory: Path, max_age_seconds: float = 3600) -> None:
    """Best-effort: borra ficheros de `directory` con más de max_age_seconds
    de antigüedad. Se llama justo antes de escribir un PDF nuevo para
    imprimir (_handle_print_pdf) -- no se puede borrar el PDF recién escrito
    justo después de os.startfile(..., "print") porque esa llamada es
    asíncrona (el visor de PDF puede seguir leyéndolo un rato); dejarlo para
    siempre en el temporal compartido del sistema tampoco vale, porque
    acumula nóminas reales (salario, DNI, número de SS) indefinidamente.
    Cada fichero se intenta borrar por separado -- si uno sigue abierto por
    un visor (justo el caso que esto existe para tolerar) no debe impedir
    limpiar el resto."""
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


DISCLAIMER_TEXT = (
    "⚠ Estimación orientativa, no es una nómina oficial ni válida para presentar "
    "impuestos. Usa solo la escala estatal de retención (sin tramo autonómico) y un "
    "mínimo personal y familiar simplificado (no incluye discapacidad ni ascendientes "
    "a cargo). Verifica siempre con tu gestoría antes de pagar una nómina real."
)

_SUPPLEMENT_TYPE_LABELS = {
    "plus": "Plus",
    "horas_extra": "Horas extra",
    "anticipo": "Anticipo",
    "dietas": "Dietas",
    "bonos": "Bonos",
}
_SUPPLEMENT_TYPE_BY_LABEL = {label: key for key, label in _SUPPLEMENT_TYPE_LABELS.items()}

DIETAS_DISCLAIMER_TEXT = (
    "⚠ Se asume que el importe está dentro de los límites legales diarios "
    "exentos de IRPF y cotización a la Seguridad Social. Esta app no valida "
    "esos límites (cambian cada año y según haya o no pernoctación o viaje "
    "internacional) -- verifica los vigentes con tu gestoría."
)


class PayrollSettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, repos: Repositories, on_change: Callable[[], None]) -> None:
        super().__init__(parent)
        self.title("Configurar porcentajes de Seguridad Social")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._on_change = on_change
        settings = repos.payroll_settings.get()

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Seguridad Social trabajador (%)").grid(
            row=0, column=0, sticky="w", padx=6, pady=4
        )
        self.ss_employee_var = tk.StringVar(value=f"{settings.ss_employee_pct:.2f}")
        ttk.Entry(frame, textvariable=self.ss_employee_var, width=10).grid(
            row=0, column=1, sticky="w", padx=6, pady=4
        )

        ttk.Label(frame, text="Seguridad Social empresa (%)").grid(
            row=1, column=0, sticky="w", padx=6, pady=4
        )
        self.ss_employer_var = tk.StringVar(value=f"{settings.ss_employer_pct:.2f}")
        ttk.Entry(frame, textvariable=self.ss_employer_var, width=10).grid(
            row=1, column=1, sticky="w", padx=6, pady=4
        )

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
            ss_employee = float(self.ss_employee_var.get().strip().replace(",", "."))
            ss_employer = float(self.ss_employer_var.get().strip().replace(",", "."))
        except ValueError:
            self.error_label.configure(text="Los porcentajes deben ser números, ej. 6.35")
            return
        try:
            self._repos.payroll_settings.update(ss_employee, ss_employer)
        except validation.ValidationError as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class SepaExportDialog(tk.Toplevel):
    """Genera un fichero SEPA (pain.001, ver app/sepa_export.py) para pagar
    por lote las nóminas YA GENERADAS del mes que se esté viendo en
    Nóminas -- mismo criterio que Coste de personal: nunca una estimación
    en vivo. Solo administradores (como "Configurar % Seguridad
    Social..."): pagar nóminas es una acción de toda la empresa, no de un
    departamento suelto, así que no respeta el alcance por departamento de
    un encargado."""

    def __init__(self, parent: tk.Misc, repos: Repositories, year: int, month: int) -> None:
        super().__init__(parent)
        self.title(f"Exportar SEPA — {MONTH_NAMES[month - 1]} {year}")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._year = year
        self._month = month
        self._payments: list[SepaPayment] = []

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame, text="Datos de la empresa (como pagadora)", style="PageHeading.TLabel"
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(frame, text="Nombre").grid(row=1, column=0, sticky="w", pady=3)
        self.company_name_var = tk.StringVar(value=repos.app_settings.get_company_name())
        ttk.Entry(frame, textvariable=self.company_name_var, width=36).grid(
            row=1, column=1, sticky="w", pady=3
        )
        ttk.Label(frame, text="IBAN").grid(row=2, column=0, sticky="w", pady=3)
        self.company_iban_var = tk.StringVar(value=repos.app_settings.get_company_iban())
        ttk.Entry(frame, textvariable=self.company_iban_var, width=36).grid(
            row=2, column=1, sticky="w", pady=3
        )
        ttk.Label(frame, text="NIF / CIF").grid(row=3, column=0, sticky="w", pady=3)
        self.company_nif_var = tk.StringVar(value=repos.app_settings.get_company_nif())
        ttk.Entry(frame, textvariable=self.company_nif_var, width=36).grid(
            row=3, column=1, sticky="w", pady=3
        )
        # C.C.C. y domicilio: no hacen falta para el fichero SEPA en sí (por
        # eso viven en este mismo diálogo en vez de uno nuevo -- ver
        # app/payroll_pdf.py), pero sí para la cabecera de la nómina en PDF.
        ttk.Label(frame, text="C.C.C. (cotización)").grid(row=4, column=0, sticky="w", pady=3)
        self.company_ccc_var = tk.StringVar(value=repos.app_settings.get_company_ccc())
        ttk.Entry(frame, textvariable=self.company_ccc_var, width=36).grid(
            row=4, column=1, sticky="w", pady=3
        )
        ttk.Label(frame, text="Domicilio").grid(row=5, column=0, sticky="w", pady=3)
        self.company_address_var = tk.StringVar(value=repos.app_settings.get_company_address())
        ttk.Entry(frame, textvariable=self.company_address_var, width=36).grid(
            row=5, column=1, sticky="w", pady=3
        )
        ttk.Button(
            frame, text="Guardar datos de la empresa", command=self._handle_save_company
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.company_error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=420)
        self.company_error_label.grid(row=7, column=0, columnspan=2, sticky="w", pady=(2, 0))

        ttk.Separator(frame, orient="horizontal").grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=12
        )

        ttk.Label(frame, text="Fecha de ejecución solicitada").grid(
            row=9, column=0, sticky="w", pady=3
        )
        self.execution_date = DateEntry(
            frame, initial=date.today() + timedelta(days=1), min_date=date.today()
        )
        self.execution_date.grid(row=9, column=1, sticky="w", pady=3)

        ttk.Label(
            frame,
            text=f"Nóminas generadas de {MONTH_NAMES[month - 1]} {year}",
            style="PageHeading.TLabel",
        ).grid(row=10, column=0, columnspan=2, sticky="w", pady=(12, 4))

        tree_frame = ttk.Frame(frame)
        tree_frame.grid(row=11, column=0, columnspan=2, sticky="nsew")
        self.tree = ttk.Treeview(
            tree_frame, columns=("empleado", "iban", "importe"), show="headings", height=8
        )
        self.tree.heading("empleado", text="Empleado")
        self.tree.column("empleado", width=170, anchor="w")
        self.tree.heading("iban", text="IBAN")
        self.tree.column("iban", width=210, anchor="w")
        self.tree.heading("importe", text="Importe neto")
        self.tree.column("importe", width=100, anchor="e")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.summary_label = ttk.Label(
            frame, text="", style="Muted.TLabel", wraplength=480, justify="left"
        )
        self.summary_label.grid(row=12, column=0, columnspan=2, sticky="w", pady=(6, 0))

        button_row = ttk.Frame(frame)
        button_row.grid(row=13, column=0, columnspan=2, pady=(12, 0))
        self.export_button = ttk.Button(
            button_row,
            text="Generar fichero SEPA...",
            command=self._handle_export,
            style="Accent.TButton",
        )
        self.export_button.pack(side="left", padx=(0, 6))
        ttk.Button(button_row, text="Cerrar", command=self.destroy).pack(side="left")
        self.export_error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=480)
        self.export_error_label.grid(row=14, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._load_preview()

    def _load_preview(self) -> None:
        records = self._repos.payroll_records.list_for_month(self._year, self._month)
        payroll_rows: list[tuple[int, str, str, float]] = []
        for record in records:
            employee = self._repos.employees.get(record.employee_id)
            payroll_rows.append(
                (
                    record.employee_id,
                    employee.full_name,
                    employee.bank_account,
                    record.payroll.neto,
                )
            )
        result = build_sepa_payments(payroll_rows)
        self._payments = result.payments

        self.tree.delete(*self.tree.get_children())
        for payment in result.payments:
            self.tree.insert(
                "",
                "end",
                iid=str(payment.employee_id),
                values=(payment.employee_name, payment.iban, _format_currency(payment.amount)),
            )

        if not records:
            self.summary_label.configure(
                text=(
                    "No hay ninguna nómina generada para este mes — "
                    "genera las nóminas primero en esta misma página."
                )
            )
        else:
            total = sum(p.amount for p in result.payments)
            lines = [f"{len(result.payments)} pago(s), {_format_currency(total)} en total."]
            if result.skipped:
                lines.append(f"{len(result.skipped)} omitido(s):")
                lines.extend(f"  • {reason}" for reason in result.skipped)
            self.summary_label.configure(text="\n".join(lines))
        self.export_button.state(["!disabled"] if self._payments else ["disabled"])

    def _handle_save_company(self) -> None:
        try:
            self._repos.app_settings.set_company_name(self.company_name_var.get())
            self._repos.app_settings.set_company_iban(self.company_iban_var.get())
            self._repos.app_settings.set_company_nif(self.company_nif_var.get())
            self._repos.app_settings.set_company_ccc(self.company_ccc_var.get())
            self._repos.app_settings.set_company_address(self.company_address_var.get())
        except validation.ValidationError as exc:
            self.company_error_label.configure(text=str(exc))
            return
        self.company_error_label.configure(text="")
        self.company_name_var.set(self._repos.app_settings.get_company_name())
        self.company_iban_var.set(self._repos.app_settings.get_company_iban())
        self.company_nif_var.set(self._repos.app_settings.get_company_nif())
        self.company_ccc_var.set(self._repos.app_settings.get_company_ccc())
        self.company_address_var.set(self._repos.app_settings.get_company_address())

    def _handle_export(self) -> None:
        if not self._payments:
            return
        try:
            execution_date = date.fromisoformat(self.execution_date.get())
        except ValueError:
            self.export_error_label.configure(text="Fecha de ejecución inválida.")
            return
        message_id = f"NOM{datetime.now():%Y%m%d%H%M%S}"
        try:
            xml_content = build_sepa_xml(
                self._payments,
                company_name=self.company_name_var.get(),
                company_iban=self.company_iban_var.get(),
                requested_execution_date=execution_date,
                message_id=message_id,
                created_at=datetime.now(),
            )
        except ValueError as exc:
            self.export_error_label.configure(text=str(exc))
            return
        path_str = filedialog.asksaveasfilename(
            title="Guardar fichero SEPA",
            defaultextension=".xml",
            filetypes=[("XML", "*.xml")],
            initialfile=f"sepa_nominas_{self._year}{self._month:02d}.xml",
            parent=self,
        )
        if not path_str:
            return
        try:
            Path(path_str).write_text(xml_content, encoding="utf-8")
        except OSError as exc:
            self.export_error_label.configure(text=str(exc))
            return
        self.export_error_label.configure(text="")
        messagebox.showinfo(
            "SEPA",
            f"Fichero generado con {len(self._payments)} pago(s).\n"
            "Súbelo a la banca online de la empresa para ejecutarlo -- "
            "esta aplicación no envía dinero ni se conecta a ningún banco.",
            parent=self,
        )


class PayrollSupplementDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee_id: int,
        year: int,
        month: int,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Añadir complemento")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee_id = employee_id
        self._year = year
        self._month = month
        self._on_change = on_change

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Tipo *").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.type_var = tk.StringVar(value=_SUPPLEMENT_TYPE_LABELS["plus"])
        type_combo = ttk.Combobox(
            frame,
            state="readonly",
            width=24,
            textvariable=self.type_var,
            values=list(_SUPPLEMENT_TYPE_LABELS.values()),
        )
        type_combo.grid(row=0, column=1, padx=6, pady=4)
        type_combo.bind("<<ComboboxSelected>>", lambda _e: self._handle_type_changed())

        ttk.Label(frame, text="Descripción *").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.description_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.description_var, width=28).grid(
            row=1, column=1, padx=6, pady=4
        )

        # Importe (plus/anticipo) y horas+precio (horas extra) son mutuamente
        # excluyentes -- se crean ambos pares de widgets pero solo uno se
        # muestra a la vez en la fila 2/3 según el tipo elegido.
        self.amount_label = ttk.Label(frame, text="Importe (€) *")
        self.amount_var = tk.StringVar()
        self.amount_entry = ttk.Entry(frame, textvariable=self.amount_var, width=28)

        self.hours_label = ttk.Label(frame, text="Horas *")
        self.hours_var = tk.StringVar()
        self.hours_entry = ttk.Entry(frame, textvariable=self.hours_var, width=28)

        self.rate_label = ttk.Label(frame, text="Precio/hora (€) *")
        self.rate_var = tk.StringVar()
        self.rate_entry = ttk.Entry(frame, textvariable=self.rate_var, width=28)

        self.dietas_note_label = ttk.Label(
            frame, text=DIETAS_DISCLAIMER_TEXT, style="Muted.TLabel", wraplength=300, justify="left"
        )

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=300)
        self.error_label.grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 0))

        button_row = ttk.Frame(frame)
        button_row.grid(row=6, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row, text="Guardar", command=self._handle_save, style="Accent.TButton"
        ).pack(side="left", padx=4)
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left", padx=4)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

        self._handle_type_changed()

    def _handle_type_changed(self) -> None:
        if self.type_var.get() == _SUPPLEMENT_TYPE_LABELS["horas_extra"]:
            self.amount_label.grid_remove()
            self.amount_entry.grid_remove()
            self.hours_label.grid(row=2, column=0, sticky="w", padx=6, pady=4)
            self.hours_entry.grid(row=2, column=1, padx=6, pady=4)
            self.rate_label.grid(row=3, column=0, sticky="w", padx=6, pady=4)
            self.rate_entry.grid(row=3, column=1, padx=6, pady=4)
        else:
            self.hours_label.grid_remove()
            self.hours_entry.grid_remove()
            self.rate_label.grid_remove()
            self.rate_entry.grid_remove()
            self.amount_label.grid(row=2, column=0, sticky="w", padx=6, pady=4)
            self.amount_entry.grid(row=2, column=1, padx=6, pady=4)

        if self.type_var.get() == _SUPPLEMENT_TYPE_LABELS["dietas"]:
            self.dietas_note_label.grid(
                row=4, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 4)
            )
        else:
            self.dietas_note_label.grid_remove()

    def _handle_save(self) -> None:
        supplement_type = _SUPPLEMENT_TYPE_BY_LABEL[self.type_var.get()]
        description = self.description_var.get()

        try:
            if supplement_type == "horas_extra":
                try:
                    hours = float(self.hours_var.get().strip().replace(",", "."))
                    rate = float(self.rate_var.get().strip().replace(",", "."))
                except ValueError:
                    self.error_label.configure(text="Horas y precio/hora deben ser números.")
                    return
                self._repos.payroll_supplements.create(
                    self._employee_id,
                    self._year,
                    self._month,
                    supplement_type,
                    description,
                    hours=hours,
                    rate_per_hour=rate,
                )
            else:
                try:
                    amount = float(self.amount_var.get().strip().replace(",", "."))
                except ValueError:
                    self.error_label.configure(text="El importe debe ser un número.")
                    return
                self._repos.payroll_supplements.create(
                    self._employee_id,
                    self._year,
                    self._month,
                    supplement_type,
                    description,
                    amount=amount,
                )
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return

        self._on_change()
        self.destroy()


class GeneratePayrollDialog(tk.Toplevel):
    """Sustituye al simple askyesno que había antes: además de confirmar
    (si ya existe una nómina de este mes, se dice como texto en vez de un
    segundo diálogo aparte) deja fijar el % de IRPF de este trabajador en
    concreto -- una gestoría a menudo ya ha calculado el % real (con tramo
    autonómico, discapacidad, etc. que la estimación de esta app no cubre,
    ver app/payroll.py), y necesita poder introducirlo aquí en vez de
    fiarse solo del cálculo interno."""

    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        employee: Employee,
        year: int,
        month: int,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Generar nómina")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        self._repos = repos
        self._employee = employee
        self._year = year
        self._month = month
        self._on_change = on_change

        assert employee.id is not None
        existing = repos.payroll_records.get(employee.id, year, month)

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text=f"{employee.full_name} — {MONTH_NAMES[month - 1]} {year}",
            style="PageHeading.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        if existing is not None:
            ttk.Label(
                frame,
                text=(
                    "Ya existe una nómina generada el "
                    f"{existing.generated_at.strftime('%d/%m/%Y %H:%M')} para este mes. "
                    "Se sustituirá por el nuevo cálculo."
                ),
                style="Muted.TLabel",
                wraplength=340,
                justify="left",
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))
            default_irpf = existing.payroll.irpf_pct
        else:
            settings = repos.payroll_settings.get()
            default_irpf = estimate_irpf_withholding_rate(
                employee.salary, settings.ss_employee_pct, employee.dependent_children
            )

        ttk.Label(frame, text="% IRPF de este trabajador").grid(
            row=2, column=0, sticky="w", pady=3
        )
        self.irpf_var = tk.StringVar(value=f"{default_irpf:g}")
        ttk.Entry(frame, textvariable=self.irpf_var, width=12).grid(
            row=2, column=1, sticky="w", pady=3
        )
        ttk.Label(
            frame,
            text="Relleno con la estimación automática — corrígelo si tu gestoría ya te ha dado el % real.",
            style="Muted.TLabel",
            wraplength=340,
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=340)
        self.error_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 0))

        button_row = ttk.Frame(frame)
        button_row.grid(row=5, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(
            button_row,
            text="Regenerar" if existing is not None else "Generar",
            command=self._handle_submit,
            style="Accent.TButton",
        ).pack(side="left", padx=(0, 6))
        ttk.Button(button_row, text="Cancelar", command=self.destroy).pack(side="left")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self, parent)

    def _handle_submit(self) -> None:
        try:
            irpf_pct = float(self.irpf_var.get().strip().replace(",", "."))
        except ValueError:
            self.error_label.configure(text="El % de IRPF debe ser un número.")
            return
        assert self._employee.id is not None
        try:
            self._repos.payroll_records.generate(
                self._employee.id, self._year, self._month, irpf_pct_override=irpf_pct
            )
        except (validation.ValidationError, RepositoryError) as exc:
            self.error_label.configure(text=str(exc))
            return
        self._on_change()
        self.destroy()


class PayrollPage(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        repos: Repositories,
        locked_department_id: int | None = None,
        is_admin: bool = True,
    ) -> None:
        super().__init__(parent)
        self._repos = repos
        self._locked_department_id = locked_department_id
        self._is_admin = is_admin
        self._departments: list[Department] = []
        self._employees: list[Employee] = []
        self._selected_employee: Employee | None = None

        today = date.today()
        self._view_year = today.year
        self._view_month = today.month

        self._build_widgets()
        self.reload_departments()
        self._refresh_employee_list()

    def _build_widgets(self) -> None:
        palette = theme.current()
        self._banner = tk.Label(
            self,
            text=DISCLAIMER_TEXT,
            wraplength=760,
            justify="left",
            background=palette.disclaimer_bg,
            foreground=palette.disclaimer_fg,
            padx=10,
            pady=8,
            anchor="w",
        )
        self._banner.pack(side="top", fill="x")

        body = ttk.Frame(self)
        body.pack(side="top", fill="both", expand=True)

        list_frame = ttk.Frame(body, padding=(12, 12, 6, 12), width=300)
        list_frame.pack(side="left", fill="y")
        list_frame.pack_propagate(False)

        ttk.Label(list_frame, text="Departamento:").pack(side="top", anchor="w")
        self.department_filter_var = tk.StringVar(value="Todos")
        self.department_filter_combo = ttk.Combobox(
            list_frame,
            state="disabled" if self._locked_department_id is not None else "readonly",
            textvariable=self.department_filter_var,
            values=["Todos"],
        )
        self.department_filter_combo.pack(side="top", fill="x", pady=(2, 8))
        self.department_filter_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._refresh_employee_list()
        )

        tree_frame = ttk.Frame(list_frame)
        tree_frame.pack(side="top", fill="both", expand=True)
        self.tree = ttk.Treeview(
            tree_frame, columns=("nombre", "departamento"), show="headings", selectmode="browse"
        )
        self.tree.heading("nombre", text="Nombre")
        self.tree.heading("departamento", text="Departamento")
        self.tree.column("nombre", width=150, anchor="w")
        self.tree.column("departamento", width=110, anchor="w")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._handle_selection_changed())

        ttk.Separator(body, orient="vertical").pack(side="left", fill="y")

        # ScrollableFrame (mismo componente que ya usa la ficha de empleado):
        # sin esto, "Histórico generado" y su tabla quedaban completamente
        # inalcanzables en cuanto el contenido del panel (desglose + tabla de
        # complementos + tabla de histórico) superaba el alto de la ventana,
        # sin ninguna barra de scroll que lo remediara.
        detail_scroll = ScrollableFrame(body, bg=theme.current().bg)
        detail_scroll.pack(side="left", fill="both", expand=True)
        self._detail_scroll = detail_scroll
        detail_frame = ttk.Frame(detail_scroll.inner, padding=12)
        detail_frame.pack(side="top", fill="both", expand=True)

        month_row = ttk.Frame(detail_frame)
        month_row.pack(side="top", anchor="w")
        ttk.Button(month_row, text="<", width=3, command=self._go_previous_month).pack(
            side="left"
        )
        self.month_label = ttk.Label(month_row, width=18, anchor="center")
        self.month_label.pack(side="left", padx=4)
        ttk.Button(month_row, text=">", width=3, command=self._go_next_month).pack(side="left")

        # Acciones de todo el mes (no de un empleado suelto) -- en fila
        # horizontal justo bajo el selector de mes, siempre visibles sin
        # depender de haber seleccionado a nadie ni de cuánto ocupe el
        # desglose de abajo.
        actions_row = ttk.Frame(detail_frame)
        actions_row.pack(side="top", anchor="w", pady=(8, 0))
        self.settings_button = ttk.Button(
            actions_row,
            text="Configurar % Seguridad Social...",
            command=self._open_settings,
        )
        self.settings_button.pack(side="left")
        self.sepa_export_button = ttk.Button(
            actions_row,
            text="Exportar SEPA (pago de nóminas)...",
            command=self._open_sepa_export,
        )
        self.sepa_export_button.pack(side="left", padx=(6, 0))
        self.gestoria_export_button = ttk.Button(
            actions_row,
            text="Exportar para gestoría...",
            command=self._handle_gestoria_export,
        )
        self.gestoria_export_button.pack(side="left", padx=(6, 0))
        # Sin restringir a administradores, por el mismo motivo que
        # generate_button/download_pdf_button más abajo: como solo puede
        # CREAR nóminas que faltan (nunca sobrescribe una ya generada), el
        # resultado final es idéntico a que un encargado pulsase "Generar
        # nómina de este mes" una vez por cada empleado de su departamento
        # -- no es una acción financiera de toda la empresa como SEPA.
        self.generate_all_button = ttk.Button(
            actions_row,
            text="Generar nóminas de todos...",
            command=self._handle_generate_all,
        )
        self.generate_all_button.pack(side="left", padx=(6, 0))
        if not self._is_admin:
            self.settings_button.state(["disabled"])
            self.sepa_export_button.state(["disabled"])
            self.gestoria_export_button.state(["disabled"])

        self.employee_heading = ttk.Label(
            detail_frame, text="Selecciona un empleado", style="PageHeading.TLabel"
        )
        self.employee_heading.pack(side="top", anchor="w", pady=(10, 4))

        # Cada botón en su propia fila (mismo criterio ya usado en la ficha
        # de empleado, ver employee_page.py): la etiqueta de estado más los
        # tres botones juntos no cabían, y "Imprimir" -- el último
        # empaquetado -- se recortaba a "Im".
        self.record_status_label = ttk.Label(detail_frame, text="", style="Muted.TLabel")
        self.record_status_label.pack(side="top", anchor="w", pady=(0, 4))
        self.generate_button = ttk.Button(
            detail_frame, text="Generar nómina de este mes", command=self._handle_generate
        )
        self.generate_button.pack(side="top", anchor="w", pady=(0, 2))
        # Sin restringir a administradores (a diferencia de "Configurar %
        # Seguridad Social.../Exportar SEPA.../Exportar para gestoría..."):
        # sigue el mismo criterio que "Generar nómina de este mes", que
        # tampoco lo está -- descargar el PDF de una nómina de un empleado
        # es la acción natural que sigue a generarla, no una acción de toda
        # la empresa.
        self.download_pdf_button = ttk.Button(
            detail_frame, text="Descargar PDF...", command=self._handle_download_pdf
        )
        self.download_pdf_button.pack(side="top", anchor="w", pady=(0, 2))
        self.print_button = ttk.Button(
            detail_frame, text="Imprimir", command=self._handle_print_pdf
        )
        self.print_button.pack(side="top", anchor="w", pady=(0, 6))

        self.breakdown_frame = ttk.Frame(detail_frame)
        self.breakdown_frame.pack(side="top", anchor="w", fill="x")

        ttk.Label(
            detail_frame, text="Complementos de este mes", style="PageHeading.TLabel"
        ).pack(side="top", anchor="w", pady=(16, 4))
        supplements_frame = ttk.Frame(detail_frame)
        supplements_frame.pack(side="top", anchor="w", fill="x")
        self.supplements_tree = ttk.Treeview(
            supplements_frame,
            columns=("tipo", "descripcion", "horas", "importe"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for col, label, width in [
            ("tipo", "Tipo", 100),
            ("descripcion", "Descripción", 220),
            ("horas", "Horas x precio", 130),
            ("importe", "Importe", 100),
        ]:
            self.supplements_tree.heading(col, text=label)
            self.supplements_tree.column(col, width=width, anchor="w")
        self.supplements_tree.pack(side="top", fill="x")

        supplements_button_row = ttk.Frame(detail_frame)
        supplements_button_row.pack(side="top", anchor="w", pady=(6, 0))
        self.add_supplement_button = ttk.Button(
            supplements_button_row,
            text="Añadir complemento...",
            command=self._handle_add_supplement,
        )
        self.add_supplement_button.pack(side="left", padx=(0, 6))
        self.delete_supplement_button = ttk.Button(
            supplements_button_row, text="Eliminar", command=self._handle_delete_supplement
        )
        self.delete_supplement_button.pack(side="left")

        ttk.Label(
            detail_frame, text="Histórico generado", style="PageHeading.TLabel"
        ).pack(side="top", anchor="w", pady=(16, 4))
        history_frame = ttk.Frame(detail_frame)
        history_frame.pack(side="top", anchor="w", fill="x")
        self.history_tree = ttk.Treeview(
            history_frame,
            columns=("periodo", "neto", "generada"),
            show="headings",
            selectmode="browse",
            height=5,
        )
        for col, label, width in [
            ("periodo", "Periodo", 120),
            ("neto", "Neto", 100),
            ("generada", "Generada el", 160),
        ]:
            self.history_tree.heading(col, text=label)
            self.history_tree.column(col, width=width, anchor="w")
        self.history_tree.pack(side="top", fill="x")
        self.history_tree.bind("<<TreeviewSelect>>", lambda _e: self._handle_history_select())

    def apply_theme_change(self) -> None:
        """El aviso de Nóminas es un tk.Label con color fijado directamente
        (para poder elegir un amarillo de aviso que no es parte de la paleta
        ttk), así que no se actualiza solo con apply_theme() -- hay que
        reconfigurarlo a mano tras un cambio de tema en caliente. Lo mismo
        para el fondo del ScrollableFrame del panel de detalle (mismo motivo
        que EmployeeFichaPanel.apply_theme_change())."""
        palette = theme.current()
        self._banner.configure(background=palette.disclaimer_bg, foreground=palette.disclaimer_fg)
        self._detail_scroll.set_bg(palette.bg)

    def reload_departments(self) -> None:
        self._departments = self._repos.departments.list_all()
        if self._locked_department_id is not None:
            # next(..., None) en vez de sin valor por defecto: si el
            # departamento del encargado se borrase mientras su sesión
            # sigue abierta (solo posible con la misma base de datos
            # compartida por dos instancias a la vez), esto lanzaba
            # StopIteration sin capturar en vez de degradar con
            # normalidad -- mismo patrón ya usado en candidates_ui.py.
            locked = next(
                (d for d in self._departments if d.id == self._locked_department_id), None
            )
            names = [locked.name] if locked is not None else []
            self.department_filter_var.set(names[0] if names else "")
        else:
            names = ["Todos"] + [d.name for d in self._departments]
            if self.department_filter_var.get() not in names:
                self.department_filter_var.set("Todos")
        self.department_filter_combo.configure(values=names)
        self._refresh_employee_list()

    def _selected_department_filter_id(self) -> int | None:
        if self._locked_department_id is not None:
            return self._locked_department_id
        name = self.department_filter_var.get()
        for dept in self._departments:
            if dept.name == name:
                return dept.id
        return None

    def _refresh_employee_list(self) -> None:
        self._employees = self._repos.employees.search(
            department_id=self._selected_department_filter_id(), active_only=True
        )
        departments_by_id = {d.id: d for d in self._departments if d.id is not None}

        self.tree.delete(*self.tree.get_children())
        for emp in self._employees:
            department = departments_by_id.get(emp.department_id)
            self.tree.insert(
                "",
                tk.END,
                iid=str(emp.id),
                values=(emp.full_name, department.name if department else "?"),
            )
        self._render_breakdown()

    def _handle_selection_changed(self) -> None:
        selection = self.tree.selection()
        if not selection:
            self._selected_employee = None
        else:
            employee_id = int(selection[0])
            self._selected_employee = self._repos.employees.get(employee_id)
        self._render_breakdown()

    def _go_previous_month(self) -> None:
        self._view_year, self._view_month = shift_month(self._view_year, self._view_month, -1)
        self._render_breakdown()

    def _go_next_month(self) -> None:
        self._view_year, self._view_month = shift_month(self._view_year, self._view_month, 1)
        self._render_breakdown()

    def _open_settings(self) -> None:
        PayrollSettingsDialog(self, self._repos, on_change=self._render_breakdown)

    def _open_sepa_export(self) -> None:
        SepaExportDialog(self, self._repos, self._view_year, self._view_month)

    def _handle_gestoria_export(self) -> None:
        records = self._repos.payroll_records.list_for_month(self._view_year, self._view_month)
        if not records:
            messagebox.showinfo(
                "Exportar para gestoría",
                "No hay ninguna nómina generada para este mes.",
                parent=self,
            )
            return
        departments_by_id = {d.id: d.name for d in self._departments if d.id is not None}
        entries = []
        for record in records:
            employee = self._repos.employees.get(record.employee_id)
            department_name = departments_by_id.get(employee.department_id, "—")
            entries.append((employee, department_name, record))
        rows = build_gestoria_rows(entries)

        path_str = filedialog.asksaveasfilename(
            title="Exportar para gestoría",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"gestoria_nominas_{self._view_year}{self._view_month:02d}.csv",
            parent=self,
        )
        if not path_str:
            return
        try:
            write_gestoria_csv(rows, Path(path_str))
        except OSError as exc:
            messagebox.showerror("Exportar para gestoría", str(exc), parent=self)
            return
        messagebox.showinfo(
            "Exportar para gestoría", f"{len(rows)} nómina(s) exportada(s).", parent=self
        )

    def _handle_generate_all(self) -> None:
        if not self._employees:
            messagebox.showinfo(
                "Generar nóminas de todos",
                "No hay ningún empleado en la vista actual.",
                parent=self,
            )
            return
        scope = self.department_filter_var.get() or "Todos"
        if not messagebox.askyesno(
            "Generar nóminas de todos",
            f"Se va a generar la nómina de {MONTH_NAMES[self._view_month - 1]} "
            f"{self._view_year} para {len(self._employees)} empleado(s) de "
            f'"{scope}".\n\nSe usará la estimación automática de IRPF; las que '
            "ya existan para este mes no se tocan.",
            parent=self,
        ):
            return
        result = self._repos.payroll_records.generate_for_employees(
            [e.id for e in self._employees if e.id is not None],
            self._view_year,
            self._view_month,
        )
        summary = f"Se generaron {result.generated} nómina(s)."
        if result.skipped:
            summary += f"\nSe omitieron {result.skipped} porque ya existían."
        messagebox.showinfo("Generar nóminas de todos", summary, parent=self)
        self._render_breakdown()

    def _render_breakdown(self) -> None:
        self.month_label.configure(
            text=f"{MONTH_NAMES[self._view_month - 1]} {self._view_year}"
        )
        for widget in self.breakdown_frame.winfo_children():
            widget.destroy()

        employee = self._selected_employee
        if employee is None:
            self.employee_heading.configure(text="Selecciona un empleado")
            self.record_status_label.configure(text="")
            self.generate_button.state(["disabled"])
            self.download_pdf_button.state(["disabled"])
            self.print_button.state(["disabled"])
            ttk.Label(
                self.breakdown_frame,
                text="Elige un empleado de la lista para ver su nómina.",
                style="Muted.TLabel",
            ).grid(row=0, column=0, sticky="w")
            self._refresh_history()
            self._refresh_supplements()
            return

        self.employee_heading.configure(text=employee.full_name)
        self.generate_button.state(["!disabled"])
        assert employee.id is not None
        record = self._repos.payroll_records.get(employee.id, self._view_year, self._view_month)
        if record is not None:
            self.record_status_label.configure(
                text=(
                    "Nómina generada el "
                    f"{record.generated_at.strftime('%d/%m/%Y %H:%M')} (histórico, no se recalcula sola)"
                )
            )
            self.generate_button.configure(text="Regenerar nómina de este mes...")
            self.download_pdf_button.state(["!disabled"])
            self.print_button.state(["!disabled"])
            # El salario/hijos a cargo mostrados deben ser los CONGELADOS
            # en el snapshot, no los actuales del empleado -- si su sueldo
            # cambió después de generar esta nómina, mostrar el actual aquí
            # encima de un desglose (IRPF, neto...) que sigue basado en el
            # antiguo era una inconsistencia visible, aunque el dato
            # guardado en base de datos ya fuera correcto.
            self._populate_breakdown_rows(
                record.annual_gross_salary_snapshot,
                record.dependent_children_snapshot,
                record.payroll,
            )
        else:
            self.record_status_label.configure(text="Aún no se ha generado la nómina de este mes (estimación en vivo).")
            self.generate_button.configure(text="Generar nómina de este mes")
            # Nunca se descarga/imprime un PDF de una estimación en vivo --
            # mismo criterio que SepaExportDialog ya documenta para sí misma.
            self.download_pdf_button.state(["disabled"])
            self.print_button.state(["disabled"])
            settings = self._repos.payroll_settings.get()
            supplements_total, exempt_supplements_total, advances_total = (
                self._repos.payroll_supplements.totals_for_employee_month(
                    employee.id, self._view_year, self._view_month
                )
            )
            payroll = calculate_monthly_payroll(
                annual_gross_salary=employee.salary,
                dependent_children=employee.dependent_children,
                ss_employee_pct=settings.ss_employee_pct,
                ss_employer_pct=settings.ss_employer_pct,
                month=self._view_month,
                year=self._view_year,
                supplements_total=supplements_total,
                exempt_supplements_total=exempt_supplements_total,
                advances_total=advances_total,
            )
            self._populate_breakdown_rows(employee.salary, employee.dependent_children, payroll)
        self._refresh_history()
        self._refresh_supplements()

    def _handle_generate(self) -> None:
        employee = self._selected_employee
        if employee is None:
            return
        GeneratePayrollDialog(
            self,
            self._repos,
            employee,
            self._view_year,
            self._view_month,
            on_change=self._render_breakdown,
        )

    def _handle_download_pdf(self) -> None:
        employee = self._selected_employee
        if employee is None:
            return
        pdf_bytes = self._build_selected_pdf_bytes(employee, action_title="Descargar PDF")
        if pdf_bytes is None:
            return
        path_str = filedialog.asksaveasfilename(
            title="Guardar nómina en PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile=(
                f"nomina_{employee.full_name.replace(' ', '_')}_"
                f"{self._view_year}{self._view_month:02d}.pdf"
            ),
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
        employee = self._selected_employee
        if employee is None:
            return
        pdf_bytes = self._build_selected_pdf_bytes(employee, action_title="Imprimir")
        if pdf_bytes is None:
            return
        directory = Path(tempfile.gettempdir()) / "contaapp_rh_print"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            _cleanup_stale_print_files(directory)
            temp_path = directory / (
                f"nomina_{employee.full_name.replace(' ', '_')}_"
                f"{self._view_year}{self._view_month:02d}_{datetime.now():%H%M%S%f}.pdf"
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
        messagebox.showinfo("Imprimir", "La nómina se ha enviado a imprimir.", parent=self)

    def _build_selected_pdf_bytes(self, employee: Employee, *, action_title: str) -> bytes | None:
        assert employee.id is not None
        record = self._repos.payroll_records.get(employee.id, self._view_year, self._view_month)
        if record is None:
            messagebox.showinfo(
                action_title, "Genera primero la nómina de este mes.", parent=self
            )
            return None
        department = self._repos.departments.get(employee.department_id)
        professional_category = (
            self._repos.professional_categories.get(employee.professional_category_id)
            if employee.professional_category_id is not None
            else None
        )
        supplements = self._repos.payroll_supplements.list_for_employee_month(
            employee.id, self._view_year, self._view_month
        )
        company = CompanyInfo(
            name=self._repos.app_settings.get_company_name(),
            nif=self._repos.app_settings.get_company_nif(),
            ccc=self._repos.app_settings.get_company_ccc(),
            address=self._repos.app_settings.get_company_address(),
        )
        return build_payroll_pdf(
            employee=employee,
            department_name=department.name,
            professional_category_name=(
                professional_category.name if professional_category is not None else None
            ),
            company=company,
            record=record,
            supplements=supplements,
        )

    def _refresh_history(self) -> None:
        self.history_tree.delete(*self.history_tree.get_children())
        employee = self._selected_employee
        if employee is None:
            return
        assert employee.id is not None
        for record in self._repos.payroll_records.list_for_employee(employee.id):
            self.history_tree.insert(
                "",
                tk.END,
                iid=f"{record.payroll.year}-{record.payroll.month}",
                values=(
                    f"{MONTH_NAMES[record.payroll.month - 1]} {record.payroll.year}",
                    _format_currency(record.payroll.neto),
                    record.generated_at.strftime("%d/%m/%Y %H:%M"),
                ),
            )

    def _handle_history_select(self) -> None:
        selection = self.history_tree.selection()
        if not selection:
            return
        year_str, month_str = selection[0].split("-")
        self._view_year, self._view_month = int(year_str), int(month_str)
        self._render_breakdown()

    def _refresh_supplements(self) -> None:
        self.supplements_tree.delete(*self.supplements_tree.get_children())
        employee = self._selected_employee
        if employee is None:
            self.add_supplement_button.state(["disabled"])
            self.delete_supplement_button.state(["disabled"])
            return
        self.add_supplement_button.state(["!disabled"])
        assert employee.id is not None
        entries = self._repos.payroll_supplements.list_for_employee_month(
            employee.id, self._view_year, self._view_month
        )
        for entry in entries:
            assert entry.id is not None
            hours_display = (
                f"{entry.hours:.1f} h x {entry.rate_per_hour:.2f} €"
                if entry.hours is not None and entry.rate_per_hour is not None
                else ""
            )
            self.supplements_tree.insert(
                "",
                tk.END,
                iid=str(entry.id),
                values=(
                    _SUPPLEMENT_TYPE_LABELS[entry.supplement_type],
                    entry.description,
                    hours_display,
                    _format_currency(entry.amount),
                ),
            )

    def _selected_supplement_id(self) -> int | None:
        selection = self.supplements_tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def _handle_add_supplement(self) -> None:
        employee = self._selected_employee
        if employee is None:
            return
        assert employee.id is not None
        PayrollSupplementDialog(
            self,
            self._repos,
            employee_id=employee.id,
            year=self._view_year,
            month=self._view_month,
            on_change=self._render_breakdown,
        )

    def _handle_delete_supplement(self) -> None:
        supplement_id = self._selected_supplement_id()
        if supplement_id is None:
            messagebox.showinfo(
                "Complementos", "Seleccione un complemento de la lista.", parent=self
            )
            return
        if not messagebox.askyesno(
            "Confirmar eliminación", "¿Eliminar este complemento?", parent=self
        ):
            return
        self._repos.payroll_supplements.delete(supplement_id)
        self._render_breakdown()

    def _populate_breakdown_rows(
        self, annual_gross_salary: float, dependent_children: int, payroll: MonthlyPayroll
    ) -> None:
        def add_row(row: int, label: str, value: str, *, bold: bool = False, indent: bool = False) -> None:
            font = ("TkDefaultFont", 10, "bold") if bold else ("TkDefaultFont", 10)
            ttk.Label(
                self.breakdown_frame, text=label, font=font, padding=(16 if indent else 0, 2, 0, 2)
            ).grid(row=row, column=0, sticky="w")
            ttk.Label(self.breakdown_frame, text=value, font=font).grid(
                row=row, column=1, sticky="e", padx=(24, 0)
            )

        add_row(0, "Salario bruto anual", _format_currency(annual_gross_salary))
        add_row(1, "Hijos a cargo", str(dependent_children))
        add_row(2, "", "")

        add_row(3, "Paga ordinaria", _format_currency(payroll.paga_ordinaria), indent=True)
        add_row(4, "Paga extra (jul./dic.)", _format_currency(payroll.paga_extra), indent=True)
        add_row(
            5, "Complementos sujetos a IRPF/SS", _format_currency(payroll.supplements_total),
            indent=True,
        )
        add_row(
            6,
            "Dietas (no sujeto a IRPF/SS)",
            _format_currency(payroll.exempt_supplements_total),
            indent=True,
        )
        add_row(7, "Bruto del mes", _format_currency(payroll.bruto_mes), bold=True)
        add_row(8, "", "")

        add_row(
            9,
            f"Retención IRPF ({payroll.irpf_pct:.2f}%)",
            f"-{_format_currency(payroll.irpf_importe)}",
            indent=True,
        )
        add_row(
            10,
            f"Seguridad Social trabajador ({payroll.ss_employee_pct:.2f}%)",
            f"-{_format_currency(payroll.ss_employee_importe)}",
            indent=True,
        )
        add_row(11, "Anticipos ya pagados", f"-{_format_currency(payroll.advances_total)}", indent=True)
        add_row(12, "NETO A PERCIBIR", _format_currency(payroll.neto), bold=True)
        add_row(13, "", "")

        add_row(
            14,
            f"Seguridad Social empresa ({payroll.ss_employer_pct:.2f}%)",
            _format_currency(payroll.ss_employer_importe),
            indent=True,
        )
        add_row(15, "COSTE TOTAL EMPRESA", _format_currency(payroll.coste_total_empresa), bold=True)
