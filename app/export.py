from __future__ import annotations

import csv
from pathlib import Path

from app.models import Department, Employee

_HEADERS = [
    "id",
    "nombre",
    "apellido",
    "dni_nie",
    "email",
    "telefono",
    "puesto",
    "departamento",
    "salario",
    "fecha_ingreso",
    "activo",
    "cuenta_bancaria",
    "num_seguridad_social",
    "tipo_contrato",
    "fecha_fin_contrato",
]


def export_employees_csv(
    employees: list[Employee],
    departments: dict[int, Department],
    file_path: Path | str,
) -> None:
    path = Path(file_path)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(_HEADERS)
        for emp in employees:
            department_name = departments[emp.department_id].name if emp.department_id in departments else ""
            writer.writerow(
                [
                    emp.id,
                    emp.first_name,
                    emp.last_name,
                    emp.dni_nie or "",
                    emp.email,
                    emp.phone,
                    emp.position,
                    department_name,
                    f"{emp.salary:.2f}",
                    emp.hire_date.isoformat(),
                    "sí" if emp.active else "no",
                    emp.bank_account,
                    emp.ss_number or "",
                    emp.contract_type,
                    emp.contract_end_date.isoformat() if emp.contract_end_date else "",
                ]
            )
