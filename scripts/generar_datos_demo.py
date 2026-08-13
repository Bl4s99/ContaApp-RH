"""Genera datos ficticios ricos para la demo interactiva de ContaApp RH.

A diferencia de generar_datos_prueba.py (que solo siembra departamentos,
turnos y empleados basicos), este script cubre TODAS las areas de la app
-- ausencias, nominas, formacion, convenios, autoservicio, desempeno,
equipo asignado, organigrama, documentos, candidatos y fichajes -- para
que las capturas de la demo reflejen la version actual del programa, no
una version muy antigua.

Uso:
    py scripts/generar_datos_demo.py --db-path C:\\ruta\\temporal\\demo.db

Nunca escribe en la base de datos real: --db-path es obligatorio (sin
valor por defecto) y el script se niega a arrancar si el nombre de
fichero resuelto es empleados.db.
"""
from __future__ import annotations

import argparse
import calendar
import random
import sys
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_connection, init_db  # noqa: E402
from app.repository import (  # noqa: E402
    CandidateInput,
    EmployeeInput,
    ProfessionalCategoryInput,
    Repositories,
    ShiftInput,
    gather_alerts,
)

RANDOM_SEED = 42

HERO_EMAIL = "laura.jimenez@empresa-ficticia.example"
HERO_FIRST_NAME = "Laura"
HERO_LAST_NAME = "Jimenez"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "ContaAppDemo2026!"

# IBAN de ejemplo citado literalmente en el propio mensaje de error del
# validador (app/validation.py) -- formato y digito de control validos.
EXAMPLE_IBAN = "ES91 2100 0418 4502 0005 1332"

