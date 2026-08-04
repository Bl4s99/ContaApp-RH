from __future__ import annotations

from app.db_engine import (
    _split_sql_statements,
    _translate_qmark_params,
    is_postgres_url,
)


class TestIsPostgresUrl:
    def test_accepts_postgresql_scheme(self) -> None:
        assert is_postgres_url("postgresql://user:pass@host/db") is True

    def test_accepts_postgres_scheme(self) -> None:
        assert is_postgres_url("postgres://user:pass@host/db") is True

    def test_rejects_empty_string(self) -> None:
        assert is_postgres_url("") is False

    def test_rejects_sqlite_path(self) -> None:
        assert is_postgres_url("C:\\empleados.db") is False

    def test_rejects_mysql_scheme(self) -> None:
        assert is_postgres_url("mysql://user:pass@host/db") is False


class TestTranslateQmarkParams:
    def test_no_placeholders(self) -> None:
        sql, params = _translate_qmark_params("SELECT * FROM employees", ())
        assert sql == "SELECT * FROM employees"
        assert params == {}

    def test_single_placeholder(self) -> None:
        sql, params = _translate_qmark_params("SELECT * FROM employees WHERE id = ?", (5,))
        assert sql == "SELECT * FROM employees WHERE id = :p0"
        assert params == {"p0": 5}

    def test_multiple_placeholders_in_order(self) -> None:
        sql, params = _translate_qmark_params(
            "INSERT INTO employees (first_name, last_name, salary) VALUES (?, ?, ?)",
            ("Ana", "López", 28000.0),
        )
        assert sql == "INSERT INTO employees (first_name, last_name, salary) VALUES (:p0, :p1, :p2)"
        assert params == {"p0": "Ana", "p1": "López", "p2": 28000.0}

    def test_ignores_question_mark_inside_string_literal(self) -> None:
        sql, params = _translate_qmark_params(
            "SELECT * FROM employees WHERE note = '¿qué tal?' AND id = ?", (5,)
        )
        assert sql == "SELECT * FROM employees WHERE note = '¿qué tal?' AND id = :p0"
        assert params == {"p0": 5}

    def test_multiple_string_literals_with_real_placeholders_between(self) -> None:
        sql, params = _translate_qmark_params(
            "UPDATE t SET a = 'x?y', b = ? WHERE c = 'p?q' AND d = ?", ("val1", "val2")
        )
        assert sql == "UPDATE t SET a = 'x?y', b = :p0 WHERE c = 'p?q' AND d = :p1"
        assert params == {"p0": "val1", "p1": "val2"}

    def test_preserves_param_values_of_various_types(self) -> None:
        sql, params = _translate_qmark_params(
            "INSERT INTO t (a, b, c) VALUES (?, ?, ?)", (1, None, 3.5)
        )
        assert params == {"p0": 1, "p1": None, "p2": 3.5}

    def test_real_query_shape_with_many_placeholders(self) -> None:
        sql = (
            "UPDATE users SET email_provider = ?, email_address = ?, "
            "email_app_password = ? WHERE id = ?"
        )
        translated_sql, params = _translate_qmark_params(sql, ("gmail", "a@b.com", "secret", 7))
        assert translated_sql == (
            "UPDATE users SET email_provider = :p0, email_address = :p1, "
            "email_app_password = :p2 WHERE id = :p3"
        )
        assert params == {"p0": "gmail", "p1": "a@b.com", "p2": "secret", "p3": 7}


class TestSplitSqlStatements:
    def test_splits_on_semicolon(self) -> None:
        script = "CREATE TABLE a (id INTEGER); CREATE TABLE b (id INTEGER);"
        statements = _split_sql_statements(script)
        assert statements == ["CREATE TABLE a (id INTEGER)", "CREATE TABLE b (id INTEGER)"]

    def test_ignores_blank_statements(self) -> None:
        script = "CREATE TABLE a (id INTEGER);;\n\n;CREATE TABLE b (id INTEGER);"
        statements = _split_sql_statements(script)
        assert statements == ["CREATE TABLE a (id INTEGER)", "CREATE TABLE b (id INTEGER)"]

    def test_strips_surrounding_whitespace(self) -> None:
        script = "\n  CREATE TABLE a (id INTEGER)  ;\n"
        statements = _split_sql_statements(script)
        assert statements == ["CREATE TABLE a (id INTEGER)"]

    def test_empty_script_returns_empty_list(self) -> None:
        assert _split_sql_statements("") == []

    def test_no_trailing_semicolon(self) -> None:
        assert _split_sql_statements("CREATE TABLE a (id INTEGER)") == [
            "CREATE TABLE a (id INTEGER)"
        ]
