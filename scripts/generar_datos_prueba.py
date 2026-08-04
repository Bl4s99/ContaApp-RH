from __future__ import annotations

import csv
import random
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import DEFAULT_DB_PATH, get_connection, init_db  # noqa: E402
from app.repository import (  # noqa: E402
    EmployeeInput,
    Repositories,
    RepositoryError,
    ShiftInput,
)
from app import validation  # noqa: E402

RANDOM_SEED = 42
EMPLOYEE_COUNT = 50
CSV_PATH = Path(__file__).resolve().parent.parent / "empleados_ficticios.csv"
EMAIL_DOMAIN = "empresa-ficticia.example"

FIRST_NAMES = [
    "Ana", "Carlos", "Maria", "Javier", "Laura", "David", "Elena", "Pablo",
    "Marta", "Sergio", "Cristina", "Alejandro", "Sara", "Miguel", "Lucia",
    "Daniel", "Paula", "Adrian", "Beatriz", "Ruben", "Isabel", "Alvaro",
    "Nuria", "Raul", "Silvia", "Ivan", "Patricia", "Oscar", "Rocio", "Diego",
    "Carmen", "Fernando", "Irene", "Jorge", "Natalia", "Manuel", "Andrea",
    "Antonio", "Sandra", "Francisco", "Eva", "Jose", "Teresa", "Luis",
    "Victoria", "Juan", "Marina", "Pedro", "Alicia", "Ricardo", "Monica",
]

LAST_NAMES = [
    "Garcia", "Rodriguez", "Gonzalez", "Fernandez", "Lopez", "Martinez",
    "Sanchez", "Perez", "Gomez", "Martin", "Jimenez", "Ruiz", "Hernandez",
    "Diaz", "Moreno", "Alvarez", "Munoz", "Romero", "Alonso", "Gutierrez",
    "Navarro", "Torres", "Dominguez", "Vazquez", "Ramos", "Gil", "Ramirez",
    "Serrano", "Blanco", "Suarez", "Molina", "Morales", "Ortega", "Delgado",
    "Castro", "Ortiz", "Rubio", "Marin", "Sanz", "Iglesias",
]


@dataclass(frozen=True)
class ShiftPlan:
    name: str
    start_time: str
    end_time: str
    days_of_week: frozenset[int]


@dataclass(frozen=True)
class DepartmentPlan:
    name: str
    positions: list[tuple[str, int, int]]  # (puesto, salario_min, salario_max)
    shifts: list[ShiftPlan]


WEEKDAYS_LV = frozenset({1, 2, 3, 4, 5})
WEEKDAYS_SAB = frozenset({6})

DEPARTMENT_PLANS = [
    DepartmentPlan(
        name="Ventas",
        positions=[
            ("Vendedor/a", 18000, 22000),
            ("Comercial", 20000, 28000),
            ("Jefe/a de Ventas", 32000, 40000),
        ],
        shifts=[
            ShiftPlan("Turno mañana", "09:00", "14:00", WEEKDAYS_LV),
            ShiftPlan("Turno tarde", "16:00", "20:00", WEEKDAYS_LV),
            ShiftPlan("Turno sábado", "10:00", "14:00", WEEKDAYS_SAB),
        ],
    ),
    DepartmentPlan(
        name="Almacén",
        positions=[
            ("Mozo/a de Almacén", 17000, 21000),
            ("Carretillero/a", 19000, 23000),
            ("Encargado/a de Almacén", 24000, 30000),
        ],
        shifts=[
            ShiftPlan("Turno mañana", "06:00", "14:00", WEEKDAYS_LV),
            ShiftPlan("Turno tarde", "14:00", "22:00", WEEKDAYS_LV),
        ],
    ),
    DepartmentPlan(
        name="Atención al Cliente",
        positions=[
            ("Agente de Atención al Cliente", 18000, 22000),
            ("Supervisor/a de Atención al Cliente", 26000, 32000),
        ],
        shifts=[
            ShiftPlan("Turno mañana", "08:00", "16:00", WEEKDAYS_LV),
            ShiftPlan("Turno tarde", "14:00", "22:00", WEEKDAYS_LV),
        ],
    ),
    DepartmentPlan(
        name="Administración",
        positions=[
            ("Auxiliar Administrativo/a", 17000, 20000),
            ("Administrativo/a", 19000, 24000),
            ("Contable", 24000, 32000),
        ],
        shifts=[
            ShiftPlan("Turno único", "09:00", "18:00", WEEKDAYS_LV),
        ],
    ),
    DepartmentPlan(
        name="Recursos Humanos",
        positions=[
            ("Técnico/a de RRHH", 22000, 28000),
            ("Reclutador/a", 22000, 28000),
            ("Responsable de RRHH", 34000, 42000),
        ],
        shifts=[
            ShiftPlan("Turno único", "09:00", "18:00", WEEKDAYS_LV),
        ],
    ),
]

DEFAULT_DAY_TYPES = [
    ("Vacaciones", "#2ecc71"),
    ("Enfermedad", "#e67e22"),
    ("Festivo", "#e74c3c"),
    ("Permiso o licencia", "#9b59b6"),
    ("Ausencia injustificada", "#c0392b"),
]


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def random_hire_date(rng: random.Random) -> date:
    earliest = date.today() - timedelta(days=365 * 6)
    span_days = (date.today() - earliest).days
    return earliest + timedelta(days=rng.randint(0, span_days))


