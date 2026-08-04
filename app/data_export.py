"""Exportación completa de los datos de un empleado en un único ZIP, para
cumplir el derecho de acceso/portabilidad RGPD (art. 15 y 20 LOPDGDD): un
empleado -- o quien gestione RRHH en su nombre -- puede pedir "todo lo que
tenéis sobre mí" y esto genera exactamente eso: un datos.json con todos los
campos estructurados de todas las tablas que lo referencian, más una carpeta
documentos/ con los ficheros reales adjuntos a su ficha (y su foto, si tiene).

Deliberadamente NO incluye el registro de auditoría (AuditLogRepository):
son metadatos de uso del sistema -- quién hizo login, quién editó qué --, no
"datos sobre" el empleado en el sentido del art. 15; es una categoría de
datos distinta, sin vínculo estructurado por empleado (ver AuditLogEntry:
solo guarda username, no employee_id)."""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from app.repository import Repositories


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"no se puede serializar a JSON: {type(value)!r}")


def export_employee_data(repos: Repositories, employee_id: int) -> bytes:
    """Devuelve los bytes del ZIP completo (el llamante decide dónde
    guardarlo, igual que EmployeeDocumentRepository.get().content -- este
    módulo no asume rutas de archivo)."""
    employee = repos.employees.get(employee_id)
    department = repos.departments.get(employee.department_id)
    manager = repos.employees.get(employee.manager_id) if employee.manager_id is not None else None
    headed_department = (
        repos.departments.get(employee.head_of_department_id)
        if employee.head_of_department_id is not None
        else None
    )
    professional_category = (
        repos.professional_categories.get(employee.professional_category_id)
        if employee.professional_category_id is not None
        else None
    )
    collective_agreement = (
        repos.collective_agreements.get(professional_category.collective_agreement_id)
        if professional_category is not None
        else None
    )

    employee_dict = asdict(employee)
    has_photo = employee_dict.pop("photo") is not None
    employee_dict["departamento"] = department.name
    employee_dict["supervisor_directo"] = manager.full_name if manager is not None else None
    employee_dict["encargado_de_departamento"] = (
        headed_department.name if headed_department is not None else None
    )
    employee_dict["categoria_profesional"] = (
        professional_category.name if professional_category is not None else None
    )
    employee_dict["convenio_colectivo"] = (
        collective_agreement.name if collective_agreement is not None else None
    )
    employee_dict["foto_incluida"] = has_photo

    documents = repos.documents.list_for_employee(employee_id)
    full_documents = [repos.documents.get(doc.id) for doc in documents if doc.id is not None]

    data: dict[str, Any] = {
        "empleado": employee_dict,
        "historial_puesto_salario": [
            asdict(entry) for entry in repos.history.list_for_employee(employee_id)
        ],
        "ausencias": [
            asdict(entry) for entry in repos.absences.list_all_for_employee(employee_id)
        ],
        "asignaciones_turno_diarias": [
            asdict(entry)
            for entry in repos.daily_assignments.list_all_for_employee(employee_id)
        ],
        "nominas_generadas": [
            asdict(record) for record in repos.payroll_records.list_for_employee(employee_id)
        ],
        "complementos_nomina": [
            asdict(entry)
            for entry in repos.payroll_supplements.list_all_for_employee(employee_id)
        ],
        "finiquitos": [
            asdict(entry)
            for entry in repos.severance_settlements.list_for_employee(employee_id)
        ],
        "accidentes_trabajo": [
            asdict(entry) for entry in repos.work_accidents.list_for_employee(employee_id)
        ],
        "episodios_it": [
            asdict(entry) for entry in repos.it_episodes.list_for_employee(employee_id)
        ],
        "formacion_certificaciones": [
            asdict(entry) for entry in repos.trainings.list_for_employee(employee_id)
        ],
        "checklist_incorporacion": [
            asdict(status) for status in repos.onboarding_tasks.checklist_for_employee(employee_id)
        ],
        "fichajes": [
            asdict(entry) for entry in repos.time_entries.list_all_for_employee(employee_id)
        ],
        "documentos": [
            {
                "id": doc.id,
                "nombre": doc.filename,
                "categoria": doc.category,
                "subido_el": doc.uploaded_at.isoformat(),
                "fichero": f"documentos/{doc.id}_{doc.filename}",
            }
            for doc in documents
        ],
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "datos.json", json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)
        )
        for doc in full_documents:
            archive.writestr(f"documentos/{doc.id}_{doc.filename}", doc.content)
        if has_photo and employee.photo is not None:
            archive.writestr("documentos/foto.jpg", employee.photo)
    return buffer.getvalue()
