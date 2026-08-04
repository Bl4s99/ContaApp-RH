from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from app.backup import BackupRepository, apply_pending_restore, format_backup_size


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "empleados.db"


def test_create_backup_copies_real_data(conn: sqlite3.Connection, tmp_path: Path) -> None:
    conn.execute("INSERT INTO departments (name) VALUES ('Ventas')")
    conn.commit()
    repo = BackupRepository(conn, _db_path(tmp_path))

    backup_path = repo.create_backup()

    assert backup_path.parent == repo.backups_dir
    assert backup_path.exists()
    check_conn = sqlite3.connect(backup_path)
    try:
        row = check_conn.execute("SELECT name FROM departments").fetchone()
    finally:
        check_conn.close()
    assert row is not None
    assert row[0] == "Ventas"


def test_create_backup_filename_uses_db_stem_as_prefix(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = BackupRepository(conn, _db_path(tmp_path))
    backup_path = repo.create_backup()
    assert backup_path.name.startswith("empleados_")
    assert backup_path.suffix == ".db"


def test_create_backup_called_twice_in_a_row_never_collides(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    # Dos llamadas seguidas (p. ej. dentro de stage_restore: copia de
    # seguridad del estado actual + lectura de la copia elegida) deben
    # producir SIEMPRE archivos distintos -- si coincidieran de nombre, la
    # segunda sobrescribiría en silencio el contenido de la primera.
    repo = BackupRepository(conn, _db_path(tmp_path))
    first = repo.create_backup()
    second = repo.create_backup()
    assert first != second
    assert first.exists()
    assert second.exists()


def test_list_backups_empty_when_no_backups_dir(conn: sqlite3.Connection, tmp_path: Path) -> None:
    repo = BackupRepository(conn, _db_path(tmp_path))
    assert repo.list_backups() == []


def test_list_backups_sorted_newest_first(conn: sqlite3.Connection, tmp_path: Path) -> None:
    repo = BackupRepository(conn, _db_path(tmp_path))
    repo.backups_dir.mkdir(parents=True)
    (repo.backups_dir / "empleados_20260101_090000_000000.db").write_bytes(b"x")
    (repo.backups_dir / "empleados_20260301_120000_000000.db").write_bytes(b"x")
    (repo.backups_dir / "empleados_20260201_150000_000000.db").write_bytes(b"x")

    backups = repo.list_backups()

    assert [b.created_at for b in backups] == [
        datetime(2026, 3, 1, 12, 0, 0),
        datetime(2026, 2, 1, 15, 0, 0),
        datetime(2026, 1, 1, 9, 0, 0),
    ]


def test_list_backups_ignores_files_that_do_not_match_the_pattern(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = BackupRepository(conn, _db_path(tmp_path))
    repo.backups_dir.mkdir(parents=True)
    (repo.backups_dir / "empleados_20260101_090000_000000.db").write_bytes(b"x")
    (repo.backups_dir / "empleados_not_a_timestamp.db").write_bytes(b"x")
    (repo.backups_dir / "otra_cosa_20260101_090000_000000.db").write_bytes(b"x")
    (repo.backups_dir / "empleados_20260101_090000_000000.txt").write_bytes(b"x")

    backups = repo.list_backups()

    assert len(backups) == 1
    assert backups[0].path.name == "empleados_20260101_090000_000000.db"


def test_has_backup_today(conn: sqlite3.Connection, tmp_path: Path) -> None:
    repo = BackupRepository(conn, _db_path(tmp_path))
    assert repo.has_backup_today() is False
    repo.create_backup()
    assert repo.has_backup_today() is True


def test_prune_old_backups_keeps_newest_n(conn: sqlite3.Connection, tmp_path: Path) -> None:
    repo = BackupRepository(conn, _db_path(tmp_path))
    repo.backups_dir.mkdir(parents=True)
    for name in [
        "empleados_20260101_090000_000000.db",
        "empleados_20260102_090000_000000.db",
        "empleados_20260103_090000_000000.db",
        "empleados_20260104_090000_000000.db",
    ]:
        (repo.backups_dir / name).write_bytes(b"x")

    deleted = repo.prune_old_backups(keep=2)

    remaining = {b.path.name for b in repo.list_backups()}
    assert remaining == {
        "empleados_20260104_090000_000000.db",
        "empleados_20260103_090000_000000.db",
    }
    assert {p.name for p in deleted} == {
        "empleados_20260101_090000_000000.db",
        "empleados_20260102_090000_000000.db",
    }


def test_create_backup_prunes_automatically(conn: sqlite3.Connection, tmp_path: Path) -> None:
    repo = BackupRepository(conn, _db_path(tmp_path))
    repo.backups_dir.mkdir(parents=True)
    for name in [
        "empleados_20260101_090000_000000.db",
        "empleados_20260102_090000_000000.db",
    ]:
        (repo.backups_dir / name).write_bytes(b"x")

    new_backup = repo.create_backup(prune_keep=1)

    remaining = repo.list_backups()
    assert len(remaining) == 1
    assert remaining[0].path == new_backup


def test_create_backup_prune_keep_none_does_not_prune(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    repo = BackupRepository(conn, _db_path(tmp_path))
    repo.backups_dir.mkdir(parents=True)
    for name in [
        "empleados_20260101_090000_000000.db",
        "empleados_20260102_090000_000000.db",
    ]:
        (repo.backups_dir / name).write_bytes(b"x")

    repo.create_backup(prune_keep=None)

    assert len(repo.list_backups()) == 3


def test_stage_restore_and_apply_pending_restore_round_trip(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    conn.execute("INSERT INTO departments (name) VALUES ('Original')")
    conn.commit()
    db_path = _db_path(tmp_path)
    repo = BackupRepository(conn, db_path)

    old_backup = repo.create_backup()  # snapshot con "Original"

    conn.execute("UPDATE departments SET name = 'Modificado'")
    conn.commit()

    safety = repo.stage_restore(old_backup)

    # la copia de seguridad tomada justo antes de restaurar refleja el
    # estado justo antes de la restauración ("Modificado"), no el original
    # -- y es un archivo DISTINTO de old_backup, no lo sobrescribe.
    assert safety != old_backup
    safety_conn = sqlite3.connect(safety)
    try:
        row = safety_conn.execute("SELECT name FROM departments").fetchone()
    finally:
        safety_conn.close()
    assert row is not None and row[0] == "Modificado"

    pending_marker = db_path.with_name(db_path.name + ".pending_restore")
    assert pending_marker.exists()
    assert not db_path.exists()  # todavía no se ha aplicado nada

    applied = apply_pending_restore(db_path)

    assert applied is True
    assert db_path.exists()
    assert not pending_marker.exists()  # el marcador se consume al aplicar

    restored_conn = sqlite3.connect(db_path)
    try:
        row = restored_conn.execute("SELECT name FROM departments").fetchone()
    finally:
        restored_conn.close()
    assert row is not None and row[0] == "Original"


def test_apply_pending_restore_returns_false_when_nothing_pending(tmp_path: Path) -> None:
    assert apply_pending_restore(_db_path(tmp_path)) is False


@pytest.mark.parametrize(
    "size_bytes, expected",
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1 KB"),
        (10 * 1024, "10 KB"),
        (1024 * 1024, "1.0 MB"),
        (int(2.5 * 1024 * 1024), "2.5 MB"),
    ],
)
def test_format_backup_size(size_bytes: int, expected: str) -> None:
    assert format_backup_size(size_bytes) == expected
