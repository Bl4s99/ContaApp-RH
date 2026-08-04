"""Exportación estructurada de nóminas ya generadas para una gestoría
externa -- un CSV bien documentado con los datos que hacen falta para
revisar/importar una nómina (identidad fiscal, desglose completo del
cálculo, IBAN), no un intento de replicar el formato de importación exacto
de un programa concreto (A3, Sage, ContaPlus...). Esta app no puede
prometer compatibilidad byte a byte con ninguno de ellos sin haberlo
investigado caso a caso; lo que sí puede garantizar es que cada columna
está documentada y que los mismos números ya se ven en la página de
Nóminas, así que siempre hay algo con lo que contrastar.

Separador `;` y decimales con coma (no `,`/`.` al estilo EE. UU.):
convención habitual de hojas de cálculo y programas de gestión en España,
coherente con cómo esta misma app ya muestra los importes en pantalla
(_format_currency en payroll_ui.py/employee_page.py). Las fechas SÍ se
quedan en ISO (AAAA-MM-DD) en vez de DD/MM/AAAA: es lo único que un
importador automático no puede interpretar mal por ambigüedad de orden."""
from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.models import Employee, PayrollRecord

_CSV_HEADER = [
    "dni_nie",
    "num_seguridad_social",
    "nombre_completo",
    "departamento",
    "puesto",
    "tipo_contrato",
    "fecha_ingreso",
    "anio",
    "mes",
    "salario_bruto_anual",
    "bruto_mes",
    "irpf_pct",
    "irpf_importe",
    "ss_trabajador_pct",
    "ss_trabajador_importe",
    "complementos",
    "anticipos",
    "neto",
    "ss_empresa_pct",
    "ss_empresa_importe",
    "coste_total_empresa",
    "iban",
]


@dataclass(frozen=True, slots=True)
class GestoriaRow:
    dni_nie: str
    ss_number: str
    full_name: str
    department_name: str
    position: str
    contract_type: str
    hire_date: str
    year: int
    month: int
    annual_gross_salary: float
    bruto_mes: float
    irpf_pct: float
    irpf_importe: float
    ss_employee_pct: float
    ss_employee_importe: float
    supplements_total: float
    advances_total: float
    neto: float
    ss_employer_pct: float
    ss_employer_importe: float
    coste_total_empresa: float
    iban: str


def build_gestoria_rows(
    entries: Sequence[tuple[Employee, str, PayrollRecord]],
) -> list[GestoriaRow]:
    """`entries`: (empleado, nombre_de_su_departamento, nómina ya generada)
    -- a diferencia de sepa_export.build_sepa_payments(), aquí no se omite
    ninguna fila (ni por falta de IBAN ni por importe cero): una gestoría
    necesita ver TODAS las nóminas del mes para cuadrar cuentas, incluida
    la de alguien sin cuenta bancaria todavía registrada."""
    return [
        GestoriaRow(
            dni_nie=employee.dni_nie or "",
            ss_number=employee.ss_number or "",
            full_name=employee.full_name,
            department_name=department_name,
            position=employee.position,
            contract_type=employee.contract_type,
            hire_date=employee.hire_date.isoformat(),
            year=record.payroll.year,
            month=record.payroll.month,
            annual_gross_salary=record.annual_gross_salary_snapshot,
            bruto_mes=record.payroll.bruto_mes,
            irpf_pct=record.payroll.irpf_pct,
            irpf_importe=record.payroll.irpf_importe,
            ss_employee_pct=record.payroll.ss_employee_pct,
            ss_employee_importe=record.payroll.ss_employee_importe,
            supplements_total=record.payroll.supplements_total,
            advances_total=record.payroll.advances_total,
            neto=record.payroll.neto,
            ss_employer_pct=record.payroll.ss_employer_pct,
            ss_employer_importe=record.payroll.ss_employer_importe,
            coste_total_empresa=record.payroll.coste_total_empresa,
            iban=employee.bank_account,
        )
        for employee, department_name, record in entries
    ]


def _format_number(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def write_gestoria_csv(rows: Sequence[GestoriaRow], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(_CSV_HEADER)
        for row in rows:
            writer.writerow(
                [
                    row.dni_nie,
                    row.ss_number,
                    row.full_name,
                    row.department_name,
                    row.position,
                    row.contract_type,
                    row.hire_date,
                    row.year,
                    row.month,
                    _format_number(row.annual_gross_salary),
                    _format_number(row.bruto_mes),
                    _format_number(row.irpf_pct),
                    _format_number(row.irpf_importe),
                    _format_number(row.ss_employee_pct),
                    _format_number(row.ss_employee_importe),
                    _format_number(row.supplements_total),
                    _format_number(row.advances_total),
                    _format_number(row.neto),
                    _format_number(row.ss_employer_pct),
                    _format_number(row.ss_employer_importe),
                    _format_number(row.coste_total_empresa),
                    row.iban,
                ]
            )