def random_phone(rng: random.Random) -> str:
    number = rng.choice(["6", "7"]) + "".join(str(rng.randint(0, 9)) for _ in range(8))
    return f"+34 {number[0:3]} {number[3:6]} {number[6:9]}"


@dataclass(frozen=True)
class FakeEmployee:
    first_name: str
    last_name: str
    email: str
    phone: str
    position: str
    department: str
    shift_name: str
    salary: float
    hire_date: str
    active: bool


def generate_employees(count: int, rng: random.Random) -> list[FakeEmployee]:
    employees: list[FakeEmployee] = []
    used_emails: set[str] = set()
    used_name_pairs: set[tuple[str, str]] = set()

    for _ in range(count):
        dept_plan = rng.choice(DEPARTMENT_PLANS)
        position, salary_min, salary_max = rng.choice(dept_plan.positions)

        while True:
            first_name = rng.choice(FIRST_NAMES)
            last_name = rng.choice(LAST_NAMES)
            if (first_name, last_name) not in used_name_pairs:
                used_name_pairs.add((first_name, last_name))
                break

        email_local = f"{strip_accents(first_name)}.{strip_accents(last_name)}".lower()
        email = f"{email_local}@{EMAIL_DOMAIN}"
        suffix = 2
        while email in used_emails:
            email = f"{email_local}{suffix}@{EMAIL_DOMAIN}"
            suffix += 1
        used_emails.add(email)

        # ~15% of employees have no shift assigned, to exercise that case too.
        shift_name = "" if rng.random() < 0.15 else rng.choice(dept_plan.shifts).name
        active = rng.random() < 0.9

        employees.append(
            FakeEmployee(
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=random_phone(rng),
                position=position,
                department=dept_plan.name,
                shift_name=shift_name,
                salary=float(rng.randint(salary_min, salary_max)),
                hire_date=random_hire_date(rng).isoformat(),
                active=active,
            )
        )

    return employees


def write_csv(employees: list[FakeEmployee], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "nombre", "apellido", "email", "telefono", "puesto",
                "departamento", "turno", "salario", "fecha_ingreso", "activo",
            ]
        )
        for emp in employees:
            writer.writerow(
                [
                    emp.first_name,
                    emp.last_name,
                    emp.email,
                    emp.phone,
                    emp.position,
                    emp.department,
                    emp.shift_name,
                    f"{emp.salary:.2f}",
                    emp.hire_date,
                    "si" if emp.active else "no",
                ]
            )


def load_into_database(csv_path: Path) -> None:
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        init_db(conn)
        repos = Repositories.create(conn)

        department_ids: dict[str, int] = {
            d.name: d.id for d in repos.departments.list_all() if d.id is not None
        }
        for plan in DEPARTMENT_PLANS:
            if plan.name not in department_ids:
                dept = repos.departments.create(plan.name)
                assert dept.id is not None
                department_ids[plan.name] = dept.id

        if not repos.day_types.list_all():
            for name, color in DEFAULT_DAY_TYPES:
                repos.day_types.create(name, color)

        shift_ids: dict[tuple[str, str], int] = {}
        for plan in DEPARTMENT_PLANS:
            dept_id = department_ids[plan.name]
            existing = {s.name: s.id for s in repos.shifts.list_for_department(dept_id)}
            for shift_plan in plan.shifts:
                if shift_plan.name in existing:
                    shift_id = existing[shift_plan.name]
                else:
                    shift = repos.shifts.create(
                        ShiftInput(
                            department_id=dept_id,
                            name=shift_plan.name,
                            start_time=shift_plan.start_time,
                            end_time=shift_plan.end_time,
                            days_of_week=shift_plan.days_of_week,
                        )
                    )
                    shift_id = shift.id
                assert shift_id is not None
                shift_ids[(plan.name, shift_plan.name)] = shift_id

        created = 0
        skipped: list[str] = []
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                department_id = department_ids.get(row["departamento"])
                if department_id is None:
                    skipped.append(f"{row['email']}: departamento desconocido")
                    continue
                shift_id = shift_ids.get((row["departamento"], row["turno"])) if row["turno"] else None
                data = EmployeeInput(
                    first_name=row["nombre"],
                    last_name=row["apellido"],
                    email=row["email"],
                    phone=row["telefono"],
                    position=row["puesto"],
                    department_id=department_id,
                    shift_id=shift_id,
                    salary=float(row["salario"]),
                    hire_date=row["fecha_ingreso"],
                    active=row["activo"].strip().lower() in ("si", "sí", "true", "1"),
                )
                try:
                    repos.employees.create(data)
                    created += 1
                except (validation.ValidationError, RepositoryError) as exc:
                    skipped.append(f"{row['email']}: {exc}")

        print(f"Departamentos disponibles: {len(department_ids)}")
        print(f"Turnos creados/existentes: {len(shift_ids)}")
        print(f"Empleados cargados: {created}")
        if skipped:
            print(f"Empleados omitidos ({len(skipped)}):")
            for line in skipped:
                print(f"  - {line}")
    finally:
        conn.close()


def main() -> None:
    rng = random.Random(RANDOM_SEED)
    employees = generate_employees(EMPLOYEE_COUNT, rng)
    write_csv(employees, CSV_PATH)
    print(f"CSV generado en: {CSV_PATH}")
    load_into_database(CSV_PATH)
    print(f"Base de datos actualizada en: {DEFAULT_DB_PATH}")


if __name__ == "__main__":
    main()
