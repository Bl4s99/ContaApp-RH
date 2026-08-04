from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.payroll import MonthlyPayroll


@dataclass(frozen=True, slots=True)
class Department:
    id: int | None
    name: str


@dataclass(frozen=True, slots=True)
class CollectiveAgreement:
    id: int | None
    name: str


@dataclass(frozen=True, slots=True)
class ProfessionalCategory:
    id: int | None
    collective_agreement_id: int
    name: str
    minimum_salary: float


@dataclass(frozen=True, slots=True)
class Employee:
    id: int | None
    first_name: str
    last_name: str
    email: str
    phone: str
    position: str
    department_id: int
    shift_id: int | None
    salary: float
    hire_date: date
    active: bool
    bank_account: str
    photo: bytes | None
    dependent_children: int
    dni_nie: str | None
    ss_number: str | None
    contract_type: str
    contract_end_date: date | None
    birth_date: date | None
    next_medical_checkup_date: date | None
    termination_date: date | None
    termination_reason: str | None
    anonymized: bool
    prl_training_date: date | None
    manager_id: int | None
    head_of_department_id: int | None
    professional_category_id: int | None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


@dataclass(frozen=True, slots=True)
class Shift:
    id: int | None
    department_id: int
    name: str
    start_time: str
    end_time: str
    days_of_week: frozenset[int]
    start_time_2: str | None = None
    end_time_2: str | None = None

    @property
    def schedule_display(self) -> str:
        if self.start_time_2 is not None and self.end_time_2 is not None:
            return f"{self.start_time}-{self.end_time} y {self.start_time_2}-{self.end_time_2}"
        return f"{self.start_time}-{self.end_time}"


@dataclass(frozen=True, slots=True)
class DayType:
    id: int | None
    name: str
    color: str
    is_vacation: bool = False


@dataclass(frozen=True, slots=True)
class DepartmentClosure:
    id: int | None
    department_id: int
    closure_date: date
    day_type_id: int
    note: str


@dataclass(frozen=True, slots=True)
class HolidayTemplate:
    id: int | None
    name: str
    created_at: date


@dataclass(frozen=True, slots=True)
class HolidayTemplateDate:
    id: int | None
    template_id: int
    holiday_date: date
    label: str


@dataclass(frozen=True, slots=True)
class HolidayApplyResult:
    departments_applied: int
    closures_created: int
    closures_skipped: int


@dataclass(frozen=True, slots=True)
class DocumentTemplate:
    id: int | None
    name: str
    body: str
    created_at: date


@dataclass(frozen=True, slots=True)
class OnboardingTask:
    id: int | None
    name: str


@dataclass(frozen=True, slots=True)
class OnboardingChecklistStatus:
    """Una tarea del catálogo junto con si un empleado concreto la tiene
    hecha -- completed_at es None si todavía está pendiente."""

    task: OnboardingTask
    completed_at: date | None

    @property
    def is_complete(self) -> bool:
        return self.completed_at is not None


@dataclass(frozen=True, slots=True)
class Candidate:
    id: int | None
    first_name: str
    last_name: str
    email: str
    phone: str
    position: str
    department_id: int
    phase: str
    notes: str
    created_at: date

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


@dataclass(frozen=True, slots=True)
class EmployeeAbsence:
    id: int | None
    employee_id: int
    absence_date: date
    day_type_id: int
    note: str
    status: str = "aprobada"  # "pendiente" | "aprobada" | "rechazada"


@dataclass(frozen=True, slots=True)
class PayrollSettings:
    ss_employee_pct: float
    ss_employer_pct: float


@dataclass(frozen=True, slots=True)
class DailyShiftAssignment:
    id: int | None
    employee_id: int
    assignment_date: date
    shift_id: int


@dataclass(frozen=True, slots=True)
class User:
    id: int | None
    username: str
    created_at: date
    role: str
    department_id: int | None
    email_provider: str | None
    email_address: str | None
    last_digest_sent_at: datetime | None


@dataclass(frozen=True, slots=True)
class EmailConnection:
    """Credenciales de conexión de correo de un usuario -- deliberadamente
    aparte de User, igual que password_hash/salt nunca viajan en ese
    dataclass: app_password es un secreto reversible (hace falta en claro
    para autenticar contra el SMTP del proveedor), así que solo se lee
    cuando de verdad hace falta usarlo (enviar el resumen, o mostrarlo en
    Mi cuenta...), nunca como parte del "usuario actual" de uso general."""

    provider: str  # "gmail" | "outlook"
    address: str
    app_password: str


