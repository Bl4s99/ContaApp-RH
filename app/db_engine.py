"""Capa de conexión configurable: SQLite (por defecto, sin ningún cambio de
comportamiento -- ver database.get_connection()) o PostgreSQL, activado
poniendo la variable de entorno GESTION_EMPLEADOS_DB_URL a una URL
postgresql://. Pensada para el modelo de "cada empresa, su propia
instalación" (ver README): la mayoría seguirá con SQLite sin tocar nada;
una empresa que ya tenga su propio PostgreSQL puede apuntar la app ahí
cambiando solo esta variable.

La pieza central es PostgresConnection: expone la MISMA interfaz mínima
que sqlite3.Connection ya ofrecía (.execute()/.executescript()/.commit()/
.rollback()/.close(), filas con acceso row["columna"]) sobre un motor
SQLAlchemy -- así ninguna de las ~230 consultas de app/repository.py ha
tenido que reescribirse, solo el tipo de conexión que reciben
(sqlite3.Connection | PostgresConnection, unificados bajo el Protocol
DbConnection). Todo el SQL de este proyecto ya estaba escrito en SQL
estándar con marcadores posicionales '?' (estilo sqlite3) -- la única
traducción real que hace falta es de marcador posicional a marcador con
nombre (":p0", ":p1"...), que es lo único que sqlalchemy.text() acepta
para no atarse a un driver concreto. Ver _translate_qmark_params().

Límite honesto, no escondido: este adaptador se ha verificado con un
ejercicio exhaustivo de tests (ver tests/test_db_engine.py) y contra la
suite completa de la aplicación corriendo sobre SQLite a través de él,
pero NO se ha podido ejecutar ni una sola vez contra un PostgreSQL real en
este entorno (sin servidor disponible, y no es apropiado instalar uno
como parte de esta tarea). El camino PostgreSQL es sólido por diseño y
por revisión, no por verificación empírica -- quien lo active por primera
vez en un PostgreSQL real debería tratarlo como recién estrenado, no como
ya probado en producción."""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, Union, runtime_checkable

if TYPE_CHECKING:
    import sqlite3

    import sqlalchemy

DB_URL_ENV_VAR = "GESTION_EMPLEADOS_DB_URL"


@runtime_checkable
class DbCursor(Protocol):
    def fetchone(self) -> Any: ...
    def fetchall(self) -> list[Any]: ...
    @property
    def lastrowid(self) -> int | None: ...
    @property
    def rowcount(self) -> int: ...


@runtime_checkable
class DbConnection(Protocol):
    """Subconjunto mínimo de sqlite3.Connection que app/repository.py y
    app/database.py realmente usan -- tanto sqlite3.Connection como
    PostgresConnection lo satisfacen de forma estructural (duck typing),
    así que cualquiera de las dos puede pasarse donde se espera este tipo
    sin ningún cast ni # type: ignore."""

    def execute(self, sql: str, parameters: Sequence[object] = ...) -> DbCursor: ...
    def executescript(self, sql: str) -> object: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


def is_postgres_url(url: str) -> bool:
    return url.startswith("postgresql://") or url.startswith("postgres://")


def _translate_qmark_params(
    sql: str, params: Sequence[object]
) -> tuple[str, dict[str, object]]:
    """Convierte SQL con marcadores posicionales '?' (estilo sqlite3, el
    único que usa este proyecto) a marcadores con nombre ':p0', ':p1'...
    (lo que exige sqlalchemy.text(), independiente de driver) y su tupla
    de parámetros posicional al dict correspondiente. No traduce ningún
    '?' que esté dentro de una cadena entre comillas simples, para no
    romper una consulta que compare contra un valor literal que contenga
    el propio carácter '?' -- ver tests/test_db_engine.py."""
    result_chars: list[str] = []
    named_params: dict[str, object] = {}
    param_index = 0
    in_string = False
    for ch in sql:
        if ch == "'":
            in_string = not in_string
            result_chars.append(ch)
        elif ch == "?" and not in_string:
            name = f"p{param_index}"
            result_chars.append(f":{name}")
            named_params[name] = params[param_index]
            param_index += 1
        else:
            result_chars.append(ch)
    return "".join(result_chars), named_params


