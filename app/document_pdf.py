"""Genera el PDF de un documento YA RENDERIZADO a partir de una plantilla
(oferta, carta de baja, contrato...) -- ver
DocumentTemplateRepository.render_for_employee() en app/repository.py, que
hace toda la sustitución de {marcadores}. Este módulo solo maqueta ese texto
ya final, nunca vuelve a tocar plantillas ni placeholders.

Deliberadamente sin tarjetas EMPRESA/TRABAJADOR estilo nómina: una plantilla
ya es prosa autocontenida (saludo, destinatario, cuerpo -- p.ej. "Estimado/a
{nombre}, nos complace ofrecerle..."), así que una cabecera formal de
contrato encima sería redundante. Sí se añade una línea compacta con el
nombre/NIF de la empresa bajo el membrete, para que quede claro de parte de
quién es el documento (el membrete en sí lleva la marca de ContaApp RH, no
la de la empresa que lo genera).

Sin UI ni base de datos -- función pura sobre datos ya obtenidos por quien
llama (mismo criterio que app/payroll_pdf.py)."""
from __future__ import annotations

import re
from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, HRFlowable, Paragraph, SimpleDocTemplate, Spacer

from app.pdf_common import BORDER, CompanyInfo, build_styles, letterhead

_BLANK_LINE_RE = re.compile(r"\n\s*\n")


def _split_paragraphs(body_text: str) -> list[str]:
    # Un párrafo de reportlab por cada bloque separado por una o más líneas
    # en blanco; los saltos de línea sueltos DENTRO de un párrafo se
    # conservan como <br/> en _paragraph_html, no como un párrafo nuevo. Un
    # cuerpo sin ninguna línea en blanco es un único párrafo.
    normalized = body_text.replace("\r\n", "\n").strip("\n")
    if not normalized.strip():
        return []
    return [block.strip("\n") for block in _BLANK_LINE_RE.split(normalized) if block.strip()]


def _sender_line(company: CompanyInfo) -> str:
    # NIF solo si esta relleno -- una empresa que aun no lo ha configurado no
    # debe salir con un "-- NIF" colgando sin nada detras (visto en la
    # verificacion manual).
    line = escape(company.name)
    if company.nif:
        line += f" — NIF {escape(company.nif)}"
    return line


def _paragraph_html(paragraph_text: str) -> str:
    # El cuerpo viene de texto libre de plantilla + datos reales de empleado
    # (nombre, puesto...) y reportlab interpreta el contenido de un
    # Paragraph como marcado tipo XML -- un "&" o "<" sin escapar (p.ej. un
    # empleado llamado "María & José") rompería la generación. Se escapa
    # ANTES de insertar <br/>, para que ese propio marcado no se escape a su
    # vez.
    return escape(paragraph_text).replace("\n", "<br/>")


def build_document_pdf(
    document_title: str,
    employee_name: str,
    body_text: str,
    company: CompanyInfo,
    generated_at: date,
) -> bytes:
    styles = build_styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title=f"{document_title} — {employee_name}",
    )

    story: list[Flowable] = [letterhead(document_title, "", styles)]
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(_sender_line(company), styles["period_line"]))
    story.append(Spacer(1, 7 * mm))

    paragraphs = _split_paragraphs(body_text)
    if not paragraphs:
        story.append(Paragraph("(Documento sin contenido.)", styles["body"]))
    else:
        for paragraph_text in paragraphs:
            story.append(Paragraph(_paragraph_html(paragraph_text), styles["body"]))

    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=3))
    story.append(
        Paragraph(
            f"Documento generado el {generated_at.strftime('%d/%m/%Y')} por ContaApp RH.",
            styles["footer"],
        )
    )

    doc.build(story)
    return buffer.getvalue()
