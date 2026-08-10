"""Capa de conexión configurable: SQLite (por defecto, sin ningún cambio de
comportamiento -- ver database.get_connection()) o PostgreSQL, activado
poniendo la variable de entorno CONTAAPP_RH_DB_URL a una URL
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

Verificado contra un PostgreSQL real (17.10, binarios oficiales de
EnterpriseDB, servidor local desechable): ver tests/test_postgres_integration.py
-- opt-in vía CONTAAPP_RH_TEST_POSTGRES_URL, cubre creación de esquema
desde cero, login case-insensitive, traducción de duplicados y de
violaciones de FK, CRUD con id autogenerado, y búsqueda case-insensitive.
Esa primera ejecución real encontró y corrigió tres bugs que ningún test
contra SQLite podía detectar: `COLLATE NOCASE` en dos consultas de
repository.py (inválido en Postgres, borrado -- ver authenticate() y
authenticate_self_service()), `result.is_insert` de SQLAlchemy siempre
False para SQL en texto plano (dejaba `lastrowid` en None para todo
INSERT, ver PostgresCursor.__init__ e _is_insert_statement()), y
`lastval()` abortando la transacción entera cuando un INSERT no genera
ningún valor de secuencia (ver el SAVEPOINT en PostgresCursor.__init__).
La suite completa de la aplicación (SQLite) sigue pasando sin cambios de
comportamiento a través de esta misma capa -- es la evidencia de que la
abstracción no alteró nada existente."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, Union, runtime_checkable

if TYPE_CHECKING:
    import sqlalchemy

DB_URL_ENV_VAR = "CONTAAPP_RH_DB_URL"
# Fichero junto al .exe (misma carpeta que resuelve app.paths.app_dir(), ver
# database.DEFAULT_DB_PATH/logging_config.LOG_DIR) para que "qué base de
# datos usar" se pueda elegir desde la propia app (ver app/ui.py,
# DatabaseSettingsDialog) sin tocar variables de entorno de Windows a mano.
DB_CONFIG_FILENAME = "db_config.json"


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


def read_configured_db_url(directory: Path) -> str | None:
    """None significa "sin opinión" (fichero ausente, corrupto, o con un
    valor inesperado como "db_url": null) -- database.get_connection() debe
    caer a la variable de entorno en ese caso, nunca impedir el arranque.
    "" (cadena vacía) es distinto: significa que el fichero SÍ existe y
    contiene una elección explícita de "usa el SQLite local", que debe
    prevalecer sobre una variable de entorno que pueda haber quedado puesta
    de antes -- ver DatabaseSettingsDialog, que escribe "" exactamente para
    volver a local. Confundir ambos casos bajo un único "" fue un bug real
    encontrado en la verificación en vivo de este mismo cambio: la elección
    explícita de "Local" desde la interfaz no ganaba a una variable de
    entorno residual."""
    try:
        raw = (directory / DB_CONFIG_FILENAME).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("db_url")
    return value if isinstance(value, str) else None


def write_configured_db_url(directory: Path, db_url: str) -> None:
    """Una cadena vacía significa "usa el SQLite local por defecto"."""
    path = directory / DB_CONFIG_FILENAME
    path.write_text(json.dumps({"db_url": db_url}, ensure_ascii=False, indent=2), encoding="utf-8")


def check_db_connection(url: str) -> None:
    """Abre y cierra inmediatamente -- deja que cualquier excepción se
    propague tal cual, para que quien llama (DatabaseSettingsDialog) la
    muestre al usuario. No se llama test_db_connection a propósito: los
    tests de este módulo importan funciones por nombre, y pytest recolecta
    cualquier test_* como caso de prueba aunque solo esté importado."""
    create_postgres_connection(url).close()


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


def _is_insert_statement(sql: str) -> bool:
    # Suficiente para el SQL propio de este proyecto: cada INSERT empieza
    # literalmente por "INSERT" (sin CTEs "WITH ... INSERT", comprobado por
    # grep) -- no es una detección genérica. Ver PostgresCursor.__init__
    # para por qué hace falta esto en vez de result.is_insert.
    return sql.lstrip().upper().startswith("INSERT")


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
        self,
        result: "sqlalchemy.engine.CursorResult[Any]",
        conn: "sqlalchemy.engine.Connection",
        is_insert: bool,
    ) -> None:
        self._rowcount = result.rowcount
        self._rows: list[_RowAdapter] = []
        self._lastrowid: int | None = None
        if result.returns_rows:
            self._rows = [_RowAdapter(row) for row in result.fetchall()]
        elif is_insert:
            # PostgreSQL no rellena cursor.lastrowid (eso es una extensión
            # de DBAPI propia de sqlite3/MySQL sin equivalente directo en
            # Postgres, que usa RETURNING) -- lastval() devuelve el último
            # valor generado por CUALQUIER secuencia en esta sesión, el
            # mismo papel que lastrowid cumple aquí: siempre se consulta
            # justo después de un INSERT, nunca más tarde.
            #
            # is_insert se recibe ya calculado (ver _is_insert_statement),
            # en vez de usar result.is_insert de SQLAlchemy, porque ese
            # atributo solo funciona para construcciones Core (Insert()) --
            # comprobado empíricamente contra un servidor real que para SQL
            # en texto plano ejecutado vía sqlalchemy.text() (como TODO el
            # SQL de este proyecto, ver el docstring del módulo) siempre
            # vale False incluso para un INSERT real, dejando lastrowid en
            # None para siempre. Bug real, no hipotético: encontrado al
            # ejecutar esto por primera vez contra un PostgreSQL real.
            #
            # lastval() puede fallar con "lastval no está definido en esta
            # sesión" cuando el INSERT no generó ningún valor de secuencia
            # -- p. ej. init_db() inserta las filas semilla de
            # payroll_settings/app_settings con un id explícito (id=1), sin
            # tocar ninguna IDENTITY. Ese caso es real (no hipotético,
            # también encontrado al ejecutar esto por primera vez) y no es
            # un error: simplemente no hay ningún id autogenerado que
            # devolver, igual que sqlite3 tampoco tendría uno significativo
            # que ofrecer para ese mismo INSERT.
            #
            # El intento va dentro de un SAVEPOINT (begin_nested()): en
            # PostgreSQL, un statement que falla dentro de una transacción
            # deja TODA la transacción abortada (cualquier consulta
            # siguiente falla con "current transaction is aborted") hasta
            # un ROLLBACK -- sin el savepoint, capturar la excepción en
            # Python no libera ese estado en el servidor, y la siguiente
            # consulta de quien llama reventaría igualmente aunque no tenga
            # nada que ver con esta.
            import sqlalchemy.exc as sa_exc

            try:
                with conn.begin_nested():
                    lastval_result = conn.execute(_sqlalchemy_text("SELECT lastval()"))
                    self._lastrowid = lastval_result.scalar()
            except sa_exc.OperationalError:
                pass

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
        import sqlalchemy.exc as sa_exc

        named_sql, named_params = _translate_qmark_params(sql, parameters)
        try:
            result = self._conn.execute(_sqlalchemy_text(named_sql), named_params)
        except sa_exc.IntegrityError as exc:
            # repository.py captura sqlite3.IntegrityError en 21 sitios para
            # traducir violaciones de restricción a DuplicateError/
            # ReferenceInUseError -- sqlalchemy.exc.IntegrityError no hereda
            # de esa clase, así que sin esto ninguno de esos except la
            # capturaría contra Postgres y el usuario vería la excepción
            # cruda. str(exc) conserva el mensaje original de Postgres
            # (incluida la cláusula DETAIL con el nombre de columna), que es
            # lo que _duplicate_error() inspecciona por substring.
            raise sqlite3.IntegrityError(str(exc)) from exc
        return PostgresCursor(result, self._conn, is_insert=_is_insert_statement(sql))

    def executescript(self, sql: str) -> None:
        for statement in _split_sql_statements(sql):
            self._conn.execute(_sqlalchemy_text(statement))

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


# Sin esto, un host inalcanzable o bloqueado por firewall depende
# enteramente del timeout TCP por defecto del sistema operativo, que puede
# tardar mucho más de lo razonable para un botón "Probar conexión" que el
# usuario espera ver responder en segundos.
_CONNECT_TIMEOUT_SECONDS = 10


def create_postgres_connection(url: str) -> PostgresConnection:
    # Importado aquí, no al nivel de módulo: quien nunca configura
    # PostgreSQL (la mayoría, con SQLite por defecto) no paga el coste de
    # arranque de cargar SQLAlchemy para nada -- esta función es la ÚNICA
    # puerta de entrada real al camino PostgreSQL.
    import sqlalchemy as sa

    engine = sa.create_engine(url, connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS})
    return PostgresConnection(engine.connect())


# Alias de conveniencia -- útil en sitios que necesitan referirse al tipo
# unión real en vez del Protocol estructural (p. ej. isinstance no funciona
# bien con Protocols que tienen propiedades, solo con métodos).
AnyConnection = Union["sqlite3.Connection", PostgresConnection]
