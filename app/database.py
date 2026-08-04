from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.paths import app_dir

SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(name)) > 0)
);

CREATE TABLE IF NOT EXISTS day_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(name)) > 0),
    color TEXT NOT NULL
        CHECK(color GLOB '#[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]'),
    is_vacation INTEGER NOT NULL DEFAULT 0 CHECK(is_vacation IN (0, 1))
);

CREATE TABLE IF NOT EXISTS shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(name)) > 0),
    start_time TEXT NOT NULL CHECK(start_time GLOB '[0-2][0-9]:[0-5][0-9]'),
    end_time TEXT NOT NULL CHECK(end_time GLOB '[0-2][0-9]:[0-5][0-9]'),
    start_time_2 TEXT CHECK(start_time_2 IS NULL OR start_time_2 GLOB '[0-2][0-9]:[0-5][0-9]'),
    end_time_2 TEXT CHECK(end_time_2 IS NULL OR end_time_2 GLOB '[0-2][0-9]:[0-5][0-9]'),
    days_of_week TEXT NOT NULL CHECK(length(trim(days_of_week)) > 0),
    UNIQUE(department_id, name),
    CHECK ((start_time_2 IS NULL) = (end_time_2 IS NULL))
);

CREATE TABLE IF NOT EXISTS collective_agreements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(name)) > 0)
);

CREATE TABLE IF NOT EXISTS professional_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collective_agreement_id INTEGER NOT NULL REFERENCES collective_agreements(id) ON DELETE CASCADE,
    name TEXT NOT NULL COLLATE NOCASE CHECK(length(trim(name)) > 0),
    minimum_salary REAL NOT NULL CHECK(minimum_salary >= 0),
    UNIQUE(collective_agreement_id, name)
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL CHECK(length(trim(first_name)) > 0),
    last_name TEXT NOT NULL CHECK(length(trim(last_name)) > 0),
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phone TEXT NOT NULL DEFAULT '',
    position TEXT NOT NULL CHECK(length(trim(position)) > 0),
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
    shift_id INTEGER REFERENCES shifts(id) ON DELETE SET NULL,
    salary REAL NOT NULL CHECK(salary >= 0),
    hire_date TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    bank_account TEXT NOT NULL DEFAULT '',
    photo BLOB,
    dependent_children INTEGER NOT NULL DEFAULT 0 CHECK(dependent_children >= 0),
    dni_nie TEXT COLLATE NOCASE,
    ss_number TEXT,
    contract_type TEXT NOT NULL DEFAULT 'Indefinido' CHECK(contract_type IN
        ('Indefinido', 'Temporal', 'Formación en alternancia', 'Prácticas', 'Fijo-discontinuo')),
    contract_end_date TEXT,
    birth_date TEXT,
    next_medical_checkup_date TEXT,
    termination_date TEXT,
    termination_reason TEXT CHECK(termination_reason IS NULL OR termination_reason IN
        ('Baja voluntaria', 'Despido procedente', 'Despido improcedente',
         'Fin de contrato temporal', 'Jubilación', 'Fallecimiento', 'Otro')),
    anonymized INTEGER NOT NULL DEFAULT 0 CHECK(anonymized IN (0, 1)),
    prl_training_date TEXT,
    manager_id INTEGER REFERENCES employees(id) ON DELETE SET NULL,
    head_of_department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    professional_category_id INTEGER REFERENCES professional_categories(id) ON DELETE SET NULL,
    self_service_pin_hash TEXT,
    self_service_pin_salt TEXT
);

CREATE TABLE IF NOT EXISTS payroll_settings (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    ss_employee_pct REAL NOT NULL CHECK(ss_employee_pct >= 0),
    ss_employer_pct REAL NOT NULL CHECK(ss_employer_pct >= 0)
);

CREATE TABLE IF NOT EXISTS department_closures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    closure_date TEXT NOT NULL,
    day_type_id INTEGER NOT NULL REFERENCES day_types(id) ON DELETE RESTRICT,
    note TEXT NOT NULL DEFAULT '',
    UNIQUE(department_id, closure_date)
);

CREATE TABLE IF NOT EXISTS holiday_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(name)) > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holiday_template_dates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL REFERENCES holiday_templates(id) ON DELETE CASCADE,
    holiday_date TEXT NOT NULL,
    label TEXT NOT NULL,
    UNIQUE(template_id, holiday_date)
);

