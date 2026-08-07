from __future__ import annotations

import inspect
import sqlite3
import threading
from pathlib import Path

from app import database
from app.database import get_connection, init_db

# conn fixture is function-scoped in tests/conftest.py.


class TestMigrationsAreWiredUp:
    """Regresión: _migrate_employees_manager_id() se escribió por completo
    (columna en SCHEMA_TABLES, índice en SCHEMA_INDEXES, la propia función
    de migración) pero nunca se añadió a la secuencia de llamadas de
    init_db() -- un error real que llegó a producción (bloqueaba el
    arranque de la app real contra el empleados.db ya existente, creado
    antes de que esa columna existiera) sin que ningún test lo detectara,
    porque tests/conftest.py siempre parte de una base de datos :memory:
    recién creada, donde SCHEMA_TABLES ya incluye cualquier columna nueva
    desde el principio -- la función de migración en sí nunca se ejercita
    en ese caso, con o sin la llamada que faltaba. Solo una base de datos
    YA EXISTENTE sin la columna (como una real, escrita por una versión
    anterior del código) puede detectar esto."""

    def test_every_migrate_function_is_called_from_init_db(self) -> None:
        # No verifica que una migración concreta sea correcta, solo que
        # ninguna quede huérfana -- escrita y nunca invocada.
        source = inspect.getsource(database.init_db)
        migration_functions = [
            name
            for name, obj in vars(database).items()
            if name.startswith("_migrate_") and inspect.isfunction(obj)
        ]
        assert migration_functions, "no se encontró ninguna función _migrate_* en app.database"
        orphaned = [name for name in migration_functions if name not in source]
        assert not orphaned, f"migraciones nunca llamadas desde init_db(): {orphaned}"

    def test_init_db_backfills_manager_id_on_a_database_created_without_it(
        self, conn: sqlite3.Connection
    ) -> None:
        # Simula un empleados.db real creado antes de que esta columna
        # existiera: se parte de una base de datos ya inicializada (con la
        # columna y su índice) y se eliminan ambos, para reproducir el
        # esquema "antiguo" sin duplicar a mano el CREATE TABLE de todas
        # las versiones previas. El índice debe eliminarse antes que la
        # columna -- SQLite rechaza dejar un índice apuntando a una
        # columna que ya no existe.
        conn.execute("DROP INDEX idx_employees_manager")
        conn.execute("ALTER TABLE employees DROP COLUMN manager_id")
        init_db(conn)  # no debe fallar, y debe dejar la columna otra vez
        columns = {row[1] for row in conn.execute("PRAGMA table_info(employees)").fetchall()}
        assert "manager_id" in columns

    def test_init_db_backfills_company_nif_on_a_database_created_without_it(
        self, conn: sqlite3.Connection
    ) -> None:
        # Mismo motivo que el test de manager_id de arriba: simula un
        # empleados.db real escrito antes de que company_nif existiera.
        conn.execute("ALTER TABLE app_settings DROP COLUMN company_nif")
        init_db(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(app_settings)").fetchall()}
        assert "company_nif" in columns

    def test_init_db_is_idempotent_on_an_already_migrated_database(
        self, conn: sqlite3.Connection
    ) -> None:
        # conn ya pasó por init_db() una vez (vía el fixture) -- llamarlo
        # de nuevo sobre una base de datos ya al día no debe fallar.
        init_db(conn)

    def test_init_db_works_on_a_brand_new_database_file(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "nuevo.db")
        try:
            init_db(conn)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(employees)").fetchall()}
            assert "manager_id" in columns
        finally:
            conn.close()


class TestConcurrentWrites:
    """Varios equipos en red pueden abrir el mismo fichero .db a la vez --
    ver la nota junto a `PRAGMA busy_timeout` en get_connection(). Estos
    tests verifican el comportamiento REAL (no solo teórico) confirmado con
    un script empírico: dos escritores que chocan no fallan al instante,
    SQLite reintenta durante busy_timeout antes de rendirse."""

    def test_get_connection_sets_an_explicit_busy_timeout(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "test.db")
        try:
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        finally:
            conn.close()

    def test_a_brief_write_lock_does_not_fail_a_concurrent_writer(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "concurrencia.db"
        setup_conn = get_connection(db_path)
        init_db(setup_conn)
        setup_conn.close()

        # El hilo "holder" abre y usa su PROPIA conexión de principio a fin
        # -- sqlite3 exige que cada conexión se use solo desde el hilo que
        # la creó, así que no puede compartirse con el hilo principal.
        ready = threading.Event()

        def hold_lock_briefly() -> None:
            conn = get_connection(db_path)
            conn.execute("INSERT INTO departments (name) VALUES ('Titular')")
            ready.set()
            threading.Event().wait(0.3)
            conn.commit()
            conn.close()

        holder = threading.Thread(target=hold_lock_briefly)
        holder.start()
        ready.wait()  # el holder ya tiene el lock de escritura abierto

        waiter = get_connection(db_path)
        try:
            # No debe lanzar sqlite3.OperationalError: 0.3s está muy por
            # debajo del busy_timeout de 5000ms, así que debe esperar a que
            # el holder confirme y luego tener éxito.
            waiter.execute("INSERT INTO departments (name) VALUES ('Esperando')")
            waiter.commit()
        finally:
            holder.join()
            waiter.close()

        names = {
            row[0]
            for row in get_connection(db_path).execute("SELECT name FROM departments").fetchall()
        }
        assert names == {"Titular", "Esperando"}

    def test_a_fresh_database_does_not_default_to_wal(self, tmp_path: Path) -> None:
        # Decisión deliberada (ver comentario en get_connection()): WAL no
        # es fiable sobre recursos compartidos de red y no ayuda en el caso
        # real (dos escritores, no lector-contra-escritor). Este test
        # protege esa decisión de un cambio accidental futuro.
        conn = get_connection(tmp_path / "sin_wal.db")
        try:
            init_db(conn)
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal"
        finally:
            conn.close()