FIRST_NAMES = [
    "Ana", "Carlos", "Maria", "Javier", "Elena", "Pablo",
    "Marta", "Sergio", "Cristina", "Alejandro", "Sara", "Miguel",
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
    head_position: str
    shifts: list[ShiftPlan]


WEEKDAYS_LV = frozenset({1, 2, 3, 4, 5})
WEEKDAYS_SAB = frozenset({6})

DEPARTMENT_PLANS = [
    DepartmentPlan(
        name="Ventas",
        positions=[("Vendedor/a", 18000, 22000), ("Comercial", 20000, 28000)],
        head_position="Jefe/a de Ventas",
        shifts=[
            ShiftPlan("Turno mañana", "09:00", "14:00", WEEKDAYS_LV),
            ShiftPlan("Turno tarde", "16:00", "20:00", WEEKDAYS_LV),
            ShiftPlan("Turno sábado", "10:00", "14:00", WEEKDAYS_SAB),
        ],
    ),
    DepartmentPlan(
        name="Almacén",
        positions=[("Mozo/a de Almacén", 17000, 21000), ("Carretillero/a", 19000, 23000)],
        head_position="Encargado/a de Almacén",
        shifts=[
            ShiftPlan("Turno mañana", "06:00", "14:00", WEEKDAYS_LV),
            ShiftPlan("Turno tarde", "14:00", "22:00", WEEKDAYS_LV),
        ],
    ),
    DepartmentPlan(
        name="Atención al Cliente",
        positions=[("Agente de Atención al Cliente", 18000, 22000)],
        head_position="Supervisor/a de Atención al Cliente",
        shifts=[
            ShiftPlan("Turno mañana", "08:00", "16:00", WEEKDAYS_LV),
            ShiftPlan("Turno tarde", "14:00", "22:00", WEEKDAYS_LV),
        ],
    ),
    DepartmentPlan(
        name="Administración",
        positions=[("Auxiliar Administrativo/a", 17000, 20000), ("Administrativo/a", 19000, 24000)],
        head_position="Contable",
        shifts=[ShiftPlan("Turno único", "09:00", "18:00", WEEKDAYS_LV)],
    ),
    DepartmentPlan(
        name="Recursos Humanos",
        positions=[("Técnico/a de RRHH", 22000, 28000), ("Reclutador/a", 22000, 28000)],
        head_position="Responsable de RRHH",
        shifts=[ShiftPlan("Turno único", "09:00", "18:00", WEEKDAYS_LV)],
    ),
]

DAY_TYPES = [
    ("Vacaciones", "#2ecc71", True),
    ("Enfermedad", "#e67e22", False),
    ("Festivo", "#e74c3c", False),
    ("Permiso o licencia", "#9b59b6", False),
    ("Ausencia injustificada", "#c0392b", False),
]

ONBOARDING_TASKS = [
    "Contrato firmado",
    "Alta en Seguridad Social",
    "Equipo entregado",
    "Accesos creados",
]

CATEGORY_PLANS = [
    ("Categoría I - Base", 17000.0),
    ("Categoría II - Especialista", 22000.0),
    ("Categoría III - Responsable", 30000.0),
]

CANDIDATE_PHASES = ["Recibido", "Entrevista", "Oferta", "Contratado", "Descartado"]

DNI_CONTROL_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def make_email(first_name: str, last_name: str, used: set[str]) -> str:
    local = f"{strip_accents(first_name)}.{strip_accents(last_name)}".lower()
    email = f"{local}@empresa-ficticia.example"
    suffix = 2
    while email in used:
        email = f"{local}{suffix}@empresa-ficticia.example"
        suffix += 1
    used.add(email)
    return email


def random_phone(rng: random.Random) -> str:
    number = rng.choice(["6", "7"]) + "".join(str(rng.randint(0, 9)) for _ in range(8))
    return f"+34 {number[0:3]} {number[3:6]} {number[6:9]}"


def fake_dni(number: int) -> str:
    letter = DNI_CONTROL_LETTERS[number % 23]
    return f"{number:08d}{letter}"


def fake_ss_number(rng: random.Random) -> str:
    return "28" + "".join(str(rng.randint(0, 9)) for _ in range(10))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path, help="Ruta a una BD SQLite nueva (nunca empleados.db)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = args.db_path.resolve()
    if db_path.name == "empleados.db":
        raise SystemExit("Nunca apuntar a empleados.db -- usa una ruta temporal para la demo.")
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    rng = random.Random(RANDOM_SEED)
    today = date.today()
    year, month = today.year, today.month
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)

    conn = get_connection(db_path)
    assert conn.__class__.__module__.startswith("sqlite3"), (
        "la conexion resultante no es sqlite3 -- revisa si existe un "
        "db_config.json que la este redirigiendo a Postgres"
    )
    try:
        init_db(conn)
        repos = Repositories.create(conn)
        used_emails: set[str] = set()
        used_names: set[tuple[str, str]] = set()

        def random_name() -> tuple[str, str]:
            while True:
                pair = (rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES))
                if pair not in used_names:
                    used_names.add(pair)
                    return pair

        # ---------------- Fase A: fundacion ----------------
        for name, color, is_vacation in DAY_TYPES:
            repos.day_types.create(name, color, is_vacation)
        vacation_day_type = next(dt for dt in repos.day_types.list_all() if dt.is_vacation)
        assert vacation_day_type.id is not None

        for name in ONBOARDING_TASKS:
            repos.onboarding_tasks.create(name)

        department_ids: dict[str, int] = {}
        shift_ids: dict[tuple[str, str], int] = {}
        for plan in DEPARTMENT_PLANS:
            dept = repos.departments.create(plan.name)
            assert dept.id is not None
            department_ids[plan.name] = dept.id
            for shift_plan in plan.shifts:
                shift = repos.shifts.create(
                    ShiftInput(
                        department_id=dept.id,
                        name=shift_plan.name,
                        start_time=shift_plan.start_time,
                        end_time=shift_plan.end_time,
                        days_of_week=shift_plan.days_of_week,
                    )
                )
                assert shift.id is not None
                shift_ids[(plan.name, shift_plan.name)] = shift.id

        agreement = repos.collective_agreements.create("Convenio Colectivo Comercio y Oficinas 2026")
        assert agreement.id is not None
        category_ids: dict[str, int] = {}
        for name, min_salary in CATEGORY_PLANS:
            cat = repos.professional_categories.create(
                ProfessionalCategoryInput(
                    collective_agreement_id=agreement.id, name=name, minimum_salary=min_salary,
                )
            )
            assert cat.id is not None
            category_ids[name] = cat.id

        repos.users.create(ADMIN_USERNAME, ADMIN_PASSWORD, role="admin")
        print(f"Usuario admin: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")

        # ---------------- Fase B: empleados y organigrama ----------------
        # inputs[email] guarda el ultimo EmployeeInput usado para poder
        # reconstruir uno "parcheado" con dataclasses.replace() cuando haga
        # falta actualizar manager_id/head_of_department_id despues de crear
        # a todo el mundo (update() exige el EmployeeInput completo, no un
        # parche).
        employee_ids: dict[str, int] = {}
        inputs: dict[str, EmployeeInput] = {}

        def create_employee(data: EmployeeInput) -> int:
            emp = repos.employees.create(data)
            assert emp.id is not None
            employee_ids[data.email] = emp.id
            inputs[data.email] = data
            return emp.id

        def set_head_of_department(email: str, head_of_department_id: int) -> None:
            new_input = replace(inputs[email], head_of_department_id=head_of_department_id)
            repos.employees.update(employee_ids[email], new_input)
            inputs[email] = new_input

        def set_manager(email: str, manager_id: int) -> None:
            new_input = replace(inputs[email], manager_id=manager_id)
            repos.employees.update(employee_ids[email], new_input)
            inputs[email] = new_input

        # Un responsable por departamento (el puesto de mayor rango), creado
        # primero para poder asignarlos luego como manager_id/
        # head_of_department_id de sus equipos.
        head_email_by_dept: dict[str, str] = {}
        for plan in DEPARTMENT_PLANS:
            first_name, last_name = random_name()
            email = make_email(first_name, last_name, used_emails)
            head_id = create_employee(
                EmployeeInput(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=random_phone(rng),
                    position=plan.head_position,
                    department_id=department_ids[plan.name],
                    salary=float(rng.randint(32000, 42000)),
                    hire_date=(today - timedelta(days=365 * rng.randint(4, 7))).isoformat(),
                    dni_nie=fake_dni(rng.randint(10_000_000, 99_999_999)),
                    ss_number=fake_ss_number(rng),
                    birth_date=(
                        today - timedelta(days=365 * rng.randint(35, 55) + rng.randint(-182, 182))
                    ).isoformat(),
                    prl_training_date=(today - timedelta(days=rng.randint(200, 900))).isoformat(),
                    professional_category_id=category_ids["Categoría III - Responsable"],
                )
            )
            set_head_of_department(email, head_id)
            head_email_by_dept[plan.name] = email

        # El "protagonista" de la demo: ficha con todos los apartados
        # rellenos, la que se muestra en las capturas de ficha.
        hero_id = create_employee(
            EmployeeInput(
                first_name=HERO_FIRST_NAME,
                last_name=HERO_LAST_NAME,
                email=HERO_EMAIL,
                phone=random_phone(rng),
                position="Técnica de RRHH",
                department_id=department_ids["Recursos Humanos"],
                salary=25500.0,
                hire_date=(today - timedelta(days=365 * 2 + 40)).isoformat(),
                bank_account=EXAMPLE_IBAN,
                dependent_children=1,
                dni_nie=fake_dni(12345678),
                ss_number=fake_ss_number(rng),
                contract_type="Indefinido",
                birth_date=(today - timedelta(days=365 * 31 + 140)).isoformat(),
                next_medical_checkup_date=(today + timedelta(days=200)).isoformat(),
                prl_training_date=(today - timedelta(days=200)).isoformat(),
                professional_category_id=category_ids["Categoría II - Especialista"],
            )
        )
        set_manager(HERO_EMAIL, employee_ids[head_email_by_dept["Recursos Humanos"]])

        # Resto de la plantilla: empleados normales repartidos por
        # departamento, con variedad suficiente para disparar varias
        # categorias de alerta de forma natural.
        REGULAR_COUNT = 42
        temp_contract_targets = 3
        birthday_soon_targets = 3
        medical_soon_targets = 2
        below_min_salary_targets = 1
        created_regular = 0
        # email -> (shift_id, dias_de_la_semana) para sembrar despues la
        # asignacion diaria real (daily_shift_assignments) -- el shift_id en
        # EmployeeInput solo es el turno habitual por defecto, la rejilla del
        # calendario lee de una tabla aparte que si no se siembra sale vacia.
        employee_shift_plan: dict[str, tuple[int, frozenset[int]]] = {}

        for i in range(REGULAR_COUNT):
            plan = rng.choice(DEPARTMENT_PLANS)
            position, salary_min, salary_max = rng.choice(plan.positions)
            first_name, last_name = random_name()
            email = make_email(first_name, last_name, used_emails)
            chosen_shift = None if rng.random() < 0.15 else rng.choice(plan.shifts)
            shift_id = None
            if chosen_shift is not None:
                shift_id = shift_ids.get((plan.name, chosen_shift.name))
                if shift_id is not None:
                    employee_shift_plan[email] = (shift_id, chosen_shift.days_of_week)
            active = rng.random() < 0.92
            hire_date_obj = today - timedelta(days=rng.randint(30, 365 * 6))

            salary = float(rng.randint(salary_min, salary_max))
            category_id = None
            if rng.random() < 0.8:
                # La categoria sigue el nivel salarial del puesto (ningun
                # puesto normal llega a los 30000 de "Responsable", eso se
                # reserva a los encargados de departamento) -- asignarla al
                # azar sin relacion con el salario disparaba la alerta
                # "salario_minimo" en decenas de empleados por accidente.
                category_name = "Categoría II - Especialista" if salary_min >= 22000 else "Categoría I - Base"
                category_id = category_ids[category_name]
                if below_min_salary_targets > 0 and active:
                    # fuerza el disparo deterministico de la alerta
                    # "salario_minimo": categoria alta, salario bajo.
                    category_id = category_ids["Categoría III - Responsable"]
                    salary = 19000.0
                    below_min_salary_targets -= 1

            contract_type = "Indefinido"
            contract_end_date = ""
            if temp_contract_targets > 0 and active:
                contract_type = "Temporal"
                contract_end_date = (today + timedelta(days=rng.randint(5, 25))).isoformat()
                temp_contract_targets -= 1

            birth_date = ""
            if birthday_soon_targets > 0:
                birth_date = (today + timedelta(days=rng.randint(2, 20)) - timedelta(days=365 * rng.randint(25, 50))).isoformat()
                birthday_soon_targets -= 1
            elif rng.random() < 0.6:
                # Anos completos + un desplazamiento de dia-del-ano al azar:
                # restar solo multiplos exactos de 365 deja el mes/dia de
                # nacimiento pegado al de hoy (solo se separa por la deriva
                # de anos bisiestos), lo que disparaba la alerta de
                # cumpleanos en casi toda la plantilla por accidente.
                birth_date = (
                    today - timedelta(days=365 * rng.randint(22, 58) + rng.randint(-182, 182))
                ).isoformat()

            next_medical = ""
            if medical_soon_targets > 0 and active:
                next_medical = (today + timedelta(days=rng.randint(3, 25))).isoformat()
                medical_soon_targets -= 1
            elif rng.random() < 0.3:
                next_medical = (today + timedelta(days=rng.randint(60, 300))).isoformat()

            # Una minoria se deja sin formacion_prl a proposito -- es la
            # condicion que dispara esa categoria de alerta (activo + sin
            # fecha). La fecha, cuando existe, tiene que caer entre la
            # contratacion y hoy (no puede ser anterior al ingreso).
            days_since_hire = max((today - hire_date_obj).days, 0)
            prl_date = (
                "" if rng.random() < 0.12
                else (hire_date_obj + timedelta(days=rng.randint(0, days_since_hire))).isoformat()
            )

            manager_id = employee_ids[head_email_by_dept[plan.name]] if rng.random() < 0.7 else None

            create_employee(
                EmployeeInput(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=random_phone(rng),
                    position=position,
                    department_id=department_ids[plan.name],
                    shift_id=shift_id,
                    salary=salary,
                    hire_date=hire_date_obj.isoformat(),
                    dependent_children=rng.choice([0, 0, 0, 1, 2]),
                    dni_nie=fake_dni(rng.randint(10_000_000, 99_999_999)) if rng.random() < 0.6 else "",
                    ss_number=fake_ss_number(rng) if rng.random() < 0.6 else "",
                    contract_type=contract_type,
                    contract_end_date=contract_end_date,
                    birth_date=birth_date,
                    next_medical_checkup_date=next_medical,
                    prl_training_date=prl_date,
                    manager_id=manager_id,
                    professional_category_id=category_id,
                    active=active,
                )
            )
            created_regular += 1

        # Un empleado dado de baja hace ~4 anos menos unos dias, para que
        # dispare la alerta de revision de retencion RGPD (retention_years
        # por defecto = 4).
        retention_years = repos.app_settings.get_data_retention_years()
        term_first, term_last = random_name()
        term_email = make_email(term_first, term_last, used_emails)
        term_id = create_employee(
            EmployeeInput(
                first_name=term_first,
                last_name=term_last,
                email=term_email,
                phone=random_phone(rng),
                position="Auxiliar Administrativo/a",
                department_id=department_ids["Administración"],
                salary=18500.0,
                hire_date=(today - timedelta(days=365 * (retention_years + 3))).isoformat(),
                active=True,
            )
        )
        termination_date = today - timedelta(days=365 * retention_years - 15)
        repos.employees.terminate(term_id, termination_date.isoformat(), "Fin de contrato temporal")

        print(f"Empleados creados: {len(employee_ids)} (incluye {len(DEPARTMENT_PLANS)} responsables, 1 protagonista, 1 baja)")

        # ---------------- Fase C: resto de areas ----------------

        # Asignacion diaria real del mes actual -- shift_id en EmployeeInput
        # solo es el turno habitual, la rejilla del calendario se queda
        # vacia si no se rellena tambien daily_shift_assignments dia a dia.
        days_in_month = calendar.monthrange(year, month)[1]
        assignment_count = 0
        for email, (shift_id, days_of_week) in employee_shift_plan.items():
            for day_num in range(1, days_in_month + 1):
                day = date(year, month, day_num)
                if day.isoweekday() in days_of_week:
                    repos.daily_assignments.set_day(employee_ids[email], day, shift_id)
                    assignment_count += 1
        print(f"Asignaciones diarias (turnos) creadas: {assignment_count}")

        # Ausencias aprobadas (calendario + saldo de vacaciones) en una
        # muestra de empleados activos.
        active_emails = [e for e, inp in inputs.items() if inp.active and e != term_email]
        for email in rng.sample(active_emails, k=min(15, len(active_emails))):
            start = today - timedelta(days=rng.randint(10, 90))
            end = start + timedelta(days=rng.randint(1, 4))
            repos.absences.mark_range(employee_ids[email], vacation_day_type.id, start, end, note="Vacaciones")

        # Solicitudes de ausencia PENDIENTES -- ruta de escritura distinta a
        # las aprobadas de arriba; sin esto "Solicitudes de ausencia" sale
        # vacia.
        for email in rng.sample(active_emails, k=min(5, len(active_emails))):
            start = today + timedelta(days=rng.randint(3, 30))
            end = start + timedelta(days=rng.randint(1, 3))
            repos.absences.request_range(employee_ids[email], vacation_day_type.id, start, end, note="Vacaciones de verano")

        # Complementos de nomina + generacion, mes actual y anterior.
        supplement_types = ["plus", "bonos", "dietas", "anticipo"]
        payroll_pool = rng.sample(active_emails, k=min(20, len(active_emails)))
        for y, m in [(prev_year, prev_month), (year, month)]:
            for email in payroll_pool:
                if rng.random() < 0.6:
                    kind = rng.choice(supplement_types)
                    repos.payroll_supplements.create(
                        employee_ids[email], y, m, kind,
                        description=f"{kind.capitalize()} de {m:02d}/{y}",
                        amount=float(rng.randint(50, 400)),
                    )
                if rng.random() < 0.3:
                    repos.payroll_supplements.create(
                        employee_ids[email], y, m, "horas_extra",
                        description="Horas extra",
                        hours=float(rng.randint(2, 10)),
                        rate_per_hour=12.0,
                    )
            repos.payroll_records.generate_for_employees(
                [employee_ids[e] for e in payroll_pool], y, m,
            )

        # Formacion y certificaciones -- al menos una caducando pronto.
        repos.trainings.create(
            hero_id, "Curso de gestión de nóminas", today - timedelta(days=400), None,
        )
        cert_soon_email = rng.choice(active_emails)
        repos.trainings.create(
            employee_ids[cert_soon_email], "Certificado de prevención de riesgos laborales",
            today - timedelta(days=700), today + timedelta(days=rng.randint(5, 25)),
        )
        for email in rng.sample(active_emails, k=min(8, len(active_emails))):
            repos.trainings.create(
                employee_ids[email], "Curso de atención al cliente",
                today - timedelta(days=rng.randint(60, 800)), None,
            )

        # Desempeno: objetivos (con variedad de estado) y evaluaciones.
        obj1 = repos.objectives.create(hero_id, "Reducir el tiempo de alta de nuevos empleados", today + timedelta(days=45))
        repos.objectives.create(hero_id, "Completar el plan de formación PRL del trimestre", today - timedelta(days=10))
        assert obj1.id is not None
        repos.objectives.update_status(obj1.id, "cumplido")
        repos.performance_reviews.create(hero_id, today - timedelta(days=20), "Buen desempeño general, muy proactiva con la digitalización de expedientes.")
        for email in rng.sample(active_emails, k=min(6, len(active_emails))):
            obj = repos.objectives.create(employee_ids[email], "Objetivo trimestral de equipo", today + timedelta(days=rng.randint(-30, 60)))
            assert obj.id is not None
            if rng.random() < 0.5:
                repos.objectives.update_status(obj.id, rng.choice(["cumplido", "no_cumplido"]))

        # Equipo asignado (material fisico).
        repos.assigned_equipment.create(hero_id, "Portátil Dell Latitude", today - timedelta(days=700))
        repos.assigned_equipment.create(hero_id, "Llave de acceso a oficina", today - timedelta(days=700))
        for email in rng.sample(active_emails, k=min(10, len(active_emails))):
            repos.assigned_equipment.create(employee_ids[email], rng.choice(["Portátil", "Móvil de empresa", "Uniforme"]), today - timedelta(days=rng.randint(30, 900)))

        # Autoservicio: PIN valido en 3 empleados, incluido el protagonista.
        repos.employees.set_self_service_pin(hero_id, "482913")
        for email in rng.sample([e for e in active_emails if e != HERO_EMAIL], k=2):
            repos.employees.set_self_service_pin(employee_ids[email], str(rng.randint(1000, 999999)).zfill(6))

        # Documentos y plantillas.
        repos.document_templates.create(
            "Oferta de trabajo", "Estimado/a {nombre}, nos complace ofrecerle el puesto de {puesto} en nuestra empresa...",
        )
        repos.document_templates.create(
            "Carta de baja voluntaria", "Por la presente, {nombre} comunica su baja voluntaria con fecha {fecha}...",
        )
        repos.documents.upload(hero_id, "contrato_laura_jimenez.pdf", "Contrato", b"contenido de ejemplo para la demo")
        repos.documents.upload(hero_id, "dni_laura_jimenez.pdf", "DNI/NIE", b"contenido de ejemplo para la demo")

        # Checklist de incorporacion del protagonista: todas las tareas
        # completadas, para que la ficha se vea "en regla".
        for status in repos.onboarding_tasks.checklist_for_employee(hero_id):
            assert status.task.id is not None
            repos.onboarding_tasks.mark_complete(hero_id, status.task.id, today - timedelta(days=650))

        # Candidatos repartidos por las 5 fases.
        for i in range(10):
            first_name, last_name = random_name()
            plan = rng.choice(DEPARTMENT_PLANS)
            repos.candidates.create(
                CandidateInput(
                    first_name=first_name,
                    last_name=last_name,
                    email=f"{strip_accents(first_name).lower()}.{strip_accents(last_name).lower()}.candidato@example.com",
                    phone=random_phone(rng),
                    position=rng.choice(plan.positions)[0],
                    department_id=department_ids[plan.name],
                    phase=CANDIDATE_PHASES[i % len(CANDIDATE_PHASES)],
                    notes="Candidato ficticio generado para la demo.",
                )
            )

        # Fichajes del mes actual -- pares estrictos entrada/salida en
        # orden cronologico por empleado. El protagonista siempre incluido,
        # para que la captura de la demo pueda seleccionarlo por nombre y
        # no dependa de a quien le tocara al azar.
        clock_pool = set(rng.sample(active_emails, k=min(10, len(active_emails))))
        clock_pool.add(HERO_EMAIL)
        work_days = [today - timedelta(days=d) for d in range(1, 15) if (today - timedelta(days=d)).weekday() < 5]
        for email in clock_pool:
            for day in sorted(work_days):
                start_hour = rng.choice([8, 9])
                repos.time_entries.create_manual(
                    employee_ids[email], "entrada", datetime.combine(day, dtime(start_hour, rng.randint(0, 15))),
                )
                repos.time_entries.create_manual(
                    employee_ids[email], "salida", datetime.combine(day, dtime(start_hour + 8, rng.randint(0, 30))),
                )

        # ---------------- Fase D: autoverificacion de alertas ----------------
        alerts = gather_alerts(repos, None, today)
        counts: dict[str, int] = {}
        for alert in alerts:
            counts[alert.category] = counts.get(alert.category, 0) + 1
        print("\nRecuento de alertas por categoria:")
        expected_categories = [
            "contrato", "cumpleanos", "revision_medica", "formacion_prl",
            "certificacion", "salario_minimo", "retencion_rgpd",
        ]
        any_missing = False
        for category_key in expected_categories:
            n = counts.get(category_key, 0)
            flag = "" if n > 0 else "  <-- VACIA"
            if n == 0:
                any_missing = True
            print(f"  {category_key}: {n}{flag}")
        if any_missing:
            print("\nAVISO: alguna categoria de alerta salio vacia -- revisar antes de capturar.")
        else:
            print("\nTodas las categorias de alerta tienen al menos un caso.")

        print(f"\nBase de datos generada en: {db_path}")
        print(f"Empleado protagonista: {HERO_FIRST_NAME} {HERO_LAST_NAME} <{HERO_EMAIL}>")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