CREATE TABLE IF NOT EXISTS document_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(name)) > 0),
    body TEXT NOT NULL CHECK(length(trim(body)) > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS onboarding_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(name)) > 0)
);

CREATE TABLE IF NOT EXISTS onboarding_checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES onboarding_tasks(id) ON DELETE RESTRICT,
    completed_at TEXT NOT NULL,
    UNIQUE(employee_id, task_id)
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name TEXT NOT NULL CHECK(length(trim(first_name)) > 0),
    last_name TEXT NOT NULL CHECK(length(trim(last_name)) > 0),
    email TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    position TEXT NOT NULL CHECK(length(trim(position)) > 0),
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE RESTRICT,
    phase TEXT NOT NULL CHECK(phase IN
        ('Recibido', 'Entrevista', 'Oferta', 'Contratado', 'Descartado')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employee_absences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    absence_date TEXT NOT NULL,
    day_type_id INTEGER NOT NULL REFERENCES day_types(id) ON DELETE RESTRICT,
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'aprobada' CHECK(status IN ('pendiente', 'aprobada', 'rechazada')),
    previous_day_type_id INTEGER REFERENCES day_types(id) ON DELETE SET NULL,
    previous_note TEXT,
    UNIQUE(employee_id, absence_date)
);

CREATE TABLE IF NOT EXISTS daily_shift_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    assignment_date TEXT NOT NULL,
    shift_id INTEGER NOT NULL REFERENCES shifts(id) ON DELETE RESTRICT,
    UNIQUE(employee_id, assignment_date)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK(length(trim(username)) > 0),
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'admin' CHECK(role IN ('admin', 'encargado')),
    department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    email_provider TEXT CHECK(email_provider IS NULL OR email_provider IN ('gmail', 'outlook')),
    email_address TEXT,
    email_app_password TEXT,
    last_digest_sent_at TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    theme_mode TEXT NOT NULL DEFAULT 'light' CHECK(theme_mode IN ('light', 'dark')),
    annual_vacation_days REAL NOT NULL DEFAULT 22 CHECK(annual_vacation_days >= 0),
    data_retention_years INTEGER NOT NULL DEFAULT 4 CHECK(data_retention_years >= 0)
);

CREATE TABLE IF NOT EXISTS employee_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    filename TEXT NOT NULL CHECK(length(trim(filename)) > 0),
    category TEXT NOT NULL CHECK(category IN ('Contrato', 'DNI/NIE', 'Certificado', 'Otro')),
    content BLOB NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payroll_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
    generated_at TEXT NOT NULL,
    annual_gross_salary_snapshot REAL NOT NULL,
    dependent_children_snapshot INTEGER NOT NULL,
    paga_ordinaria REAL NOT NULL,
    paga_extra REAL NOT NULL,
    supplements_total REAL NOT NULL DEFAULT 0,
    bruto_mes REAL NOT NULL,
    irpf_pct REAL NOT NULL,
    irpf_importe REAL NOT NULL,
    ss_employee_pct REAL NOT NULL,
    ss_employee_importe REAL NOT NULL,
    advances_total REAL NOT NULL DEFAULT 0,
    neto REAL NOT NULL,
    ss_employer_pct REAL NOT NULL,
    ss_employer_importe REAL NOT NULL,
    coste_total_empresa REAL NOT NULL,
    UNIQUE(employee_id, year, month)
);

