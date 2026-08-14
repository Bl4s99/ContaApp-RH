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

El aspecto visual reutiliza la identidad de marca de la app (azul pizarra,
ver app/theme.py) en vez del gris/Helvetica genérico de un PDF por defecto --
membrete con el nombre de la app, tarjetas EMPRESA/TRABAJADOR con cabecera de
color, filas alternas en las tablas de importes y una franja de líquido a
percibir a modo de cierre visual del documento.

Sin UI ni base de datos -- función pura sobre datos ya obtenidos por quien
llama (mismo criterio que app/payroll.py, app/sepa_export.py,
app/gestoria_export.py)."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models import Employee, PayrollRecord, PayrollSupplement
from app.pdf_common import BORDER, PRIMARY, PRIMARY_PALE, DISCLAIMER_BG, DISCLAIMER_FG, PRIMARY_DARK
from app.pdf_common import CompanyInfo as CompanyInfo
from app.pdf_common import build_styles, info_card, letterhead, section_heading, subsection_label

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


def _devengos_salariales_rows(
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
        if supplement.supplement_type in ("anticipo", "dietas"):
            # anticipo es una deducción (ver _deducciones_rows); dietas es
            # una percepción NO salarial (ver _devengos_no_salariales_rows) --
            # ninguna de las dos pertenece a este desglose.
            continue
        label = _SUPPLEMENT_TYPE_LABELS.get(supplement.supplement_type, supplement.supplement_type)
        text = f"{label} — {supplement.description}" if supplement.description else label
        rows.append((text, _format_currency(supplement.amount)))
    return rows


def _devengos_no_salariales_rows(
    supplements: Sequence[PayrollSupplement],
) -> list[tuple[str, str]]:
    # Dietas -- percepción no salarial, exenta de IRPF/SS mientras se
    # mantenga dentro de los límites legales diarios (ver el docstring de
    # calculate_monthly_payroll() en app/payroll.py). Es la única partida
    # de este desglose; si en el futuro se añade otro tipo no salarial,
    # se sumaría aquí junto a ella.
    rows = []
    for supplement in supplements:
        if supplement.supplement_type != "dietas":
            continue
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
    "bonos": "Bonos",
    "dietas": "Dietas",
}


