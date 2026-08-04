"""Generación de texto base de documentos (oferta, contrato, carta de baja...)
a partir de una plantilla reutilizable con marcadores y los datos reales de
un empleado -- funciones puras, sin UI ni base de datos, misma filosofía de
aislamiento que payroll.py/vacation.py/severance.py/alerts.py.

Un marcador se escribe como {nombre_del_campo} dentro del texto de la
plantilla. Deliberadamente NO se usa str.format(): un marcador desconocido
(typo) se deja tal cual en el resultado en vez de lanzar una excepción, y
una llave suelta que no forme parte de un marcador reconocido no rompe el
resto del texto -- el objetivo es que un fallo de sustitución se vea de un
vistazo en la vista previa, no que interrumpa la generación con un error
críptico para alguien de RRHH sin conocimientos técnicos.
"""

from __future__ import annotations

import re
from datetime import date

from app.models import Employee

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

PLACEHOLDER_DESCRIPTIONS: dict[str, str] = {
    "nombre": "Nombre de pila",
    "apellidos": "Apellidos",
    "nombre_completo": "Nombre y apellidos",
    "dni_nie": "DNI o NIE",
    "puesto": "Puesto",
    "departamento": "Departamento",
    "salario": "Salario bruto anual (formateado, ej. 24.000,00 €)",
    "fecha_ingreso": "Fecha de ingreso (DD/MM/AAAA)",
    "tipo_contrato": "Tipo de contrato",
    "email": "Correo electrónico",
    "telefono": "Teléfono",
    "iban": "Cuenta bancaria (IBAN)",
    "fecha_hoy": "Fecha de hoy (DD/MM/AAAA)",
    "fecha_baja": "Fecha de baja (vacío si el empleado sigue activo)",
    "motivo_baja": "Motivo de baja (vacío si el empleado sigue activo)",
}


def _format_currency(value: float) -> str:
    # Mismo formato español (punto de millar, coma decimal) que
    # employee_page._format_currency -- ver el comentario allí sobre por
    # qué se duplica en vez de importarse.
    us_formatted = f"{value:,.2f}"
    integer_part, decimal_part = us_formatted.split(".")
    integer_part = integer_part.replace(",", ".")
    return f"{integer_part},{decimal_part} €"


def build_placeholder_values(employee: Employee, department_name: str) -> dict[str, str]:
    return {
        "nombre": employee.first_name,
        "apellidos": employee.last_name,
        "nombre_completo": employee.full_name,
        "dni_nie": employee.dni_nie or "",
        "puesto": employee.position,
        "departamento": department_name,
        "salario": _format_currency(employee.salary),
        "fecha_ingreso": employee.hire_date.strftime("%d/%m/%Y"),
        "tipo_contrato": employee.contract_type,
        "email": employee.email,
        "telefono": employee.phone,
        "iban": employee.bank_account,
        "fecha_hoy": date.today().strftime("%d/%m/%Y"),
        "fecha_baja": (
            employee.termination_date.strftime("%d/%m/%Y") if employee.termination_date else ""
        ),
        "motivo_baja": employee.termination_reason or "",
    }


def render_document_template(body: str, values: dict[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return values[key] if key in values else match.group(0)

    return _PLACEHOLDER_RE.sub(_replace, body)