CREATE TABLE IF NOT EXISTS time_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    entry_type TEXT NOT NULL CHECK(entry_type IN ('entrada', 'salida')),
    entry_timestamp TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS employee_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    position TEXT NOT NULL CHECK(length(trim(position)) > 0),
    salary REAL NOT NULL CHECK(salary >= 0),
    effective_date TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS payroll_supplements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
    supplement_type TEXT NOT NULL CHECK(supplement_type IN ('plus', 'horas_extra', 'anticipo')),
    description TEXT NOT NULL CHECK(length(trim(description)) > 0),
    amount REAL NOT NULL CHECK(amount > 0),
    hours REAL CHECK(hours IS NULL OR hours > 0),
    rate_per_hour REAL CHECK(rate_per_hour IS NULL OR rate_per_hour > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS severance_settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    termination_date TEXT NOT NULL,
    termination_reason TEXT NOT NULL,
    hire_date TEXT NOT NULL,
    annual_gross_salary REAL NOT NULL CHECK(annual_gross_salary >= 0),
    annual_vacation_days REAL NOT NULL CHECK(annual_vacation_days >= 0),
    vacation_days_used_this_year INTEGER NOT NULL CHECK(vacation_days_used_this_year >= 0),
    vacation_days_pending REAL NOT NULL CHECK(vacation_days_pending >= 0),
    vacation_amount REAL NOT NULL CHECK(vacation_amount >= 0),
    extra_payment_months_accrued INTEGER NOT NULL CHECK(extra_payment_months_accrued >= 0),
    extra_payment_amount REAL NOT NULL CHECK(extra_payment_amount >= 0),
    total_amount REAL NOT NULL CHECK(total_amount >= 0),
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_accidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    accident_date TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('Leve', 'Grave', 'Muy grave', 'Mortal')),
    description TEXT NOT NULL CHECK(length(trim(description)) > 0),
    caused_leave INTEGER NOT NULL DEFAULT 0 CHECK(caused_leave IN (0, 1)),
    reported_to_authority INTEGER NOT NULL DEFAULT 0 CHECK(reported_to_authority IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS it_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    contingency TEXT NOT NULL CHECK(contingency IN
        ('Común', 'Accidente de trabajo', 'Accidente no laboral')),
    leave_date TEXT NOT NULL,
    last_confirmation_date TEXT,
    return_date TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employee_trainings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    completion_date TEXT NOT NULL,
    expiration_date TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employee_objectives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
    target_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendiente' CHECK(status IN ('pendiente', 'cumplido', 'no_cumplido')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS performance_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    review_date TEXT NOT NULL,
    comments TEXT NOT NULL CHECK(length(trim(comments)) > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assigned_equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    description TEXT NOT NULL CHECK(length(trim(description)) > 0),
    assigned_date TEXT NOT NULL,
    returned_date TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    CHECK (returned_date IS NULL OR returned_date >= assigned_date)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username TEXT NOT NULL,
    -- Deliberadamente SIN la lista cerrada de códigos válidos que tenía al
    -- principio (action IN (...)): SQLite no permite ampliar un CHECK ya
    -- existente con ALTER TABLE, así que cada código nuevo habría exigido
    -- recrear la tabla entera (ver _migrate_audit_log_action_check). La
    -- lista real de códigos válidos vive únicamente en las constantes
    -- AUDIT_* de app/repository.py, la única fuente de verdad.
    action TEXT NOT NULL CHECK(length(trim(action)) > 0),
    details TEXT NOT NULL DEFAULT ''
);
"""

SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_employees_department ON employees(department_id);
CREATE INDEX IF NOT EXISTS idx_employees_active ON employees(active);
CREATE INDEX IF NOT EXISTS idx_employees_shift ON employees(shift_id);
CREATE INDEX IF NOT EXISTS idx_shifts_department ON shifts(department_id);
CREATE INDEX IF NOT EXISTS idx_closures_department_date ON department_closures(department_id, closure_date);
CREATE INDEX IF NOT EXISTS idx_absences_employee_date ON employee_absences(employee_id, absence_date);
CREATE INDEX IF NOT EXISTS idx_assignments_employee_date ON daily_shift_assignments(employee_id, assignment_date);
CREATE INDEX IF NOT EXISTS idx_assignments_shift ON daily_shift_assignments(shift_id);
CREATE INDEX IF NOT EXISTS idx_time_entries_employee_timestamp ON time_entries(employee_id, entry_timestamp);
CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_dni_nie ON employees(dni_nie);
CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_ss_number ON employees(ss_number);
CREATE INDEX IF NOT EXISTS idx_payroll_records_employee ON payroll_records(employee_id);
CREATE INDEX IF NOT EXISTS idx_employee_documents_employee ON employee_documents(employee_id);
CREATE INDEX IF NOT EXISTS idx_employee_history_employee ON employee_history(employee_id, effective_date);
CREATE INDEX IF NOT EXISTS idx_payroll_supplements_employee_period
    ON payroll_supplements(employee_id, year, month);
CREATE INDEX IF NOT EXISTS idx_severance_settlements_employee
    ON severance_settlements(employee_id, generated_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_occurred_at ON audit_log(occurred_at);
CREATE INDEX IF NOT EXISTS idx_work_accidents_employee ON work_accidents(employee_id, accident_date);
CREATE INDEX IF NOT EXISTS idx_it_episodes_employee ON it_episodes(employee_id, leave_date);
CREATE INDEX IF NOT EXISTS idx_employees_manager ON employees(manager_id);
CREATE INDEX IF NOT EXISTS idx_employees_head_of_department ON employees(head_of_department_id);
CREATE INDEX IF NOT EXISTS idx_employees_professional_category ON employees(professional_category_id);
CREATE INDEX IF NOT EXISTS idx_professional_categories_agreement ON professional_categories(collective_agreement_id);
CREATE INDEX IF NOT EXISTS idx_employee_trainings_employee
    ON employee_trainings(employee_id, completion_date);
CREATE INDEX IF NOT EXISTS idx_employee_objectives_employee
    ON employee_objectives(employee_id, target_date);
CREATE INDEX IF NOT EXISTS idx_performance_reviews_employee
    ON performance_reviews(employee_id, review_date);
CREATE INDEX IF NOT EXISTS idx_assigned_equipment_employee
    ON assigned_equipment(employee_id, assigned_date);
"""

DEFAULT_DB_PATH = app_dir() / "empleados.db"


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # El fichero .db suele vivir en una carpeta compartida en red para que
    # varios equipos usen la app a la vez -- cuando dos escritores chocan
    # (poco frecuente: cada escritura va en una transacción corta, de
    # milisegundos), SQLite debe REINTENTAR un rato antes de rendirse en vez
    # de fallar al instante. 5000ms iguala el timeout que sqlite3.connect()
    # ya aplicaba de forma implícita (su parámetro timeout=5.0 por defecto);
    # se fija aquí de forma explícita para que no dependa de ese valor por
    # defecto ni se pierda si algún día cambia. Se descarta WAL a propósito:
    # mejora lector-contra-escritor, no escritor-contra-escritor (que es el
    # caso real aquí), y su fichero -shm no es fiable sobre recursos
    # compartidos de red (SMB) -- ver README, sección "Concurrencia".
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


DEFAULT_SS_EMPLOYEE_PCT = 6.35
DEFAULT_SS_EMPLOYER_PCT = 31.40


def init_db(conn: sqlite3.Connection) -> None:
    # Defensive: FK enforcement (RESTRICT/CASCADE/SET NULL) is a no-op in SQLite
    # unless this pragma is set on the connection. get_connection() already sets
    # it, but init_db() is public and shouldn't silently lose FK enforcement if
    # ever called with a connection that didn't go through get_connection().
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_TABLES)
    _migrate_employees_shift_id(conn)
    _migrate_employees_bank_account_and_photo(conn)
    _migrate_employees_dependent_children(conn)
    _migrate_shifts_split_schedule(conn)
    _migrate_employees_dni_ss(conn)
    _migrate_day_types_is_vacation(conn)
    _migrate_app_settings_vacation_days(conn)
    _migrate_employee_absences_status(conn)
    _migrate_users_role_and_department(conn)
    _migrate_users_email_digest(conn)
    _migrate_backfill_employee_history(conn)
    _migrate_employees_alerts_fields(conn)
    _migrate_payroll_records_supplements(conn)
    _migrate_employees_termination_fields(conn)
    _migrate_employees_anonymized(conn)
    _migrate_employees_prl_training_date(conn)
    _migrate_audit_log_action_check(conn)
    _migrate_employee_absences_previous_state(conn)
    _migrate_employees_manager_id(conn)
    _migrate_employees_head_of_department_id(conn)
    _migrate_employees_professional_category_id(conn)
    _migrate_employees_self_service_pin(conn)
    conn.executescript(SCHEMA_INDEXES)
    conn.execute(
        "INSERT OR IGNORE INTO payroll_settings (id, ss_employee_pct, ss_employer_pct) "
        "VALUES (1, ?, ?)",
        (DEFAULT_SS_EMPLOYEE_PCT, DEFAULT_SS_EMPLOYER_PCT),
    )
    conn.execute("INSERT OR IGNORE INTO app_settings (id, theme_mode) VALUES (1, 'light')")
    conn.commit()


