from __future__ import annotations

import sqlite3
import tkinter as tk
from collections.abc import Iterator

import pytest

from app.database import get_connection, init_db


@pytest.fixture()
def conn() -> Iterator[sqlite3.Connection]:
    connection = get_connection(":memory:")
    # Toda la suite asume SQLite real (algunos tests capturan
    # sqlite3.IntegrityError directamente, por ejemplo) -- si
    # CONTAAPP_RH_DB_URL estuviera definida en el entorno de quien
    # ejecuta los tests, get_connection() ignoraría ":memory:" y conectaría
    # a un PostgreSQL real en su lugar, lo que ejecutaría toda la suite
    # (con sus operaciones de escritura) contra una base de datos ajena sin
    # avisar. Este assert lo convierte en un fallo inmediato y explícito en
    # vez de un comportamiento silenciosamente distinto según el entorno.
    assert isinstance(connection, sqlite3.Connection), (
        "conn fixture esperaba SQLite -- ¿CONTAAPP_RH_DB_URL está definida?"
    )
    init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(scope="session")
def tk_root() -> Iterator[tk.Tk]:
    # Session-scoped and shared across every test module that needs a live Tk
    # interpreter (widget tests, image-to-PhotoImage conversion, ...). Creating
    # and destroying separate Tcl interpreters per module was still enough
    # churn to intermittently corrupt Tcl's library-path state on Windows;
    # one interpreter for the whole run is the reliable fix.
    root = tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()
