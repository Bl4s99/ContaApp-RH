from __future__ import annotations

import logging
import logging.handlers
import sys
import tkinter as tk
from collections.abc import Callable
from types import TracebackType

from app.paths import app_dir

LOG_DIR = app_dir() / "logs"
LOG_FILE = LOG_DIR / "app.log"
LOGGER_NAME = "gestion_empleados"

# Los mensajes que se registran aquí (excepciones no controladas, fallos de
# backup/envío de correo) son siempre trazas técnicas -- ningún punto de
# este módulo añade DNI/salario/IBAN a un mensaje de log a propósito. Dicho
# esto, una excepción real puede incluir un valor identificativo en su
# propio texto (algunos mensajes de error de este proyecto son así de
# específicos a propósito, ej. "ya existe un empleado con el email 'x'") --
# el log nunca sale de este ordenador, así que el riesgo es el mismo que ya
# asumía `empleados.db`, no uno nuevo, pero por eso el log vive junto a
# `backups/`, con el mismo nivel de confianza, no se sube a ningún sitio.


def configure_logging() -> logging.Logger:
    """Logging a un archivo local con rotación (5 archivos de 1 MB) --
    nunca se envía nada fuera de este ordenador. Segura de llamar más de
    una vez (no duplica el handler)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    return logger


def log_uncaught_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """Para `sys.excepthook` -- cubre lo que pase FUERA del bucle de
    eventos de Tkinter (ej. durante el arranque, antes de que exista
    ninguna ventana). `KeyboardInterrupt` se deja pasar tal cual: no es un
    fallo, es el usuario pidiendo salir."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logging.getLogger(LOGGER_NAME).critical(
        "Excepción no controlada fuera de la interfaz",
        exc_info=(exc_type, exc_value, exc_tb),
    )


def install_tk_exception_hook(
    on_exception: Callable[[type[BaseException], BaseException], None] | None = None,
) -> None:
    """Sustituye `Tk.report_callback_exception`, el método que Tkinter
    llama para CUALQUIER excepción no controlada dentro de un callback
    (clic de botón, atajo de teclado, etc.). Por defecto solo la imprime a
    stderr -- en la versión compilada `--windowed` no hay stderr visible,
    así que la excepción desaparecía sin dejar rastro. Se sustituye a
    nivel de clase (no en cada ventana por separado) para cubrir tanto
    `LoginWindow` como `MainWindow` con una sola llamada.

    `on_exception`, si se indica, se llama DESPUÉS de registrar en el log
    local -- pensado para app.crash_report.notify_crash_report_recipients,
    que este módulo deliberadamente no importa (dependencia cero, como el
    resto de logging_config.py); quien instale el hook decide si hay algo
    más que hacer aparte de loguear. Un fallo dentro de `on_exception` (ej.
    sin conexión de red) se registra como aviso y no se propaga: una
    excepción dentro del manejador de excepciones no debe tapar la
    original ni reventar Tkinter."""

    def _report_callback_exception(
        self: tk.Misc,
        exc: type[BaseException],
        val: BaseException,
        tb: TracebackType | None,
    ) -> None:
        logging.getLogger(LOGGER_NAME).error(
            "Excepción en un callback de la interfaz", exc_info=(exc, val, tb)
        )
        if on_exception is not None:
            try:
                on_exception(exc, val)
            except Exception:
                logging.getLogger(LOGGER_NAME).warning(
                    "Fallo al ejecutar el aviso adicional de excepción", exc_info=True
                )

    # El stub de typeshed tipa este atributo como un Callable YA ligado (sin
    # `self`), pero en tiempo de ejecución una función asignada a nivel de
    # clase se liga igualmente a la instancia (protocolo descriptor normal
    # de Python) -- desajuste solo de tipado, no de comportamiento real.
    tk.Tk.report_callback_exception = _report_callback_exception  # type: ignore[assignment]
