"""Aviso por correo cuando la aplicación falla en el ordenador de un cliente
-- sin esto, "sin observabilidad" significaba que nadie se enteraba salvo
que lo contaran a mano (ver logging_config.py para el log local, que sigue
existiendo sin cambios). Reutiliza el mismo SMTP que el resumen semanal
(app/email_digest.py), pero es una suscripción aparte: activarla exige
tener ya un correo conectado en "Mi cuenta...", no se activa sola por tener
el resumen semanal activado.

Deliberadamente NO incluye el mensaje ni la traza de la excepción: eso ya
vive en el log local (`logs/app.log`), que nunca sale de este ordenador a
propósito. Un correo real SÍ sale de este ordenador, así que aquí solo va
el tipo de excepción y cuándo ocurrió -- nunca el texto completo, que en
este proyecto a veces incluye un valor identificativo real (ver el mismo
aviso en logging_config.py).

`build_crash_report_text()`/`build_crash_report_message()` son puras (sin
red) y con tests; `send_crash_report_email()` hace E/S de red real y no
tiene test propio, misma división que email_digest.py."""
from __future__ import annotations

import logging
import smtplib
import threading
from collections.abc import Sequence
from datetime import datetime
from email.message import EmailMessage

from app.email_digest import SMTP_SERVERS
from app.logging_config import LOGGER_NAME
from app.models import EmailConnection


def build_crash_report_text(exception_type_name: str, occurred_at: datetime) -> str:
    return (
        "La aplicación ContaApp RH tuvo un fallo no controlado "
        f"el {occurred_at:%d/%m/%Y} a las {occurred_at:%H:%M}.\n\n"
        f"Tipo de excepción: {exception_type_name}\n\n"
        "Por privacidad, este aviso no incluye el mensaje completo del "
        'error -- consulta el registro local (carpeta "logs", archivo '
        "app.log) en el ordenador donde ocurrió para ver el detalle."
    )


def build_crash_report_message(
    connection: EmailConnection, exception_type_name: str, occurred_at: datetime
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"ContaApp RH — fallo detectado ({exception_type_name})"
    message["From"] = connection.address
    message["To"] = connection.address
    message.set_content(build_crash_report_text(exception_type_name, occurred_at))
    return message


def send_crash_report_email(
    connection: EmailConnection, exception_type_name: str, occurred_at: datetime
) -> None:
    host, port = SMTP_SERVERS[connection.provider]
    message = build_crash_report_message(connection, exception_type_name, occurred_at)
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(connection.address, connection.app_password)
        smtp.send_message(message)


def notify_recipients_in_background(
    recipients: Sequence[EmailConnection], exception_type_name: str, occurred_at: datetime
) -> None:
    """Envía el aviso a cada destinatario en un hilo aparte -- un fallo real
    ya es un mal momento para que, encima, la ventana se quede congelada
    varios segundos esperando una conexión SMTP. Cada destinatario se
    intenta por separado: que uno falle (contraseña de aplicación caducada,
    sin conexión...) no impide avisar a los demás. El hilo es daemon a
    propósito -- si la app se cierra a mitad del envío, no debe impedir que
    el proceso termine."""
    if not recipients:
        return

    def _send_all() -> None:
        logger = logging.getLogger(LOGGER_NAME)
        for connection in recipients:
            try:
                send_crash_report_email(connection, exception_type_name, occurred_at)
            except (smtplib.SMTPException, OSError) as exc:
                logger.warning(
                    "No se pudo enviar el aviso de fallo a %s: %s", connection.address, exc
                )

    threading.Thread(target=_send_all, daemon=True).start()