def _split_sql_statements(script: str) -> list[str]:
    # Suficiente para el DDL propio de este proyecto (sentencias CREATE
    # TABLE/CREATE INDEX simples, sin ningún ';' dentro de una cadena de
    # texto ni bloques $$...$$ de funciones PL/pgSQL) -- no es un parser de
    # SQL genérico.
    return [stmt.strip() for stmt in script.split(";") if stmt.strip()]


class _RowAdapter:
    """Una fila de SQLAlchemy con acceso por nombre de columna
    (row["columna"]) además de por posición (row[0]) -- mismo interfaz que
    sqlite3.Row, que es como app/repository.py ya accede a cada fila en
    todas sus consultas."""

    __slots__ = ("_row",)

    def __init__(self, row: "sqlalchemy.engine.Row[Any]") -> None:
        self._row = row

    def __getitem__(self, key: str | int) -> object:
        if isinstance(key, str):
            return self._row._mapping[key]
        return self._row[key]

    def __repr__(self) -> str:
        return f"_RowAdapter({tuple(self._row)!r})"


class PostgresCursor:
    def __init__(
        self, result: "sqlalchemy.engine.CursorResult[Any]", conn: "sqlalchemy.engine.Connection"
    ) -> None:
        self._rowcount = result.rowcount
        self._rows: list[_RowAdapter] = []
        self._lastrowid: int | None = None
        if result.returns_rows:
            self._rows = [_RowAdapter(row) for row in result.fetchall()]
        elif result.is_insert:
            # PostgreSQL no rellena cursor.lastrowid (eso es una extensión
            # de DBAPI propia de sqlite3/MySQL sin equivalente directo en
            # Postgres, que usa RETURNING) -- lastval() devuelve el último
            # valor generado por CUALQUIER secuencia en esta sesión, el
            # mismo papel que lastrowid cumple aquí: siempre se consulta
            # justo después de un INSERT, nunca más tarde.
            lastval_result = conn.execute(_sqlalchemy_text("SELECT lastval()"))
            self._lastrowid = lastval_result.scalar()

    def fetchone(self) -> _RowAdapter | None:
        if not self._rows:
            return None
        return self._rows.pop(0)

    def fetchall(self) -> list[_RowAdapter]:
        rows, self._rows = self._rows, []
        return rows

    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    @property
    def rowcount(self) -> int:
        return self._rowcount


def _sqlalchemy_text(sql: str) -> Any:
    import sqlalchemy as sa

    return sa.text(sql)


class PostgresConnection:
    """Ver el docstring del módulo. `sa_connection` ya viene con una
    transacción abierta (SQLAlchemy 2.0 la abre implícitamente en el
    primer execute()); commit()/rollback() cierran esa transacción y
    SQLAlchemy abre la siguiente sola, igual que sqlite3 con
    isolation_level por defecto."""

    def __init__(self, sa_connection: "sqlalchemy.engine.Connection") -> None:
        self._conn = sa_connection

    def execute(self, sql: str, parameters: Sequence[object] = ()) -> PostgresCursor:
        named_sql, named_params = _translate_qmark_params(sql, parameters)
        result = self._conn.execute(_sqlalchemy_text(named_sql), named_params)
        return PostgresCursor(result, self._conn)

    def executescript(self, sql: str) -> None:
        for statement in _split_sql_statements(sql):
            self._conn.execute(_sqlalchemy_text(statement))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def create_postgres_connection(url: str) -> PostgresConnection:
    # Importado aquí, no al nivel de módulo: quien nunca configura
    # PostgreSQL (la mayoría, con SQLite por defecto) no paga el coste de
    # arranque de cargar SQLAlchemy para nada -- esta función es la ÚNICA
    # puerta de entrada real al camino PostgreSQL.
    import sqlalchemy as sa

    engine = sa.create_engine(url)
    return PostgresConnection(engine.connect())


# Alias de conveniencia -- útil en sitios que necesitan referirse al tipo
# unión real en vez del Protocol estructural (p. ej. isinstance no funciona
# bien con Protocols que tienen propiedades, solo con métodos).
AnyConnection = Union["sqlite3.Connection", PostgresConnection]