def _rows_table(rows: Sequence[tuple[str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    data = [[Paragraph(label, styles["cell"]), Paragraph(amount, styles["cell_right"])] for label, amount in rows]
    table = Table(data, colWidths=[120 * mm, 40 * mm])
    table.setStyle(
        TableStyle(
            [
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, PRIMARY_PALE]),
                ("LINEBELOW", (0, -1), (-1, -1), 0.75, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
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
                ("BACKGROUND", (0, 0), (-1, -1), PRIMARY_PALE),
                ("LINEABOVE", (0, 0), (-1, 0), 1, PRIMARY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


_CardRow = tuple[str, str]


def _liquido_band(amount_text: str, styles: dict[str, ParagraphStyle]) -> Table:
    # Franja de cierre del bloque de importes -- deliberadamente el elemento
    # con más peso visual de la página (mismo azul oscuro del membrete, cifra
    # más grande que cualquier otro número del documento) para que el
    # líquido a percibir sea lo primero que salte a la vista, no solo un
    # renglón más entre los demás totales.
    table = Table(
        [
            [
                Paragraph("LÍQUIDO TOTAL A PERCIBIR", styles["liquido_label"]),
                Paragraph(amount_text, styles["liquido_amount"]),
            ]
        ],
        colWidths=[100 * mm, 60 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PRIMARY_DARK),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def build_payroll_pdf(
    employee: Employee,
    department_name: str,
    professional_category_name: str | None,
    company: CompanyInfo,
    record: PayrollRecord,
    supplements: Sequence[PayrollSupplement] = (),
) -> bytes:
    payroll = record.payroll
    styles = build_styles()
    period_label = _period_label(payroll.year, payroll.month)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title=f"Nómina — {employee.full_name} — {period_label}",
    )

    story: list[Flowable] = []

    story.append(letterhead("RECIBO DE SALARIOS", period_label, styles))
    story.append(Spacer(1, 4 * mm))

    disclaimer_table = Table(
        [[Paragraph(DISCLAIMER_TEXT, styles["disclaimer"])]], colWidths=[160 * mm]
    )
    disclaimer_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), DISCLAIMER_BG),
                ("LINEBEFORE", (0, 0), (0, 0), 3, DISCLAIMER_FG),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(disclaimer_table)
    story.append(Spacer(1, 4 * mm))

    category_label, category_value = _category_line(employee.position, professional_category_name)
    period_last_day = date(payroll.year, payroll.month, _period_days(payroll.year, payroll.month))
    empresa_rows: list[_CardRow] = [
        ("Empresa", company.name),
        ("NIF/CIF", company.nif),
        ("C.C.C.", company.ccc),
        ("Domicilio", company.address),
    ]
    trabajador_rows: list[_CardRow] = [
        ("Trabajador/a", employee.full_name),
        ("NIF/NIE", employee.dni_nie or ""),
        ("Nº afiliación S.S.", employee.ss_number or ""),
        (category_label, category_value),
        ("Departamento", department_name),
        ("Antigüedad", _seniority_text(employee.hire_date, period_last_day)),
    ]
    cards_table = Table(
        [[info_card("EMPRESA", empresa_rows, styles), info_card("TRABAJADOR/A", trabajador_rows, styles)]],
        colWidths=[80 * mm, 80 * mm],
    )
    cards_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("LEFTPADDING", (1, 0), (1, 0), 6 * mm),
            ]
        )
    )
    story.append(cards_table)
    story.append(Spacer(1, 3 * mm))
    story.append(
        Paragraph(
            f"Período de liquidación: <b>{period_label}</b> "
            f"({_period_days(payroll.year, payroll.month)} días)",
            styles["period_line"],
        )
    )
    story.append(Spacer(1, 4 * mm))

    devengos_no_salariales = _devengos_no_salariales_rows(supplements)
    devengos_flowables: list[Flowable] = [
        section_heading("I. DEVENGOS", styles),
        subsection_label("Percepciones salariales", styles),
        Spacer(1, 1 * mm),
        _rows_table(_devengos_salariales_rows(record, supplements), styles),
    ]
    # El subapartado de no salariales solo se añade si hay dietas este mes --
    # nunca un título "Percepciones no salariales" seguido de una tabla vacía.
    if devengos_no_salariales:
        devengos_flowables.extend(
            [
                Spacer(1, 2 * mm),
                subsection_label("Percepciones no salariales", styles),
                Spacer(1, 1 * mm),
                _rows_table(devengos_no_salariales, styles),
            ]
        )
    devengos_flowables.append(
        _total_row_table("TOTAL DEVENGADO (bruto del mes)", _format_currency(payroll.bruto_mes), styles)
    )
    story.append(KeepTogether(devengos_flowables))
    story.append(Spacer(1, 3 * mm))

    total_deducir = payroll.ss_employee_importe + payroll.irpf_importe + payroll.advances_total
    story.append(
        KeepTogether(
            [
                section_heading("II. DEDUCCIONES", styles),
                _rows_table(_deducciones_rows(record, supplements), styles),
                _total_row_table("TOTAL A DEDUCIR", _format_currency(total_deducir), styles),
            ]
        )
    )
    story.append(Spacer(1, 3 * mm))

    story.append(_liquido_band(_format_currency(payroll.neto), styles))
    story.append(Spacer(1, 5 * mm))

    story.append(
        KeepTogether(
            [
                section_heading("Bases de cotización y aportación empresarial (simplificado)", styles),
                Spacer(1, 1 * mm),
                Paragraph(
                    "Esta aplicación no desglosa por separado las bases de cotización ni la "
                    "aportación empresarial por contingencias comunes/profesionales, desempleo, "
                    "formación profesional o FOGASA — se muestran como cifras combinadas.",
                    styles["footer"],
                ),
                Spacer(1, 2 * mm),
                _rows_table(
                    [
                        (
                            "Base sujeta a retención IRPF (aprox.)",
                            # bruto_mes incluye las dietas (exentas); la base real de
                            # IRPF/SS las excluye -- ver exempt_supplements_total en
                            # app/payroll.py. Cuando no hay dietas este mes, ambas
                            # cifras coinciden exactamente.
                            _format_currency(payroll.bruto_mes - payroll.exempt_supplements_total),
                        ),
                        (
                            "Aportación empresarial a la Seguridad Social "
                            f"({_format_percentage(payroll.ss_employer_pct)}, cifra combinada)",
                            _format_currency(payroll.ss_employer_importe),
                        ),
                        ("Coste total para la empresa", _format_currency(payroll.coste_total_empresa)),
                    ],
                    styles,
                ),
            ]
        )
    )
    story.append(Spacer(1, 4 * mm))

    # Solo la fecha de generación, sin repetir DISCLAIMER_TEXT (ya se ha
    # mostrado una vez, de forma destacada, justo debajo del membrete --
    # repetir el mismo aviso largo aquí abajo no añadía nada, solo alargaba
    # el documento).
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=3))
    story.append(
        Paragraph(
            f"Nómina generada el {record.generated_at.strftime('%d/%m/%Y a las %H:%M')} "
            "por ContaApp RH.",
            styles["footer"],
        )
    )

    doc.build(story)
    return buffer.getvalue()
