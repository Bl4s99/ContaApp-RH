from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from app.export import export_employees_csv
from app.models import Department, Employee


def make_employee(**overrides: object) -> Employee:
    defaults: dict[str, object] = dict(
        id=1,
        first_name="Ana",
        last_name="Lopez",
        email="ana@example.com",
        phone="+34 600 111 222",
        position="Ingeniera",
        department_id=1,
        shift_id=None,
        salary=35000.0,
        hire_date=date(2023, 5, 1),
        active=True,
        bank_account="ES91 2100 0418 4502 0005 1332",
        photo=None,
        dependent_children=0,
        dni_nie="12345678Z",
        ss_number="281234567890",
        contract_type="Indefinido",
        contract_end_date=None,
        birth_date=None,
        next_medical_checkup_date=None,
        termination_date=None,
        termination_reason=None,
        anonymized=False,
        prl_training_date=None,
        manager_id=None,
        head_of_department_id=None,
        professional_category_id=None,
    )
    defaults.update(overrides)
    return Employee(**defaults)  # type: ignore[arg-type]


def test_export_includes_bank_account_column(tmp_path: Path) -> None:
    departments = {1: Department(id=1, name="Ventas")}
    out_path = tmp_path / "empleados.csv"

    export_employees_csv([make_employee()], departments, out_path)

    with out_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["cuenta_bancaria"] == "ES91 2100 0418 4502 0005 1332"
    assert rows[0]["departamento"] == "Ventas"
    assert rows[0]["activo"] == "sí"


def test_export_handles_blank_bank_account(tmp_path: Path) -> None:
    departments = {1: Department(id=1, name="Ventas")}
    out_path = tmp_path / "empleados.csv"

    export_employees_csv([make_employee(bank_account="")], departments, out_path)

    with out_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["cuenta_bancaria"] == ""


def test_export_handles_unknown_department(tmp_path: Path) -> None:
    out_path = tmp_path / "empleados.csv"

    export_employees_csv([make_employee(department_id=999)], {}, out_path)

    with out_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["departamento"] == ""


def test_export_includes_dni_nie_and_ss_number(tmp_path: Path) -> None:
    departments = {1: Department(id=1, name="Ventas")}
    out_path = tmp_path / "empleados.csv"

    export_employees_csv([make_employee()], departments, out_path)

    with out_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["dni_nie"] == "12345678Z"
    assert rows[0]["num_seguridad_social"] == "281234567890"


def test_export_handles_missing_dni_nie_and_ss_number(tmp_path: Path) -> None:
    departments = {1: Department(id=1, name="Ventas")}
    out_path = tmp_path / "empleados.csv"

    export_employees_csv(
        [make_employee(dni_nie=None, ss_number=None)], departments, out_path
    )

    with out_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["dni_nie"] == ""
    assert rows[0]["num_seguridad_social"] == ""
