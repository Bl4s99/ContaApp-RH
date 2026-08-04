"""Envío del resumen semanal de alertas por correo -- para que una alerta ya
calculada (contrato por vencer, formación PRL pendiente...) no se pase por
alto solo porque nadie abrió la app ese día. Usa `smtplib`/`email` (librería
estándar, sin dependencias nuevas) contra el SMTP del proveedor de correo
que el propio usuario ha conectado en "Mi cuenta..." -- solo Gmail y Outlook
de momento, cada uno con una contraseña de aplicación, no una integración
OAuth real (eso exigiría registrar una app en Google Cloud/Azure antes de
poder implementarse; ver README).

`build_digest_text()`/`build_digest_message()` son puras (sin red) y con
tests; `send_digest_email()` hace E/S de red real y solo se verifica con
smoke tests, misma división que el resto de la app entre lógica pura y
efectos reales."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.alerts import Alert
from app.models import EmailConnection

SMTP_SERVERS = {
    "gmail": ("smtp.gmail.com", 587),
    "outlook": ("smtp.office365.com", 587),
}

_CATEGORY_LABELS = {
    "contrato": "Contrato",
    "cumpleanos": "Cumpleaños",
    "revision_medica": "Revisión médica",
    "retencion_rgpd": "Retención RGPD",
    "formacion_prl": "Formación PRL",
    "certificacion": "Certificación",
}


def build_digest_text(alerts: list[Alert]) -> str:
    if not alerts:
        return "No hay alertas activas esta semana."
    lines = [f"Resumen semanal: {len(alerts)} alerta(s) activa(s).", ""]
    for alert in alerts:
        label = _CATEGORY_LABELS.get(alert.category, alert.category)
        lines.append(f"- [{label}] {alert.employee_name}: {alert.detail}")
    return "\n".join(lines)


def build_digest_message(connection: EmailConnection, alerts: list[Alert]) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"Gestión de Empleados — resumen semanal ({len(alerts)} alerta(s))"
    message["From"] = connection.address
    message["To"] = connection.address
    message.set_content(build_digest_text(alerts))
    return message


def send_digest_email(connection: EmailConnection, alerts: list[Alert]) -> None:
    host, port = SMTP_SERVERS[connection.provider]
    message = build_digest_message(connection, alerts)
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(connection.address, connection.app_password)
        smtp.send_message(message)