def _employees_columns(conn: sqlite3.Connection) -> set[str]:
    # Indexed access (not row["name"]) so this works regardless of the
    # connection's row_factory (PRAGMA table_info columns: cid, name, type, ...).
    return {row[1] for row in conn.execute("PRAGMA table_info(employees)").fetchall()}


def _migrate_employees_shift_id(conn: sqlite3.Connection) -> None:
    if "shift_id" not in _employees_columns(conn):
        conn.execute(
            "ALTER TABLE employees ADD COLUMN shift_id "
            "INTEGER REFERENCES shifts(id) ON DELETE SET NULL"
        )


def _migrate_employees_bank_account_and_photo(conn: sqlite3.Connection) -> None:
    columns = _employees_columns(conn)
    if "bank_account" not in columns:
        conn.execute("ALTER TABLE employees ADD COLUMN bank_account TEXT NOT NULL DEFAULT ''")
    if "photo" not in columns:
        conn.execute("ALTER TABLE employees ADD COLUMN photo BLOB")


def _migrate_employees_dependent_children(conn: sqlite3.Connection) -> None:
    if "dependent_children" not in _employees_columns(conn):
        conn.execute(
            "ALTER TABLE employees ADD COLUMN dependent_children "
            "INTEGER NOT NULL DEFAULT 0 CHECK(dependent_children >= 0)"
        )