@dataclass(frozen=True, slots=True)
class TimeClockEntry:
    id: int | None
    employee_id: int
    entry_type: str  # "entrada" | "salida"
    entry_timestamp: datetime
    note: str


@dataclass(frozen=True, slots=True)
class EmployeeDocument:
    id: int | None
    employee_id: int
    filename: str
    category: str
    content: bytes
    size_bytes: int
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class EmployeeDocumentSummary:
    """Igual que EmployeeDocument pero sin `content` -- para listar los
    documentos de un empleado sin cargar todos sus bytes en memoria (mismo
    motivo que Employee.photo se excluye de las consultas de listado)."""

    id: int
    employee_id: int
    filename: str
    category: str
    size_bytes: int
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class PayrollRecord:
    """Nómina GENERADA (histórico persistido), a diferencia de un
    MonthlyPayroll calculado al vuelo: congela el salario/hijos a cargo del
    empleado en el momento de generarla, para que un cambio posterior en su
    ficha no reescriba silenciosamente el histórico."""

    id: int | None
    employee_id: int
    generated_at: datetime
    annual_gross_salary_snapshot: float
    dependent_children_snapshot: int
    payroll: MonthlyPayroll


@dataclass(frozen=True, slots=True)
class MonthlyCostSummary:
    """Coste de personal agregado de un mes concreto, a partir de las
    nóminas GENERADAS de ese mes (no una estimación) -- payroll_count es
    cuántas nóminas componen el total, para que un mes con pocas o ninguna
    nómina generada se note como incompleto en vez de leerse como "coste
    real bajo"."""

    year: int
    month: int
    total_gross: float
    total_employer_cost: float
    payroll_count: int


@dataclass(frozen=True, slots=True)
class DepartmentCostSummary:
    """Lo mismo que MonthlyCostSummary pero agregado por departamento para
    un año/mes concretos -- usa el departamento ACTUAL de cada empleado,
    no el que tuviera en ese mes si desde entonces ha cambiado (esta app no
    guarda historial de departamento, solo de puesto/salario)."""

    department_id: int
    department_name: str
    total_gross: float
    total_employer_cost: float
    payroll_count: int


@dataclass(frozen=True, slots=True)
class EmployeeHistoryEntry:
    """Un tramo del historial de puesto/salario de un empleado: 'desde
    effective_date, este era su puesto y salario' -- no lleva fecha de fin,
    que queda implícita por la siguiente entrada (o 'sigue vigente' si es
    la más reciente)."""

    id: int | None
    employee_id: int
    position: str
    salary: float
    effective_date: date
    note: str


