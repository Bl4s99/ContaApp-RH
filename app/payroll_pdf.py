"""Genera el PDF de una nómina YA GENERADA (un PayrollRecord congelado, nunca
una estimación en vivo -- ver payroll_ui.py, que solo habilita el botón de
descarga cuando existe un registro). Sigue el formato del modelo oficial de
recibo de salarios (Orden ESS/2098/2014: cabecera empresa/trabajador,
I. DEVENGOS, II. DEDUCCIONES, líquido a percibir, bases de cotización) pero
solo con lo que esta app realmente calcula -- donde el cálculo de la app es
más simple que el oficial completo (SS del trabajador sin desglosar por
contingencia, sin tramo autonómico de IRPF, sin bases de cotización
separadas), el PDF lo dice explícitamente en vez de fingir una precisión que
no tiene. Mismo espíritu que el aviso ya usado en toda la app de Nóminas
(DISCLAIMER_TEXT, app/payroll_ui.py).

Sin UI ni base de datos -- función pura sobre datos ya obtenidos por quien
llama (mismo criterio que app/payroll.py, app/sepa_export.py,
app/gestoria_export.py)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models import Employee, PayrollRecord, PayrollSupplement

# Nombres de mes en español, duplicados a propósito en vez de importados de
# app/calendar_widget.py (que arrastraría tkinter a un módulo que no debe
# depender de UI) o de calendar.month_name (que depende del locale del
# proceso, algo que este proyecto evita deliberadamente en todo formateo de
# fechas/importes -- ver el comentario de _format_currency en payroll_ui.py).
_MONTH_NAMES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

DISCLAIMER_TEXT = (
    "Estimación orientativa, no es una nómina oficial ni válida para presentar "
    "impuestos. Usa solo la escala estatal de retención de IRPF (sin tramo "
    "autonómico) y un mínimo personal y familiar simplificado. La aportación del "
    "trabajador a la Seguridad Social se muestra como una única cifra combinada, "
    "sin desglosar por contingencias comunes/desempleo/formación profesional. "
    "Verifica siempre con tu gestoría antes de considerar esta nómina definitiva."
)

_DISCLAIMER_BG = colors.HexColor("#fdf3cd")  # theme.py, disclaimer_bg (modo claro)
_DISCLAIMER_FG = colors.HexColor("#7a5b00")  # theme.py, disclaimer_fg (modo claro)
_HEADING_BG = colors.HexColor("#2f6690")
_TOTAL_BG = colors.HexColor("#eef3f7")
_GRID_COLOR = colors.HexColor("#b5b5b5")


@dataclass(frozen=True, slots=True)
class CompanyInfo:
    name: str
    nif: str
    ccc: str
    address: str


def _format_currency(value: float) -> str:
    # Duplicado del helper de payroll_ui.py a propósito, no importado -- este
    # módulo no depende de la capa de UI. Mismo formato español (punto de
    # millar, coma decimal) sin depender del locale del proceso.
    us_formatted = f"{value:,.2f}"
    integer_part, decimal_part = us_formatted.split(".")
    integer_part = integer_part.replace(",", ".")
    return f"{integer_part},{decimal_part} €"


def _format_percentage(value: float) -> str:
    # Igual que _format_currency: coma decimal española, no el punto que
    # f"{value:g}" produciría por defecto -- si no, los importes de esta
    # misma tabla usan coma y los porcentajes usarían punto, inconsistencia
    # visible en el documento.
    return f"{value:g}".replace(".", ",") + "%"


def _period_label(year: int, month: int) -> str:
    return f"{_MONTH_NAMES[month - 1].capitalize()} de {year}"


def _period_days(year: int, month: int) -> int:
    import calendar

    return calendar.monthrange(year, month)[1]


def _seniority_text(hire_date: date, as_of: date) -> str:
    years = as_of.year - hire_date.year
    months = as_of.month - hire_date.month
    if as_of.day < hire_date.day:
        months -= 1
    if months < 0:
        years -= 1
        months += 12
    years = max(years, 0)
    months = max(months, 0)
    if years == 0 and months == 0:
        return "menos de 1 mes"
    parts = []
    if years > 0:
        parts.append(f"{years} año{'s' if years != 1 else ''}")
    if months > 0:
        parts.append(f"{months} mes{'es' if months != 1 else ''}")
    return " y ".join(parts)


def _category_line(position: str, professional_category_name: str | None) -> tuple[str, str]:
    # No se sustituye libremente uno por otro: "puesto" (texto libre) y
    # "categoría profesional" (ligada a un convenio) son conceptos distintos
    # -- mostrar el puesto bajo la etiqueta de categoría formal cuando no hay
    # ninguna asignada sería inventar una precisión que no existe.
    if professional_category_name is not None:
        return ("Categoría profesional", professional_category_name)
    return ("Puesto", position)


def _devengos_rows(
    payroll_record: PayrollRecord, supplements: Sequence[PayrollSupplement]
) -> list[tuple[str, str]]:
    payroll = payroll_record.payroll
    rows = [("Salario base (paga ordinaria)", _format_currency(payroll.paga_ordinaria))]
    if payroll.paga_extra:
        rows.append(("Gratificación extraordinaria (prorrata)", _format_currency(payroll.paga_extra)))
    # Los complementos se listan uno a uno con los ya registrados para este
    # empleado/mes (app/payroll_supplements, tabla en vivo, no un snapshot
    # ligado a este PayrollRecord concreto -- no existe tal snapshot). Si se
    # editan complementos DESPUÉS de generar la nómina sin regenerarla, este
    # desglose puede dejar de sumar exactamente el "Complementos" congelado
    # en payroll.supplements_total -- mismo límite que ya acepta hoy la
    # propia página de Nóminas, cuyo árbol de complementos también es
    # siempre en vivo, se esté mirando un registro congelado o no.
    for supplement in supplements:
        if supplement.supplement_type == "anticipo":
            continue  # es una deducción (anticipo ya pagado), no un devengo
        label = _SUPPLEMENT_TYPE_LABELS.get(supplement.supplement_type, supplement.supplement_type)
        text = f"{label} — {supplement.description}" if supplement.description else label
        rows.append((text, _format_currency(supplement.amount)))
    return rows


def _deducciones_rows(
    payroll_record: PayrollRecord, supplements: Sequence[PayrollSupplement]
) -> list[tuple[str, str]]:
    payroll = payroll_record.payroll
    rows = [
        (
            "Aportación del trabajador a la Seguridad Social "
            f"({_format_percentage(payroll.ss_employee_pct)}, cifra combinada)",
            _format_currency(payroll.ss_employee_importe),
        ),
        (
            f"Retención IRPF ({_format_percentage(payroll.irpf_pct)})",
            _format_currency(payroll.irpf_importe),
        ),
    ]
    for supplement in supplements:
        if supplement.supplement_type != "anticipo":
            continue
        text = f"Anticipo — {supplement.description}" if supplement.description else "Anticipo"
        rows.append((text, _format_currency(supplement.amount)))
    return rows


_SUPPLEMENT_TYPE_LABELS = {
    "plus": "Plus",
    "horas_extra": "Horas extra",
}


def _rows_table(rows: Sequence[tuple[str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    data = [[Paragraph(label, styles["cell"]), Paragraph(amount, styles["cell_right"])] for label, amount in rows]
    table = Table(data, colWidths=[120 * mm, 40 * mm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, _GRID_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _total_row_table(label: str, amount: str, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table(
        [[Paragraph(label, styles["total_label"]), Paragraph(amount, styles["total_amount"])]],
        colWidths=[120 * mm, 40 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, _GRID_COLOR),
                ("BACKGROUND", (0, 0), (-1, -1), _TOTAL_BG),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _section_heading(text: str, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table([[Paragraph(text, styles["section_heading"])]], colWidths=[160 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _HEADING_BG),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=14, alignment=TA_CENTER),
        "disclaimer": ParagraphStyle(
            "disclaimer",
            parent=base["Normal"],
            fontSize=8,
            textColor=_DISCLAIMER_FG,
            leading=11,
        ),
        "header_label": ParagraphStyle(
            "header_label", parent=base["Normal"], fontSize=9, textColor=colors.grey
        ),
        "header_value": ParagraphStyle("header_value", parent=base["Normal"], fontSize=10),
        "section_heading": ParagraphStyle(
            "section_heading",
            parent=base["Normal"],
            fontSize=10,
            textColor=colors.white,
            fontName="Helvetica-Bold",
        ),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=9),
        "cell_right": ParagraphStyle(
            "cell_right", parent=base["Normal"], fontSize=9, alignment=2
        ),
        "total_label": ParagraphStyle(
            "total_label", parent=base["Normal"], fontSize=10, fontName="Helvetica-Bold"
        ),
        "total_amount": ParagraphStyle(
            "total_amount",
            parent=base["Normal"],
            fontSize=10,
            fontName="Helvetica-Bold",
            alignment=2,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"], fontSize=7, textColor=colors.grey
        ),
    }


def _header_field(label: str, value: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    text = f"<b>{label}:</b> {value}" if value else f"<b>{label}:</b> —"
    return Paragraph(text, styles["header_value"])


def build_payroll_pdf(
    employee: Employee,
    department_name: str,
    professional_category_name: str | None,
    company: CompanyInfo,
    record: PayrollRecord,
    supplements: Sequence[PayrollSupplement] = (),
) -> bytes:
    payroll = record.payroll
    styles = _build_styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title=f"Nómina — {employee.full_name} — {_period_label(payroll.year, payroll.month)}",
    )

    story: list[Flowable] = []

    story.append(Paragraph("Recibo individual de salarios", styles["title"]))
    story.append(Spacer(1, 4 * mm))
    disclaimer_table = Table(
        [[Paragraph(DISCLAIMER_TEXT, styles["disclaimer"])]], colWidths=[160 * mm]
    )
    disclaimer_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _DISCLAIMER_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, _DISCLAIMER_FG),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(disclaimer_table)
    story.append(Spacer(1, 5 * mm))

    category_label, category_value = _category_line(employee.position, professional_category_name)
    period_last_day = date(payroll.year, payroll.month, _period_days(payroll.year, payroll.month))
    header_data = [
        [
            _header_field("Empresa", company.name, styles),
            _header_field("Trabajador", employee.full_name, styles),
        ],
        [
            _header_field("NIF / CIF", company.nif, styles),
            _header_field("NIF / NIE", employee.dni_nie or "", styles),
        ],
        [
            _header_field("C.C.C.", company.ccc, styles),
            _header_field("Nº afiliación S.S.", employee.ss_number or "", styles),
        ],
        [
            _header_field("Domicilio", company.address, styles),
            _header_field(category_label, category_value, styles),
        ],
        [
            Paragraph("", styles["header_value"]),
            _header_field("Departamento", department_name, styles),
        ],
        [
            Paragraph("", styles["header_value"]),
            _header_field(
                "Antigüedad", _seniority_text(employee.hire_date, period_last_day), styles
            ),
        ],
    ]
    header_table = Table(header_data, colWidths=[80 * mm, 80 * mm])
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 3 * mm))
    story.append(
        Paragraph(
            f"<b>Período de liquidación:</b> {_period_label(payroll.year, payroll.month)} "
            f"({_period_days(payroll.year, payroll.month)} días)",
            styles["header_value"],
        )
    )
    story.append(Spacer(1, 5 * mm))

    story.append(_section_heading("I. DEVENGOS", styles))
    story.append(_rows_table(_devengos_rows(record, supplements), styles))
    story.append(_total_row_table("TOTAL DEVENGADO (bruto del mes)", _format_currency(payroll.bruto_mes), styles))
    story.append(Spacer(1, 4 * mm))

    total_deducir = payroll.ss_employee_importe + payroll.irpf_importe + payroll.advances_total
    story.append(_section_heading("II. DEDUCCIONES", styles))
    story.append(_rows_table(_deducciones_rows(record, supplements), styles))
    story.append(_total_row_table("TOTAL A DEDUCIR", _format_currency(total_deducir), styles))
    story.append(Spacer(1, 5 * mm))

    liquido_table = Table(
        [[Paragraph("LÍQUIDO TOTAL A PERCIBIR", styles["total_label"]),
          Paragraph(_format_currency(payroll.neto), styles["total_amount"])]],
        colWidths=[120 * mm, 40 * mm],
    )
    liquido_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1.0, colors.black),
                ("BACKGROUND", (0, 0), (-1, -1), _TOTAL_BG),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(liquido_table)
    story.append(Spacer(1, 6 * mm))

    story.append(_section_heading("Bases de cotización y aportación empresarial (simplificado)", styles))
    story.append(Spacer(1, 1 * mm))
    story.append(
        Paragraph(
            "Esta aplicación no desglosa por separado las bases de cotización ni la "
            "aportación empresarial por contingencias comunes/profesionales, desempleo, "
            "formación profesional o FOGASA — se muestran como cifras combinadas.",
            styles["footer"],
        )
    )
    story.append(Spacer(1, 2 * mm))
    bases_rows = [
        ("Base sujeta a retención IRPF (aprox.)", _format_currency(payroll.bruto_mes)),
        (
            "Aportación empresarial a la Seguridad Social "
            f"({_format_percentage(payroll.ss_employer_pct)}, cifra combinada)",
            _format_currency(payroll.ss_employer_importe),
        ),
        ("Coste total para la empresa", _format_currency(payroll.coste_total_empresa)),
    ]
    story.append(_rows_table(bases_rows, styles))
    story.append(Spacer(1, 8 * mm))

    story.append(
        Paragraph(
            f"Nómina generada el {record.generated_at.strftime('%d/%m/%Y a las %H:%M')} "
            "por ContaApp RH. " + DISCLAIMER_TEXT,
            styles["footer"],
        )
    )

    doc.build(story)
    return buffer.getvalue()