def _migrate_shifts_split_schedule(conn: sqlite3.Connection) -> None:
    # Note: SQLite can't ALTER TABLE ADD a table-level CHECK constraint on an
    # existing table, so the "both or neither" rule for start_time_2/end_time_2
    # is enforced in Python (validation.validate_split_shift) for DBs migrated
    # this way. Fresh databases get the stronger CHECK from SCHEMA_TABLES too.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(shifts)").fetchall()}
    if "start_time_2" not in columns:
        conn.execute(
            "ALTER TABLE shifts ADD COLUMN start_time_2 "
            "TEXT CHECK(start_time_2 IS NULL OR start_time_2 GLOB '[0-2][0-9]:[0-5][0-9]')"
        )
    if "end_time_2" not in columns:
        conn.execute(
            "ALTER TABLE shifts ADD COLUMN end_time_2 "
            "TEXT CHECK(end_time_2 IS NULL OR end_time_2 GLOB '[0-2][0-9]:[0-5][0-9]')"
        )


def _migrate_employees_dni_ss(conn: sqlite3.Connection) -> None:
    # No inline UNIQUE here (or on the ALTER TABLE below): SQLite's ALTER
    # TABLE ADD COLUMN can't carry a UNIQUE constraint. Uniqueness for
    # dni_nie is enforced uniformly for both fresh and migrated databases by
    # the separate idx_employees_dni_nie index in SCHEMA_INDEXES instead,
    # which runs after this migration either way.
    columns = _employees_columns(conn)
    if "dni_nie" not in columns:
        conn.execute("ALTER TABLE employees ADD COLUMN dni_nie TEXT COLLATE NOCASE")
    if "ss_number" not in columns:
        conn.execute("ALTER TABLE employees ADD COLUMN ss_number TEXT")
    if "contract_type" not in columns:
        # A single-column CHECK (referencing only the new column itself) can
        # be added via ALTER TABLE ADD COLUMN and IS enforced afterwards --
        # verified empirically; SQLite only rejects multi-column/table-level
        # CHECK constraints this way (see the split-shift migration above).
        conn.execute(
            "ALTER TABLE employees ADD COLUMN contract_type TEXT NOT NULL "
            "DEFAULT 'Indefinido' CHECK(contract_type IN "
            "('Indefinido', 'Temporal', 'Formación en alternancia', 'Prácticas', 'Fijo-discontinuo'))"
        )
    if "contract_end_date" not in columns:
        conn.execute("ALTER TABLE employees ADD COLUMN contract_end_date TEXT")


