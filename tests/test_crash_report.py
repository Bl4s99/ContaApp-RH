from __future__ import annotations

from datetime import datetime

from app.crash_report import build_crash_report_message, build_crash_report_text
from app.models import EmailConnection

CONNECTION = EmailConnection(provider="gmail", address="hr@example.com", app_password="secret")
OCCURRED_AT = datetime(2026, 8, 4, 14, 30)


class TestBuildCrashReportText:
    def test_includes_exception_type(self) -> None:
        text = build_crash_report_text("ValueError", OCCURRED_AT)
        assert "ValueError" in text

    def test_includes_formatted_date_and_time(self) -> None:
        text = build_crash_report_text("ValueError", OCCURRED_AT)
        assert "04/08/2026" in text
        assert "14:30" in text

    def test_never_includes_a_generic_message_placeholder_as_the_real_detail(self) -> None:
        # No debe colarse el texto/mensaje real de la excepción -- solo el
        # tipo. Comprobación indirecta: la función no recibe ningún mensaje,
        # así que basta con verificar que el texto explica dónde consultarlo.
        text = build_crash_report_text("RuntimeError", OCCURRED_AT)
        assert "logs" in text
        assert "app.log" in text


class TestBuildCrashReportMessage:
    def test_subject_includes_exception_type(self) -> None:
        message = build_crash_report_message(CONNECTION, "KeyError", OCCURRED_AT)
        assert "KeyError" in message["Subject"]

    def test_from_and_to_are_the_connected_address(self) -> None:
        message = build_crash_report_message(CONNECTION, "KeyError", OCCURRED_AT)
        assert message["From"] == "hr@example.com"
        assert message["To"] == "hr@example.com"

    def test_body_contains_crash_report_text(self) -> None:
        message = build_crash_report_message(CONNECTION, "KeyError", OCCURRED_AT)
        assert "KeyError" in message.get_content()
