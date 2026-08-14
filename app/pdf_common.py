"""Piezas de PDF compartidas entre app/payroll_pdf.py y app/document_pdf.py:
paleta de color, estilos tipográficos, membrete con el nombre de la app y
tarjeta de datos con cabecera de color. Todo lo que sea específico de un tipo
de documento concreto (tablas de devengos/deducciones, franja de líquido a
percibir...) se queda en su propio módulo -- este archivo es solo el "motor
de carta con membrete" común a cualquier PDF que genere esta app.

Sin UI ni base de datos -- funciones puras (mismo criterio que payroll_pdf.py,
payroll.py, sepa_export.py, gestoria_export.py).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

# Colores duplicados de la paleta CLARA de app/theme.py, a propósito -- este
# módulo no puede importar theme.py sin arrastrar tkinter. Siempre la paleta
# clara -- un PDF se "imprime en papel blanco", no hay modo oscuro que
# aplicarle.
PRIMARY_DARK_HEX = "#1c3d5c"
PRIMARY_HEX = "#2f6690"
PRIMARY_LIGHT_HEX = "#5b9bd5"
PRIMARY_DARK = colors.HexColor(PRIMARY_DARK_HEX)
PRIMARY = colors.HexColor(PRIMARY_HEX)
PRIMARY_PALE = colors.HexColor("#e8f0f7")
BORDER = colors.HexColor("#d7dee6")
DISCLAIMER_BG = colors.HexColor("#fdf3cd")
DISCLAIMER_FG = colors.HexColor("#7a5b00")


@dataclass(frozen=True, slots=True)
class CompanyInfo:
    name: str
    nif: str
    ccc: str
    address: str


def build_styles() -> dict[str, ParagraphStyle]:
    # Escala tipográfica deliberada (nunca menos de 1.3x fontSize de leading,
    # nunca menos de 8pt para texto con información real, no decorativo) --
    # las fuentes estándar de PDF (Helvetica/Times) no van incrustadas en el
    # archivo, cada lector las sustituye por su propia versión con sus
    # propias métricas, así que un ajuste "al milímetro" en un lector puede
    # desbordarse en otro. Mejor dejar aire de sobra en todas partes y, si
    # hace falta, que el documento ocupe una segunda página -- nunca al revés.
    base = getSampleStyleSheet()
    return {
        "wordmark": ParagraphStyle(
            "wordmark",
            parent=base["Normal"],
            fontSize=17,
            leading=20,
            fontName="Helvetica",
            textColor=colors.white,
        ),
        "letterhead_right": ParagraphStyle(
            "letterhead_right",
            parent=base["Normal"],
            fontSize=12,
            leading=16,
            fontName="Helvetica-Bold",
            textColor=colors.white,
            alignment=2,
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer",
            parent=base["Normal"],
            fontSize=8.5,
            leading=12,
            textColor=DISCLAIMER_FG,
        ),
        "card_title": ParagraphStyle(
            "card_title",
            parent=base["Normal"],
            fontSize=10,
            leading=13,
            fontName="Helvetica-Bold",
            textColor=PRIMARY_DARK,
        ),
        "card_label": ParagraphStyle(
            "card_label", parent=base["Normal"], fontSize=8, leading=11, textColor=colors.grey
        ),
        "card_value": ParagraphStyle(
            "card_value",
            parent=base["Normal"],
            fontSize=9.5,
            leading=13,
            fontName="Helvetica-Bold",
        ),
        "period_line": ParagraphStyle(
            "period_line", parent=base["Normal"], fontSize=9, leading=12, textColor=colors.grey
        ),
        "section_heading": ParagraphStyle(
            "section_heading",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            textColor=colors.white,
            fontName="Helvetica-Bold",
        ),
        "subsection_label": ParagraphStyle(
            "subsection_label",
            parent=base["Normal"],
            fontSize=9.5,
            leading=13,
            fontName="Helvetica-Bold",
            textColor=PRIMARY_DARK,
        ),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=9.5, leading=13),
        "cell_right": ParagraphStyle(
            "cell_right", parent=base["Normal"], fontSize=9.5, leading=13, alignment=2
        ),
        "total_label": ParagraphStyle(
            "total_label",
            parent=base["Normal"],
            fontSize=10,
            leading=13,
            fontName="Helvetica-Bold",
        ),
        "total_amount": ParagraphStyle(
            "total_amount",
            parent=base["Normal"],
            fontSize=10,
            leading=13,
            fontName="Helvetica-Bold",
            alignment=2,
        ),
        "liquido_label": ParagraphStyle(
            "liquido_label",
            parent=base["Normal"],
            fontSize=12,
            leading=16,
            fontName="Times-Bold",
            textColor=colors.white,
        ),
        "liquido_amount": ParagraphStyle(
            "liquido_amount",
            parent=base["Normal"],
            fontSize=20,
            leading=24,
            fontName="Times-Bold",
            textColor=colors.white,
            alignment=2,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"], fontSize=7.5, leading=10, textColor=colors.grey
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontSize=10.5, leading=15, spaceAfter=8
        ),
    }


def letterhead(title: str, subtitle: str, styles: dict[str, ParagraphStyle]) -> Table:
    # Membrete con el nombre de la app -- primer elemento visible de
    # cualquier PDF que genere esta app, mismo azul pizarra oscuro que la
    # barra lateral. title/subtitle se escapan aquí dentro (no en quien
    # llama) porque para un documento de plantilla vienen de texto libre del
    # usuario (el nombre de la plantilla) y reportlab interpreta el
    # contenido de un Paragraph como marcado tipo XML -- un "&" o "<" sin
    # escapar rompería la generación.
    wordmark = Paragraph(
        f'Conta<b>App</b> <font color="{PRIMARY_LIGHT_HEX}"><b>RH</b></font>',
        styles["wordmark"],
    )
    subtitle_html = (
        f'<br/><font color="{PRIMARY_LIGHT_HEX}" size="10">{escape(subtitle)}</font>'
        if subtitle
        else ""
    )
    doc_title = Paragraph(f"{escape(title)}{subtitle_html}", styles["letterhead_right"])
    table = Table([[wordmark, doc_title]], colWidths=[90 * mm, 70 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PRIMARY_DARK),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 10),
                ("RIGHTPADDING", (1, 0), (1, 0), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


CardRow = tuple[str, str]


def info_card(title: str, rows: Sequence[CardRow], styles: dict[str, ParagraphStyle]) -> Table:
    # Tarjeta con cabecera de color propia (EMPRESA/TRABAJADOR en nóminas) --
    # construida como dos tablas anidadas (cabecera + filas) dentro de una
    # tercera que las envuelve con un único borde, porque una Table de
    # reportlab no deja aplicar un color de fondo distinto a "la primera
    # fila" cuando el resto de filas tiene un número de columnas distinto
    # (cabecera=1 col, filas=2). Una sola columna de valor a todo el ancho de
    # la tarjeta, que reportlab ajusta por sí solo: más filas seguras es
    # mejor que columnas de ancho fijo que a veces no caben (ver historial en
    # payroll_pdf.py, donde un nombre de departamento largo llegó a partirse
    # a mitad de palabra con dos columnas).
    header = Table([[Paragraph(escape(title), styles["card_title"])]], colWidths=[80 * mm])
    header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PRIMARY_PALE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    body_data = [
        [Paragraph(escape(label), styles["card_label"]), Paragraph(escape(value) or "—", styles["card_value"])]
        for label, value in rows
    ]
    body = Table(body_data, colWidths=[24 * mm, 56 * mm])
    body.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    wrapper = Table([[header], [body]], colWidths=[80 * mm])
    wrapper.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return wrapper


def section_heading(text: str, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table([[Paragraph(escape(text), styles["section_heading"])]], colWidths=[160 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PRIMARY),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def subsection_label(text: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    # Subtítulo ligero -- a diferencia de section_heading, sin banda de color
    # propia: es una subdivisión de la sección, no una sección nueva, y una
    # segunda banda del mismo peso visual la haría parecer independiente.
    return Paragraph(escape(text), styles["subsection_label"])