def _migrate_day_types_is_vacation(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(day_types)").fetchall()}
    if "is_vacation" not in columns:
        conn.execute(
            "ALTER TABLE day_types ADD COLUMN is_vacation "
            "INTEGER NOT NULL DEFAULT 0 CHECK(is_vacation IN (0, 1))"
        )
        # One-time backfill: an existing database's "Vacaciones" day type
        # (seeded by every install before this migration existed) should
        # count toward the vacation balance from day one, same as it would
        # on a fresh install. Later renames are the admin's call, not ours.
        conn.execute(
            "UPDATE day_types SET is_vacation = 1 WHERE name = 'Vacaciones' COLLATE NOCASE"
        )


def _migrate_app_settings_vacation_days(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(app_settings)").fetchall()}
    if "annual_vacation_days" not in columns:
        conn.execute(
            "ALTER TABLE app_settings ADD COLUMN annual_vacation_days "
            "REAL NOT NULL DEFAULT 22 CHECK(annual_vacation_days >= 0)"
        )
    if "data_retention_years" not in columns:
        conn.execute(
            "ALTER TABLE app_settings ADD COLUMN data_retention_years "
            "INTEGER NOT NULL DEFAULT 4 CHECK(data_retention_years >= 0)"
        )


def _migrate_employee_absences_status(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(employee_absences)").fetchall()}
    if "status" not in columns:
        # Every pre-existing absence was, by definition, directly marked by
        # an admin under the old (request-less) flow -- DEFAULT 'aprobada'
        # correctly backfills all of them as already-confirmed.
        conn.execute(
            "ALTER TABLE employee_absences ADD COLUMN status TEXT NOT NULL "
            "DEFAULT 'aprobada' CHECK(status IN ('pendiente', 'aprobada', 'rechazada'))"
        )


def _migrate_employee_absences_previous_state(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(employee_absences)").fetchall()}
    if "previous_day_type_id" not in columns:
        conn.execute(
            "ALTER TABLE employee_absences ADD COLUMN previous_day_type_id "
            "INTEGER REFERENCES day_types(id) ON DELETE SET NULL"
        )
    if "previous_note" not in columns:
        conn.execute("ALTER TABLE employee_absences ADD COLUMN previous_note TEXT")


def _migrate_users_role_and_department(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "role" not in columns:
        # Every pre-existing account (in practice, just the single seeded
        # "admin" user -- there was no UI to create others before this
        # migration) correctly backfills as role='admin': that was already
        # its real-world role, since the old schema had no other concept.
        conn.execute(
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL "
            "DEFAULT 'admin' CHECK(role IN ('admin', 'encargado'))"
        )
    if "department_id" not in columns:
        conn.execute(
            "ALTER TABLE users ADD COLUMN department_id "
            "INTEGER REFERENCES departments(id) ON DELETE SET NULL"
        )


def _migrate_users_email_digest(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "email_provider" not in columns:
        conn.execute(
            "ALTER TABLE users ADD COLUMN email_provider TEXT "
            "CHECK(email_provider IS NULL OR email_provider IN ('gmail', 'outlook'))"
        )
    if "email_address" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN email_address TEXT")
    if "email_app_password" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN email_app_password TEXT")
    if "last_digest_sent_at" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN last_digest_sent_at TEXT")


def _migrate_employees_alerts_fields(conn: sqlite3.Connection) -> None:
    columns = _employees_columns(conn)
    if "birth_date" not in columns:
        conn.execute("ALTER TABLE employees ADD COLUMN birth_date TEXT")
    if "next_medical_checkup_date" not in columns:
        conn.execute("ALTER TABLE employees ADD COLUMN next_medical_checkup_date TEXT")


def _migrate_employees_termination_fields(conn: sqlite3.Connection) -> None:
    columns = _employees_columns(conn)
    if "termination_date" not in columns:
        conn.execute("ALTER TABLE employees ADD COLUMN termination_date TEXT")
    if "termination_reason" not in columns:
        # CHECK de una sola columna: sí se aplica vía ALTER TABLE ADD COLUMN
        # (verificado ya con contract_type) -- ver esa migración para el porqué.
        conn.execute(
            "ALTER TABLE employees ADD COLUMN termination_reason TEXT "
            "CHECK(termination_reason IS NULL OR termination_reason IN "
            "('Baja voluntaria', 'Despido procedente', 'Despido improcedente', "
            "'Fin de contrato temporal', 'Jubilación', 'Fallecimiento', 'Otro'))"
        )


def _migrate_employees_anonymized(conn: sqlite3.Connection) -> None:
    if "anonymized" not in _employees_columns(conn):
        conn.execute(
            "ALTER TABLE employees ADD COLUMN anonymized "
            "INTEGER NOT NULL DEFAULT 0 CHECK(anonymized IN (0, 1))"
        )


def _migrate_employees_prl_training_date(conn: sqlite3.Connection) -> None:
    if "prl_training_date" not in _employees_columns(conn):
        conn.execute("ALTER TABLE employees ADD COLUMN prl_training_date TEXT")


def _migrate_employees_manager_id(conn: sqlite3.Connection) -> None:
    if "manager_id" not in _employees_columns(conn):
        conn.execute(
            "ALTER TABLE employees ADD COLUMN manager_id "
            "INTEGER REFERENCES employees(id) ON DELETE SET NULL"
        )


def _migrate_employees_head_of_department_id(conn: sqlite3.Connection) -> None:
    if "head_of_department_id" not in _employees_columns(conn):
        conn.execute(
            "ALTER TABLE employees ADD COLUMN head_of_department_id "
            "INTEGER REFERENCES departments(id) ON DELETE SET NULL"
        )


def _migrate_employees_professional_category_id(conn: sqlite3.Connection) -> None:
    if "professional_category_id" not in _employees_columns(conn):
        conn.execute(
            "ALTER TABLE employees ADD COLUMN professional_category_id "
            "INTEGER REFERENCES professional_categories(id) ON DELETE SET NULL"
        )


def _migrate_employees_self_service_pin(conn: sqlite3.Connection) -> None:
    columns = _employees_columns(conn)
    if "self_service_pin_hash" not in columns:
        conn.execute("ALTER TABLE employees ADD COLUMN self_service_pin_hash TEXT")
    if "self_service_pin_salt" not in columns:
        conn.execute("ALTER TABLE employees ADD COLUMN self_service_pin_salt TEXT")


def _migrate_audit_log_action_check(conn: sqlite3.Connection) -> None:
    """audit_log.action empezó con un CHECK de lista cerrada (action IN
    (...)); se afloja aquí a "no vacío" porque SQLite no permite ampliar un
    CHECK ya existente con ALTER TABLE -- cada código nuevo habría exigido
    este mismo procedimiento de todos modos, así que se hace una vez y no
    hace falta repetirlo cada vez que se añade un AUDIT_* nuevo en Python.
    Solo actúa si la tabla ya existe con el CHECK viejo (una base de datos
    recién creada ya sale con el CHECK laxo directamente desde
    SCHEMA_TABLES, y esta consulta detecta eso y no hace nada)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'audit_log'"
    ).fetchone()
    # Acceso posicional (row[0], no row["sql"]) para que funcione con
    # cualquier row_factory de la conexión -- mismo criterio defensivo que
    # _employees_columns() más arriba.
    if row is None or row[0] is None or "action IN (" not in row[0]:
        return
    conn.executescript(
        """
        ALTER TABLE audit_log RENAME TO audit_log_old;
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            username TEXT NOT NULL,
            action TEXT NOT NULL CHECK(length(trim(action)) > 0),
            details TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO audit_log SELECT * FROM audit_log_old;
        DROP TABLE audit_log_old;
        """
    )


def _migrate_payroll_records_supplements(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(payroll_records)").fetchall()}
    # DEFAULT 0 correctly backfills every already-generated record: it was
    # frozen before this feature existed, so it genuinely had no supplements
    # or advances applied at the time -- 0 is its real historical value, not
    # a guess. A later "Regenerar..." naturally picks up any that exist now.
    if "supplements_total" not in columns:
        conn.execute(
            "ALTER TABLE payroll_records ADD COLUMN supplements_total REAL NOT NULL DEFAULT 0"
        )
    if "advances_total" not in columns:
        conn.execute(
            "ALTER TABLE payroll_records ADD COLUMN advances_total REAL NOT NULL DEFAULT 0"
        )


def _migrate_backfill_employee_history(conn: sqlite3.Connection) -> None:
    # Not a schema migration (employee_history is a brand-new table, already
    # created by SCHEMA_TABLES) -- a one-time DATA backfill so employees that
    # already existed before this feature shipped start with an initial
    # history entry too, instead of an empty history until their next edit.
    # Idempotent by construction: any employee that already has at least one
    # row (backfilled before, or created fresh via EmployeeRepository.create,
    # which records its own initial entry) is excluded and left untouched.
    rows = conn.execute(
        """
        SELECT id, position, salary, hire_date FROM employees
        WHERE id NOT IN (SELECT DISTINCT employee_id FROM employee_history)
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO employee_history (employee_id, position, salary, effective_date, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                row["id"],
                row["position"],
                row["salary"],
                row["hire_date"],
                "Historial inicial (creado automáticamente)",
            ),
        )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
