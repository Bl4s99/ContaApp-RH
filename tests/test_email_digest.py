from __future__ import annotations

from datetime import date

from app.alerts import Alert
from app.email_digest import build_digest_message, build_digest_text
from app.models import EmailConnection

CONNECTION = EmailConnection(provider="gmail", address="hr@example.com", app_password="secret")


def make_alert(**overrides: object) -> Alert:
    defaults: dict[str, object] = dict(
        employee_id=1,
        employee_name="Ana López",
        category="contrato",
        target_date=date(2026, 8, 1),
        days_remaining=5,
        detail="Contrato vence en 5 día(s)",
    )
    defaults.update(overrides)
    return Alert(**defaults)  # type: ignore[arg-type]


class TestBuildDigestText:
    def test_no_alerts_message(self) -> None:
        assert build_digest_text([]) == "No hay alertas activas esta semana."

    def test_includes_count_and_each_alert(self) -> None:
        alerts = [
            make_alert(employee_name="Ana López", detail="Contrato vence en 5 día(s)"),
            make_alert(employee_name="Luis Pérez", category="cumpleanos", detail="Cumple 30 años hoy"),
        ]
        text = build_digest_text(alerts)
        assert "2 alerta(s)" in text
        assert "Ana López" in text
        assert "Contrato vence en 5 día(s)" in text
        assert "Luis Pérez" in text
        assert "Cumple 30 años hoy" in text

    def test_uses_spanish_category_label(self) -> None:
        text = build_digest_text([make_alert(category="formacion_prl")])
        assert "[Formación PRL]" in text

    def test_unknown_category_falls_back_to_raw_value(self) -> None:
        text = build_digest_text([make_alert(category="algo_nuevo")])
        assert "[algo_nuevo]" in text


class TestBuildDigestMessage:
    def test_subject_includes_alert_count(self) -> None:
        message = build_digest_message(CONNECTION, [make_alert(), make_alert()])
        assert "2 alerta(s)" in message["Subject"]

    def test_from_and_to_are_the_connected_address(self) -> None:
        message = build_digest_message(CONNECTION, [])
        assert message["From"] == "hr@example.com"
        assert message["To"] == "hr@example.com"

    def test_body_contains_digest_text(self) -> None:
        alerts = [make_alert(employee_name="Ana López")]
        message = build_digest_message(CONNECTION, alerts)
        assert "Ana López" in message.get_content()