@dataclass(frozen=True, slots=True)
class SeveranceSettlement:
    """El finiquito calculado y guardado al causar baja un empleado --
    congela hire_date/annual_gross_salary tal como estaban en ese momento
    (igual que PayrollRecord), y NUNCA se modifica una vez creado: si hace
    falta corregir algo, se genera una entrada nueva, la anterior queda
    igual (mismo criterio que EmployeeHistoryEntry, no el de "regenerar
    sustituye" de PayrollRecord)."""

    id: int | None
    employee_id: int
    termination_date: date
    termination_reason: str
    hire_date: date
    annual_gross_salary: float
    annual_vacation_days: float
    vacation_days_used_this_year: int
    vacation_days_pending: float
    vacation_amount: float
    extra_payment_months_accrued: int
    extra_payment_amount: float
    total_amount: float
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkAccident:
    """Un accidente de trabajo registrado para un empleado -- el registro
    mínimo que exige la normativa de PRL (Ley 31/1995), no una herramienta
    de evaluación de riesgos completa. `caused_leave` distingue un accidente
    "con baja" de uno "sin baja" (misma distinción que usa el propio parte
    oficial de accidente de trabajo); `reported_to_authority` deja constancia
    de si se ha cumplido con la notificación a la autoridad laboral que la
    ley exige para los casos graves/muy graves/mortales."""

    id: int | None
    employee_id: int
    accident_date: date
    severity: str  # "Leve" | "Grave" | "Muy grave" | "Mortal"
    description: str
    caused_leave: bool
    reported_to_authority: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EmployeeTraining:
    """Un curso de formación o una certificación registrada para un
    empleado -- deliberadamente una única entidad, no dos separadas: la
    única diferencia funcional entre un "curso" y una "certificación" es
    si esta última caduca, y `expiration_date` opcional ya lo capta sin
    necesitar un campo de tipo aparte. `completion_date` no se restringe a
    ser posterior a la fecha de ingreso -- un carné, un idioma u otra
    certificación puede haberse obtenido antes de empezar a trabajar
    aquí, a diferencia de un accidente de trabajo."""

    id: int | None
    employee_id: int
    name: str
    completion_date: date
    expiration_date: date | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Objective:
    """Un objetivo de desempeño para un empleado -- deliberadamente ligero
    (título, fecha objetivo, estado, notas libres), no un sistema de OKR/
    KPI con ponderaciones ni aprobaciones en varios niveles: con un solo
    responsable de RRHH, ese formalismo no aporta nada que una lista con
    fecha y estado no cubra ya. `status` es una lista cerrada de tres
    valores, no un booleano "cumplido sí/no", porque un objetivo cuya
    fecha ya pasó sin cumplirse es un estado real y distinto de "todavía
    pendiente", no la ausencia de "cumplido"."""

    id: int | None
    employee_id: int
    title: str
    target_date: date
    status: str  # "pendiente" | "cumplido" | "no_cumplido"
    notes: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PerformanceReview:
    """Una nota de seguimiento/evaluación de desempeño -- texto libre con
    fecha, deliberadamente sin una puntuación numérica ni una plantilla de
    campos fija: distinto tipo de conversación cada vez (una charla de
    seguimiento, una evaluación anual, una nota tras un proyecto concreto),
    y forzarlas todas al mismo formulario rígido perdería más de lo que
    ordenaría a esta escala."""

    id: int | None
    employee_id: int
    review_date: date
    comments: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AssignedEquipment:
    """Un artículo de material entregado a un empleado -- portátil,
    uniforme, llaves, etc. -- con texto libre en vez de un catálogo
    cerrado (mismo criterio que Employee.position: la variedad real de
    material que puede entregarse en una empresa pequeña no encaja bien en
    una lista fija). `returned_date` opcional distingue lo que sigue en
    manos del empleado (None) de lo ya devuelto, sin necesitar un campo de
    estado aparte -- útil sobre todo al dar de baja a alguien, para saber
    de un vistazo qué queda pendiente de recuperar."""

    id: int | None
    employee_id: int
    description: str
    assigned_date: date
    returned_date: date | None
    notes: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ITEpisode:
    """Un episodio de incapacidad temporal (IT) como entidad propia -- no
    solo un día marcado "Enfermedad" en el calendario. `leave_date` es el
    parte de baja, `last_confirmation_date` el parte de confirmación más
    reciente (opcional: no todas las IT llegan a necesitar uno, y aquí solo
    se guarda el último, no un historial completo de cada confirmación),
    `return_date` el parte de alta -- `None` mientras el episodio sigue
    abierto. `contingency` decide quién paga qué parte del salario durante
    la baja (ver app/incapacidad_temporal.py)."""

    id: int | None
    employee_id: int
    contingency: str  # "Común" | "Accidente de trabajo" | "Accidente no laboral"
    leave_date: date
    last_confirmation_date: date | None
    return_date: date | None
    created_at: datetime

    @property
    def is_open(self) -> bool:
        return self.return_date is None


@dataclass(frozen=True, slots=True)
class AuditLogEntry:
    """Un registro de auditoría es una fotografía del nombre de usuario en
    el momento de la acción, no solo una referencia a users.id -- si el
    usuario se elimina más tarde, el registro histórico sigue siendo
    legible (quién hizo qué) aunque user_id quede a NULL."""

    id: int | None
    occurred_at: datetime
    user_id: int | None
    username: str
    action: str
    details: str


@dataclass(frozen=True, slots=True)
class PayrollSupplement:
    """Un ajuste puntual de UN mes de nómina de un empleado: un plus, unas
    horas extra (con su desglose de horas/precio-hora, para consulta), o un
    anticipo ya pagado por adelantado. `amount` es siempre positivo -- el
    signo con el que afecta al neto (suma o resta) lo decide supplement_type
    en el cálculo, no el propio valor guardado."""

    id: int | None
    employee_id: int
    year: int
    month: int
    supplement_type: str  # "plus" | "horas_extra" | "anticipo"
    description: str
    amount: float
    hours: float | None
    rate_per_hour: float | None
    created_at: datetime
