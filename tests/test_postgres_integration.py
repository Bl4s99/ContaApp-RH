"""Suite de integración real contra PostgreSQL -- a diferencia del resto de
la suite (SQLite en memoria, ver tests/conftest.py), estos tests SÍ abren
una conexión de red real y ejecutan SQL real contra un servidor PostgreSQL.

Opt-in a propósito: se saltan enteros salvo que CONTAAPP_RH_TEST_POSTGRES_URL
esté definida, porque no existe (ni existirá) un servicio PostgreSQL en CI
-- ver .github/workflows/tests.yml. Para levantar un servidor local
desechable (binarios en zip de EnterpriseDB, sin instalador, sin servicio de
Windows) y ejecutar este módulo contra él, ver README.md, sección "Base de
datos configurable (SQLite / PostgreSQL)".

No se toca tests/conftest.py ni su aserción de que la fixture `conn`
compartida por el resto de la suite es SQLite: ese assert sigue protegiendo
al resto de los tests de correr por accidente contra un PostgreSQL real si
CONTAAPP_RH_DB_URL estuviera definida en el entorno. Este módulo define su
propia fixture `conn` (con nombre igual, pero de ámbito de módulo, así que
no colisiona con la de conftest.py) apuntando siempre, explícitamente, a
CONTAAPP_RH_TEST_POSTGRES_URL."""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from app.database import init_db
from app.db_engine import PostgresConnection, create_postgres_connection
from app.repository import (
    DepartmentRepository,
    DuplicateError,
    EmployeeInput,
    EmployeeRepository,
    ReferenceInUseError,
    UserRepository,
)

_TEST_URL_ENV_VAR = "CONTAAPP_RH_TEST_POSTGRES_URL"

pytestmark = pytest.mark.skipif(
    not os.environ.get(_TEST_URL_ENV_VAR),
    reason=f"{_TEST_URL_ENV_VAR} no definida -- ver el docstring de este módulo",
)


def make_input(**overrides: object) -> EmployeeInput:
    defaults: dict[str, object] = dict(
        first_name="Ana",
        last_name="Lopez",
        email="ana.lopez@example.com",
        phone="+34 600 111 222",
        position="Ingeniera",
        department_id=1,
        salary=35000.0,
        hire_date="2023-05-01",
        active=True,
    )
    defaults.update(overrides)
    return EmployeeInput(**defaults)  # type: ignore[arg-type]


@pytest.fixture()
def conn() -> Iterator[PostgresConnection]:
    # DROP/CREATE SCHEMA en vez de envolver en una transacción que se
    # revierte al final: init_db() y transaction() (database.py) ya hacen
    # su propio commit() internamente, así que no existe una única
    # transacción de test que se pueda revertir sin más -- recrear el
    # esquema entero antes de cada test es lo que da aislamiento real.
    # CREATE EXTENSION IF NOT EXISTS citext ya es la primera línea de
    # POSTGRES_SCHEMA_TABLES, así que init_db() se encarga de recrear la
    # extensión (vive en el esquema public que se acaba de borrar) sin
    # necesitar ningún paso adicional aquí.
    url = os.environ[_TEST_URL_ENV_VAR]
    connection = create_postgres_connection(url)
    connection.executescript("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    init_db(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture()
def department_id(conn: PostgresConnection) -> int:
    dept = DepartmentRepository(conn).create("Ingeniería")
    assert dept.id is not None
    return dept.id


class TestSchemaCreation:
    def test_init_db_ran_without_error_and_seeded_defaults(
        self, conn: PostgresConnection
    ) -> None:
        # Llegar aquí ya prueba lo principal: las 334 líneas de
        # POSTGRES_SCHEMA_TABLES (nunca antes ejecutadas contra un servidor
        # real, ver README) se ejecutaron sin ningún error de sintaxis.
        row = conn.execute("SELECT id FROM app_settings WHERE id = 1").fetchone()
        assert row is not None


class TestCaseInsensitiveLogin:
    def test_authenticate_is_case_insensitive_via_citext(
        self, conn: PostgresConnection
    ) -> None:
        # Prueba en vivo el fix de COLLATE NOCASE -> nada (ver
        # repository.py, UserRepository.authenticate): en Postgres la
        # case-insensitividad la da CITEXT a nivel de columna, no una
        # cláusula de la consulta.
        UserRepository(conn).create("Admin", "clave12345")
        user = UserRepository(conn).authenticate("admin", "clave12345")
        assert user is not None
        assert user.username == "Admin"

    def test_authenticate_wrong_password_returns_none(
        self, conn: PostgresConnection
    ) -> None:
        UserRepository(conn).create("Admin", "clave12345")
        assert UserRepository(conn).authenticate("admin", "incorrecta") is None


class TestDuplicateKeyTranslation:
    def test_duplicate_dni_nie_raises_duplicate_error_with_correct_message(
        self, conn: PostgresConnection, department_id: int
    ) -> None:
        # Prueba en vivo la traducción de excepción de db_engine.py
        # (PostgresConnection.execute(): sqlalchemy.exc.IntegrityError ->
        # sqlite3.IntegrityError) Y que _duplicate_error() sigue
        # distinguiendo el campo correcto a partir del mensaje real de
        # Postgres, no solo del de SQLite.
        repo = EmployeeRepository(conn)
        repo.create(make_input(department_id=department_id, dni_nie="12345678Z"))
        with pytest.raises(DuplicateError, match="DNI/NIE"):
            repo.create(
                make_input(
                    department_id=department_id,
                    email="otro@example.com",
                    dni_nie="12345678Z",
                )
            )


class TestForeignKeyViolationTranslation:
    def test_delete_department_in_use_is_blocked(
        self, conn: PostgresConnection, department_id: int
    ) -> None:
        # La otra mitad de la traducción de excepción: una violación de
        # FK (RESTRICT), no solo de índice único.
        EmployeeRepository(conn).create(make_input(department_id=department_id))
        with pytest.raises(ReferenceInUseError):
            DepartmentRepository(conn).delete(department_id)


class TestBasicCrud:
    def test_create_and_get_round_trip_with_lastval_id(
        self, conn: PostgresConnection, department_id: int
    ) -> None:
        # id positivo real via SELECT lastval() (PostgresCursor.lastrowid,
        # ver db_engine.py) -- Postgres no ofrece cursor.lastrowid nativo.
        repo = EmployeeRepository(conn)
        created = repo.create(make_input(department_id=department_id))
        assert created.id is not None
        assert created.id > 0
        fetched = repo.get(created.id)
        assert fetched.email == "ana.lopez@example.com"


class TestCaseInsensitiveSearch:
    def test_search_finds_a_different_capitalization(
        self, conn: PostgresConnection, department_id: int
    ) -> None:
        # Prueba en vivo el fix de LOWER() en EmployeeRepository.search()
        # (repository.py): LIKE es case-sensitive por defecto en Postgres,
        # a diferencia de SQLite.
        repo = EmployeeRepository(conn)
        repo.create(
            make_input(department_id=department_id, first_name="Garcia", email="g@x.com")
        )
        results = repo.search(query="GARCIA")
        assert [e.first_name for e in results] == ["Garcia"]
