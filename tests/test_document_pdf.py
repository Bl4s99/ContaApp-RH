from __future__ import annotations

from datetime import date

from app.document_pdf import _paragraph_html, _sender_line, _split_paragraphs, build_document_pdf
from app.pdf_common import CompanyInfo


def _company(**overrides: object) -> CompanyInfo:
    defaults: dict[str, object] = dict(
        name="Empresa de Prueba S.L.",
        nif="B23456718",
        ccc="28/1234567/89",
        address="Calle Mayor 1, 28001 Madrid",
    )
    defaults.update(overrides)
    return CompanyInfo(**defaults)  # type: ignore[arg-type]


class TestSenderLine:
    def test_includes_nif_when_present(self) -> None:
        assert _sender_line(_company(name="Empresa S.L.", nif="B23456718")) == (
            "Empresa S.L. — NIF B23456718"
        )

    def test_omits_trailing_nif_label_when_nif_is_empty(self) -> None:
        # Bug real visto en la verificacion manual: sin este caso especial,
        # una empresa sin NIF configurado salia como "Empresa S.L. -- NIF"
        # con la etiqueta colgando sin ningun valor detras.
        assert _sender_line(_company(name="Empresa S.L.", nif="")) == "Empresa S.L."

    def test_escapes_ampersand_in_company_name(self) -> None:
        assert _sender_line(_company(name="García & Hnos", nif="")) == "García &amp; Hnos"


class TestSplitParagraphs:
    def test_single_paragraph_no_blank_lines(self) -> None:
        assert _split_paragraphs("Hola, esto es un párrafo.") == ["Hola, esto es un párrafo."]

    def test_two_paragraphs_separated_by_blank_line(self) -> None:
        assert _split_paragraphs("Primero.\n\nSegundo.") == ["Primero.", "Segundo."]

    def test_multiple_blank_lines_still_one_split(self) -> None:
        assert _split_paragraphs("Primero.\n\n\n\nSegundo.") == ["Primero.", "Segundo."]

    def test_single_newlines_stay_within_one_paragraph(self) -> None:
        assert _split_paragraphs("Línea 1.\nLínea 2.") == ["Línea 1.\nLínea 2."]

    def test_empty_body_returns_empty_list(self) -> None:
        assert _split_paragraphs("") == []

    def test_whitespace_only_body_returns_empty_list(self) -> None:
        assert _split_paragraphs("   \n\n   ") == []

    def test_leading_and_trailing_blank_lines_are_stripped(self) -> None:
        assert _split_paragraphs("\n\nHola.\n\n") == ["Hola."]


class TestParagraphHtml:
    def test_escapes_ampersand(self) -> None:
        assert _paragraph_html("María & José") == "María &amp; José"

    def test_escapes_angle_brackets(self) -> None:
        assert _paragraph_html("<Ingeniera>") == "&lt;Ingeniera&gt;"

    def test_converts_newline_to_br(self) -> None:
        assert _paragraph_html("Línea 1.\nLínea 2.") == "Línea 1.<br/>Línea 2."

    def test_br_tag_survives_escaping_order(self) -> None:
        # El <br/> se inserta DESPUÉS de escapar -- si el orden fuera al
        # revés, el propio <br/> saldría escapado y visible como texto.
        result = _paragraph_html("a\nb")
        assert "<br/>" in result
        assert "&lt;br" not in result


class TestBuildDocumentPdfWellFormedness:
    def test_produces_a_valid_pdf(self) -> None:
        pdf_bytes = build_document_pdf(
            document_title="Oferta de trabajo",
            employee_name="Ana López",
            body_text="Estimada Ana,\n\nNos complace ofrecerle el puesto de Ingeniera.\n\nUn saludo.",
            company=_company(),
            generated_at=date(2026, 8, 14),
        )
        assert pdf_bytes.startswith(b"%PDF-")
        assert b"%%EOF" in pdf_bytes[-1024:]
        assert len(pdf_bytes) > 500

    def test_does_not_raise_with_empty_body(self) -> None:
        # P.ej. una plantilla que consiste solo en un marcador que resuelve
        # a cadena vacía (fecha_baja de un empleado todavía activo).
        pdf_bytes = build_document_pdf(
            document_title="Carta de baja",
            employee_name="Ana López",
            body_text="",
            company=_company(),
            generated_at=date(2026, 8, 14),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_ampersand_in_employee_name(self) -> None:
        pdf_bytes = build_document_pdf(
            document_title="Oferta de trabajo",
            employee_name="María & José Muñoz",
            body_text="Estimado/a María & José,\n\nBienvenido/a.",
            company=_company(),
            generated_at=date(2026, 8, 14),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_angle_brackets_in_body(self) -> None:
        pdf_bytes = build_document_pdf(
            document_title="Oferta de trabajo",
            employee_name="Ana López",
            body_text="El puesto es <Ingeniera Senior> a partir del 1 de enero.",
            company=_company(),
            generated_at=date(2026, 8, 14),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_special_characters_in_title(self) -> None:
        # template.name es texto libre -- también hay que escaparlo.
        pdf_bytes = build_document_pdf(
            document_title="Oferta & Contrato <borrador>",
            employee_name="Ana López",
            body_text="Cuerpo del documento.",
            company=_company(),
            generated_at=date(2026, 8, 14),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_non_ascii_names(self) -> None:
        pdf_bytes = build_document_pdf(
            document_title="Carta de baja voluntaria",
            employee_name="María José Muñoz Núñez",
            body_text="Por la presente, María José Muñoz Núñez comunica su baja voluntaria.",
            company=_company(name="Compañía Española de Ñoquis, S.L."),
            generated_at=date(2026, 8, 14),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_a_very_long_body(self) -> None:
        pdf_bytes = build_document_pdf(
            document_title="Contrato",
            employee_name="Ana López",
            body_text="Cláusula de prueba. " * 500,
            company=_company(),
            generated_at=date(2026, 8, 14),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_multiple_paragraphs(self) -> None:
        pdf_bytes = build_document_pdf(
            document_title="Contrato",
            employee_name="Ana López",
            body_text=(
                "Párrafo uno.\n\nPárrafo dos.\n\n"
                "Párrafo tres, con\nun salto de línea suelto."
            ),
            company=_company(),
            generated_at=date(2026, 8, 14),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    def test_does_not_raise_with_empty_optional_company_fields(self) -> None:
        pdf_bytes = build_document_pdf(
            document_title="Oferta de trabajo",
            employee_name="Ana López",
            body_text="Cuerpo del documento.",
            company=_company(name="", nif="", ccc="", address=""),
            generated_at=date(2026, 8, 14),
        )
        assert pdf_bytes.startswith(b"%PDF-")

    # Nota: sin test de salida determinista para la misma entrada -- mismo
    # motivo documentado en tests/test_payroll_pdf.py (reportlab incrusta un
    # /CreationDate real en cada PDF que genera).
