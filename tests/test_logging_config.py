from __future__ import annotations

import logging
import sys
import tkinter as tk
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import logging_config

# tk_root fixture is session-scoped in tests/conftest.py.


@pytest.fixture()
def isolated_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirige LOG_DIR/LOG_FILE a un directorio temporal y deja el logger
    "gestion_empleados" limpio antes y después de cada test -- es un
    logger con nombre global (logging.getLogger reutiliza la misma
    instancia en todo el proceso), así que un handler que sobreviviera a
    un test intentaría escribir en un tmp_path ya borrado desde cualquier
    otro sitio del proceso que use el mismo logger."""
    log_file = tmp_path / "logs" / "app.log"
    monkeypatch.setattr(logging_config, "LOG_DIR", log_file.parent)
    monkeypatch.setattr(logging_config, "LOG_FILE", log_file)
    logger = logging.getLogger(logging_config.LOGGER_NAME)
    logger.handlers.clear()
    try:
        yield log_file
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()


class TestConfigureLogging:
    def test_creates_the_log_file_and_writes_real_messages(self, isolated_log: Path) -> None:
        logger = logging_config.configure_logging()
        logger.info("mensaje de prueba")
        for handler in logger.handlers:
            handler.flush()
        assert isolated_log.exists()
        content = isolated_log.read_text(encoding="utf-8")
        assert "mensaje de prueba" in content
        assert "INFO" in content

    def test_calling_it_twice_does_not_duplicate_handlers(self, isolated_log: Path) -> None:
        logger = logging_config.configure_logging()
        logging_config.configure_logging()
        assert len(logger.handlers) == 1


class TestLogUncaughtException:
    def test_logs_the_exception_type_message_and_traceback(self, isolated_log: Path) -> None:
        logging_config.configure_logging()
        try:
            raise ValueError("fallo de prueba")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()
            assert exc_type is not None and exc_value is not None
            logging_config.log_uncaught_exception(exc_type, exc_value, exc_tb)
        logger = logging.getLogger(logging_config.LOGGER_NAME)
        for handler in logger.handlers:
            handler.flush()
        content = isolated_log.read_text(encoding="utf-8")
        assert "Excepción no controlada fuera de la interfaz" in content
        assert "ValueError" in content
        assert "fallo de prueba" in content
        assert "CRITICAL" in content

    def test_keyboard_interrupt_is_not_logged_as_a_failure(
        self, isolated_log: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logging_config.configure_logging()
        # sys.__excepthook__ escribiría a stderr real; lo silenciamos para
        # que este test no ensucie la salida de la suite.
        monkeypatch.setattr(sys, "__excepthook__", lambda *a: None)
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            exc_type, exc_value, exc_tb = sys.exc_info()
            assert exc_type is not None and exc_value is not None
            logging_config.log_uncaught_exception(exc_type, exc_value, exc_tb)
        logger = logging.getLogger(logging_config.LOGGER_NAME)
        for handler in logger.handlers:
            handler.flush()
        assert not isolated_log.exists() or isolated_log.read_text(encoding="utf-8") == ""


class TestInstallTkExceptionHook:
    def test_captures_a_real_exception_from_a_button_callback(
        self, tk_root: tk.Tk, isolated_log: Path
    ) -> None:
        original_hook = tk.Tk.report_callback_exception
        logging_config.configure_logging()
        logging_config.install_tk_exception_hook()

        def _boom() -> None:
            raise RuntimeError("boom desde un callback")

        button = tk.Button(tk_root, text="x", command=_boom)
        try:
            button.invoke()
            tk_root.update()
            logger = logging.getLogger(logging_config.LOGGER_NAME)
            for handler in logger.handlers:
                handler.flush()
            content = isolated_log.read_text(encoding="utf-8")
            assert "Excepción en un callback de la interfaz" in content
            assert "boom desde un callback" in content
        finally:
            button.destroy()
            # Restaura el hook por defecto -- este test lo sustituye a
            # nivel de CLASE (tk.Tk), así que sin esto afectaría a
            # cualquier otro test que comparta el tk_root de sesión.
            tk.Tk.report_callback_exception = original_hook

    def test_calls_on_exception_after_logging(self, tk_root: tk.Tk, isolated_log: Path) -> None:
        original_hook = tk.Tk.report_callback_exception
        logging_config.configure_logging()
        received: list[tuple[type[BaseException], BaseException]] = []
        logging_config.install_tk_exception_hook(
            on_exception=lambda exc, val: received.append((exc, val))
        )

        def _boom() -> None:
            raise RuntimeError("boom con aviso adicional")

        button = tk.Button(tk_root, text="x", command=_boom)
        try:
            button.invoke()
            tk_root.update()
            assert len(received) == 1
            exc_type, exc_value = received[0]
            assert exc_type is RuntimeError
            assert str(exc_value) == "boom con aviso adicional"
        finally:
            button.destroy()
            tk.Tk.report_callback_exception = original_hook

    def test_a_failing_on_exception_is_caught_and_logged_not_propagated(
        self, tk_root: tk.Tk, isolated_log: Path
    ) -> None:
        original_hook = tk.Tk.report_callback_exception
        logging_config.configure_logging()

        def _broken_notifier(
            _exc: type[BaseException], _val: BaseException
        ) -> None:
            raise OSError("sin conexión de red")

        logging_config.install_tk_exception_hook(on_exception=_broken_notifier)

        def _boom() -> None:
            raise RuntimeError("boom original")

        button = tk.Button(tk_root, text="x", command=_boom)
        try:
            button.invoke()  # no debe propagar el OSError de _broken_notifier
            tk_root.update()
            logger = logging.getLogger(logging_config.LOGGER_NAME)
            for handler in logger.handlers:
                handler.flush()
            content = isolated_log.read_text(encoding="utf-8")
            assert "boom original" in content
            assert "Fallo al ejecutar el aviso adicional de excepción" in content
        finally:
            button.destroy()
            tk.Tk.report_callback_exception = original_hook
