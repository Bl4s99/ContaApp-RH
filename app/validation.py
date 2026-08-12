from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^[0-9+\-\s()]{6,20}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_IBAN_STRUCTURE_RE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
_IBAN_COUNTRY_LENGTHS = {"ES": 24}  # tightest check for the app's primary locale

MAX_TEXT_LENGTH = 100
MAX_SALARY = 100_000_000.0
MAX_NOTE_LENGTH = 200
MAX_RANGE_DAYS = 366
MAX_DEPENDENT_CHILDREN = 20
MAX_PERCENTAGE = 100.0
VALID_WEEKDAYS = frozenset(range(1, 8))  # ISO weekdays: 1=lunes .. 7=domingo
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 40
# El asistente de primer arranque (app/setup_wizard.py) es ahora quien crea
# el primer usuario admin, con una contraseña elegida por la propia empresa
# -- ya no hace falta aceptar la antigua semilla débil "admin"/"admin".
MIN_PASSWORD_LENGTH = 8


class ValidationError(Exception):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


def validate_required_text(value: str, field: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValidationError(field, "no puede estar vacío")
    if len(stripped) > MAX_TEXT_LENGTH:
        raise ValidationError(field, f"no puede superar {MAX_TEXT_LENGTH} caracteres")
    return stripped


def validate_email(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("email", "no puede estar vacío")
    if len(stripped) > MAX_TEXT_LENGTH or not _EMAIL_RE.match(stripped):
        raise ValidationError("email", "formato inválido")
    return stripped.lower()


def validate_phone(value: str) -> str:
    stripped = value.strip()
    if stripped and not _PHONE_RE.match(stripped):
        raise ValidationError("teléfono", "formato inválido")
    return stripped


def validate_salary(value: float) -> float:
    if value < 0:
        raise ValidationError("salario", "no puede ser negativo")
    if value > MAX_SALARY:
        raise ValidationError("salario", "valor no realista")
    return float(value)


def validate_minimum_salary(value: float) -> float:
    if value < 0:
        raise ValidationError("salario_minimo", "no puede ser negativo")
    if value > MAX_SALARY:
        raise ValidationError("salario_minimo", "valor no realista")
    return float(value)


def validate_hire_date(value: str) -> date:
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_ingreso", "formato inválido, use AAAA-MM-DD") from exc
    if parsed > date.today():
        raise ValidationError("fecha_ingreso", "no puede ser una fecha futura")
    return parsed


def validate_time_hhmm(value: str, field: str) -> str:
    stripped = value.strip()
    if not _TIME_RE.match(stripped):
        raise ValidationError(field, "hora inválida, use HH:MM en formato 24 horas")
    return stripped


def validate_time_order(start_time: str, end_time: str, *, allow_overnight: bool = False) -> None:
    # allow_overnight=True permite end_time < start_time: un turno que
    # cruza la medianoche (p. ej. 22:00-06:00) -- la capa de fichajes
    # (TimeEntryRepository._validate_alternation()) ya está pensada para
    # turnos nocturnos, así que la definición del turno no debía ser lo
    # único que lo impidiera. Solo el turno de un tramo (o el primero de
    # uno partido) puede cruzar medianoche: el segundo tramo de un turno
    # partido sigue exigiendo el mismo día (allow_overnight=False, el
    # valor por defecto) -- permitir que también él "envuelva" produciría
    # segundos tramos de duración absurda (p. ej. 17:00 a las 15:30 del
    # día siguiente, ~22h) en vez de la breve sesión que un turno partido
    # da a entender.
    if end_time == start_time or (not allow_overnight and end_time < start_time):
        detail = (
            "la hora de fin no puede ser igual a la hora de inicio"
            if end_time == start_time
            else "la hora de fin debe ser posterior a la hora de inicio"
        )
        raise ValidationError("horario", detail)


def validate_split_shift_times(
    start_time_2: str | None, end_time_2: str | None, first_end_time: str
) -> tuple[str, str] | None:
    """Valida el segundo tramo horario opcional de un turno partido.

    Devuelve (inicio, fin) normalizados, o None si no hay segundo tramo.
    """
    start_provided = start_time_2 is not None and start_time_2.strip() != ""
    end_provided = end_time_2 is not None and end_time_2.strip() != ""
    if not start_provided and not end_provided:
        return None
    if start_provided != end_provided:
        raise ValidationError(
            "horario_2",
            "indique hora de inicio y fin del segundo tramo, o déjelas ambas vacías",
        )
    assert start_time_2 is not None and end_time_2 is not None
    clean_start = validate_time_hhmm(start_time_2, "hora_inicio_2")
    clean_end = validate_time_hhmm(end_time_2, "hora_fin_2")
    validate_time_order(clean_start, clean_end)
    if clean_start <= first_end_time:
        raise ValidationError(
            "horario_2", "el segundo tramo debe empezar después de que termine el primero"
        )
    return clean_start, clean_end


def validate_days_of_week(days: Iterable[int]) -> frozenset[int]:
    day_set = frozenset(days)
    if not day_set:
        raise ValidationError("días", "seleccione al menos un día de la semana")
    if not day_set.issubset(VALID_WEEKDAYS):
        raise ValidationError("días", "día de la semana inválido")
    return day_set


def validate_color_hex(value: str) -> str:
    stripped = value.strip()
    if not _COLOR_RE.match(stripped):
        raise ValidationError("color", "debe ser un color hexadecimal, ej. #2ecc71")
    return stripped


def validate_note(value: str) -> str:
    stripped = value.strip()
    if len(stripped) > MAX_NOTE_LENGTH:
        raise ValidationError("nota", f"no puede superar {MAX_NOTE_LENGTH} caracteres")
    return stripped


def validate_iban(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    compact = stripped.replace(" ", "").upper()
    if not _IBAN_STRUCTURE_RE.match(compact):
        raise ValidationError(
            "cuenta_bancaria", "formato de IBAN inválido, ej. ES91 2100 0418 4502 0005 1332"
        )
    country = compact[:2]
    expected_length = _IBAN_COUNTRY_LENGTHS.get(country)
    if expected_length is not None and len(compact) != expected_length:
        raise ValidationError(
            "cuenta_bancaria", f"un IBAN de {country} debe tener {expected_length} caracteres"
        )
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    if int(numeric) % 97 != 1:
        raise ValidationError("cuenta_bancaria", "el IBAN no es válido (dígito de control incorrecto)")
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


MAX_COMPANY_NAME_LENGTH = 70  # límite real del campo <Nm> en SEPA pain.001


def validate_company_name(value: str) -> str:
    stripped = value.strip()
    if len(stripped) > MAX_COMPANY_NAME_LENGTH:
        raise ValidationError(
            "nombre_empresa", f"no puede superar {MAX_COMPANY_NAME_LENGTH} caracteres"
        )
    return stripped


MAX_COMPANY_CCC_LENGTH = 20  # generoso: el formato del CCC ha variado entre reformas


def validate_company_ccc(value: str) -> str:
    # Sin validar el formato exacto (dígitos/separadores) a propósito --
    # mismo criterio que validate_ss_number: el formato ha cambiado varias
    # veces y validar mal rechazaría un CCC real, peor que no validar nada.
    stripped = value.strip()
    if len(stripped) > MAX_COMPANY_CCC_LENGTH:
        raise ValidationError(
            "ccc_empresa", f"no puede superar {MAX_COMPANY_CCC_LENGTH} caracteres"
        )
    return stripped


MAX_COMPANY_ADDRESS_LENGTH = 200


def validate_company_address(value: str) -> str:
    stripped = value.strip()
    if len(stripped) > MAX_COMPANY_ADDRESS_LENGTH:
        raise ValidationError(
            "domicilio_empresa", f"no puede superar {MAX_COMPANY_ADDRESS_LENGTH} caracteres"
        )
    return stripped


_DNI_RE = re.compile(r"^(\d{8})([A-Za-z])$")
_NIE_RE = re.compile(r"^([XYZxyz])(\d{7})([A-Za-z])$")
_DNI_NIE_CONTROL_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
_NIE_PREFIX_DIGITS = {"X": "0", "Y": "1", "Z": "2"}


def validate_dni_nie(value: str) -> str:
    stripped = value.strip().upper().replace(" ", "")
    if not stripped:
        return ""
    dni_match = _DNI_RE.match(stripped)
    nie_match = _NIE_RE.match(stripped)
    if dni_match:
        digits, letter = dni_match.groups()
        numeric = digits
    elif nie_match:
        prefix, digits, letter = nie_match.groups()
        numeric = _NIE_PREFIX_DIGITS[prefix] + digits
    else:
        raise ValidationError(
            "dni_nie", "formato inválido, use DNI (12345678Z) o NIE (X1234567L)"
        )
    expected_letter = _DNI_NIE_CONTROL_LETTERS[int(numeric) % 23]
    if letter != expected_letter:
        raise ValidationError(
            "dni_nie", "la letra no coincide con el número (dígito de control incorrecto)"
        )
    return stripped


_CIF_RE = re.compile(r"^([ABCDEFGHJNPQRSUVW])(\d{7})([0-9A-J])$")
_CIF_LETTER_CONTROL = "JABCDEFGHI"
# N/P/Q/R/S/W exigen letra de control; A/B/E/H exigen dígito; el resto
# (C/D/F/G/I/J/U/V) acepta las dos formas -- simplificación pragmática y
# deliberada: aceptar de más es preferible a rechazar un CIF real.
_CIF_REQUIRES_LETTER = frozenset("NPQRSW")
_CIF_REQUIRES_DIGIT = frozenset("ABEH")


def validate_cif(value: str) -> str:
    stripped = value.strip().upper().replace(" ", "")
    if not stripped:
        return ""
    match = _CIF_RE.match(stripped)
    if not match:
        raise ValidationError("nif_cif", "formato de CIF inválido, ej. B12345674")
    org_letter, digits, control_char = match.groups()
    even_sum = sum(int(d) for d in digits[1::2])
    odd_sum = 0
    for d in digits[0::2]:
        doubled = int(d) * 2
        odd_sum += doubled - 9 if doubled >= 10 else doubled
    control_digit = (10 - (even_sum + odd_sum) % 10) % 10
    expected_letter = _CIF_LETTER_CONTROL[control_digit]
    expected_digit = str(control_digit)
    if org_letter in _CIF_REQUIRES_LETTER:
        valid = control_char == expected_letter
    elif org_letter in _CIF_REQUIRES_DIGIT:
        valid = control_char == expected_digit
    else:
        valid = control_char in (expected_letter, expected_digit)
    if not valid:
        raise ValidationError("nif_cif", "el CIF no es válido (dígito de control incorrecto)")
    return stripped


def validate_company_nif(value: str) -> str:
    """Acepta DNI/NIE (autónomo dado de alta con su propio documento) o CIF
    (sociedad) -- el asistente de primer arranque no sabe de antemano cuál
    de los dos va a introducir la empresa."""
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        return validate_dni_nie(value)
    except ValidationError:
        pass
    try:
        return validate_cif(value)
    except ValidationError:
        raise ValidationError(
            "nif_cif",
            "formato de NIF/CIF inválido, use DNI (12345678Z), NIE (X1234567L) o CIF (B12345674)",
        ) from None


_SS_NUMBER_RE = re.compile(r"^\d{12}$")


def validate_ss_number(value: str) -> str:
    # Formato (12 dígitos: provincia + número + control) únicamente -- no se
    # verifica el dígito de control real. El algoritmo oficial tiene un caso
    # especial poco documentado para números de serie >= 10.000.000 que no
    # se ha podido confirmar con certeza suficiente; validar mal rechazaría
    # números reales válidos, lo cual es peor que no validar el control.
    stripped = value.strip().replace(" ", "").replace("/", "").replace("-", "")
    if not stripped:
        return ""
    if not _SS_NUMBER_RE.match(stripped):
        raise ValidationError(
            "num_seguridad_social",
            "debe tener 12 dígitos (provincia + número + control), ej. 281234567890",
        )
    return stripped


CONTRACT_TYPES: tuple[str, ...] = (
    "Indefinido",
    "Temporal",
    "Formación en alternancia",
    "Prácticas",
    "Fijo-discontinuo",
)


def validate_contract_type(value: str) -> str:
    if value not in CONTRACT_TYPES:
        raise ValidationError("tipo_contrato", "tipo de contrato no válido")
    return value


def validate_contract_end_date(value: str, contract_type: str, hire_date: date) -> date | None:
    stripped = value.strip()
    if not stripped:
        return None
    if contract_type == "Indefinido":
        raise ValidationError(
            "fecha_fin_contrato", "un contrato indefinido no debe tener fecha de fin"
        )
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError(
            "fecha_fin_contrato", "formato inválido, use AAAA-MM-DD"
        ) from exc
    if parsed < hire_date:
        raise ValidationError(
            "fecha_fin_contrato", "no puede ser anterior a la fecha de ingreso"
        )
    return parsed


MINIMUM_WORKING_AGE = 16  # edad laboral mínima general en España (Art. 6 ET)


def validate_birth_date(value: str, hire_date: date) -> date | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_nacimiento", "formato inválido, use AAAA-MM-DD") from exc
    if parsed >= date.today():
        raise ValidationError("fecha_nacimiento", "no puede ser hoy ni una fecha futura")
    if parsed > hire_date:
        raise ValidationError(
            "fecha_nacimiento", "no puede ser posterior a la fecha de ingreso"
        )
    try:
        earliest_hire_date = parsed.replace(year=parsed.year + MINIMUM_WORKING_AGE)
    except ValueError:
        # 29 de febrero cayendo en un año no bisiesto -- mismo criterio que
        # las fechas de aniversario de alerts.py.
        earliest_hire_date = parsed.replace(month=3, day=1, year=parsed.year + MINIMUM_WORKING_AGE)
    if hire_date < earliest_hire_date:
        # Sin esto, se podía dar de alta a alguien con semanas o meses de
        # edad en la fecha de ingreso -- solo se comprobaba que el
        # nacimiento no fuera posterior al ingreso, sin ninguna edad
        # mínima entre ambas fechas.
        raise ValidationError(
            "fecha_nacimiento",
            f"el empleado debe tener al menos {MINIMUM_WORKING_AGE} años en la fecha de ingreso",
        )
    return parsed


def validate_next_medical_checkup_date(value: str) -> date | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError(
            "proxima_revision_medica", "formato inválido, use AAAA-MM-DD"
        ) from exc


def validate_prl_training_date(value: str, hire_date: date) -> date | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError(
            "fecha_formacion_prl", "formato inválido, use AAAA-MM-DD"
        ) from exc
    if parsed > date.today():
        raise ValidationError("fecha_formacion_prl", "no puede ser una fecha futura")
    if parsed < hire_date:
        raise ValidationError(
            "fecha_formacion_prl", "no puede ser anterior a la fecha de ingreso"
        )
    return parsed


WORK_ACCIDENT_SEVERITIES = ("Leve", "Grave", "Muy grave", "Mortal")


def validate_work_accident_severity(value: str) -> str:
    if value not in WORK_ACCIDENT_SEVERITIES:
        raise ValidationError(
            "gravedad", f"debe ser una de: {', '.join(WORK_ACCIDENT_SEVERITIES)}"
        )
    return value


def validate_work_accident_date(
    value: str, hire_date: date, termination_date: date | None = None
) -> date:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("fecha_accidente", "obligatoria")
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_accidente", "formato inválido, use AAAA-MM-DD") from exc
    if parsed > date.today():
        raise ValidationError("fecha_accidente", "no puede ser una fecha futura")
    if parsed < hire_date:
        raise ValidationError(
            "fecha_accidente", "no puede ser anterior a la fecha de ingreso"
        )
    if termination_date is not None and parsed > termination_date:
        # Sin esto, se podía registrar un accidente para un empleado ya
        # inactivo con fecha posterior a su propia baja -- alcanzable
        # desde la app normal filtrando por "Inactivos" y seleccionando
        # cualquier ex-empleado. Un accidente ANTERIOR a la baja (p. ej.
        # una corrección histórica introducida después de tramitarla) sigue
        # siendo válido, por eso se compara contra la fecha de baja, no
        # contra "el empleado debe estar activo".
        raise ValidationError(
            "fecha_accidente", "no puede ser posterior a la fecha de baja del empleado"
        )
    return parsed


def validate_training_completion_date(value: str) -> date:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("fecha_finalizacion", "obligatoria")
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_finalizacion", "formato inválido, use AAAA-MM-DD") from exc
    if parsed > date.today():
        raise ValidationError("fecha_finalizacion", "no puede ser una fecha futura")
    return parsed


def validate_training_expiration_date(value: str, completion_date: date) -> date | None:
    """A diferencia de las demás fechas de este módulo, no se compara con
    hire_date: un carné, un idioma u otra certificación puede haberse
    obtenido antes de empezar a trabajar aquí (ver EmployeeTraining)."""
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_caducidad", "formato inválido, use AAAA-MM-DD") from exc
    if parsed <= completion_date:
        raise ValidationError(
            "fecha_caducidad", "debe ser posterior a la fecha de finalización"
        )
    return parsed


OBJECTIVE_STATUSES = ("pendiente", "cumplido", "no_cumplido")


def validate_objective_target_date(value: str) -> date:
    """A diferencia de la fecha de un accidente o de formación PRL, no se
    compara con hire_date ni se rechaza si es futura: un objetivo por
    definición mira hacia una fecha por cumplir, y registrar uno con fecha
    ya pasada (backfill de un objetivo que se olvidó dar de alta a tiempo)
    también es un caso legítimo."""
    stripped = value.strip()
    if not stripped:
        raise ValidationError("fecha_objetivo", "obligatoria")
    try:
        return datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_objetivo", "formato inválido, use AAAA-MM-DD") from exc


def validate_objective_status(value: str) -> str:
    if value not in OBJECTIVE_STATUSES:
        raise ValidationError("estado", f"debe ser uno de: {', '.join(OBJECTIVE_STATUSES)}")
    return value


def validate_review_date(value: str) -> date:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("fecha_evaluacion", "obligatoria")
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_evaluacion", "formato inválido, use AAAA-MM-DD") from exc
    if parsed > date.today():
        raise ValidationError("fecha_evaluacion", "no puede ser una fecha futura")
    return parsed


def validate_equipment_assigned_date(value: str) -> date:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("fecha_entrega", "obligatoria")
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_entrega", "formato inválido, use AAAA-MM-DD") from exc
    if parsed > date.today():
        raise ValidationError("fecha_entrega", "no puede ser una fecha futura")
    return parsed


def validate_equipment_returned_date(value: str, assigned_date: date) -> date:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("fecha_devolucion", "obligatoria")
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_devolucion", "formato inválido, use AAAA-MM-DD") from exc
    if parsed > date.today():
        raise ValidationError("fecha_devolucion", "no puede ser una fecha futura")
    if parsed < assigned_date:
        raise ValidationError(
            "fecha_devolucion", "no puede ser anterior a la fecha de entrega"
        )
    return parsed


IT_CONTINGENCIES = ("Común", "Accidente de trabajo", "Accidente no laboral")


def validate_it_contingency(value: str) -> str:
    if value not in IT_CONTINGENCIES:
        raise ValidationError(
            "contingencia", f"debe ser una de: {', '.join(IT_CONTINGENCIES)}"
        )
    return value


def validate_it_leave_date(
    value: str, hire_date: date, termination_date: date | None = None
) -> date:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("fecha_baja_it", "obligatoria")
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_baja_it", "formato inválido, use AAAA-MM-DD") from exc
    if parsed > date.today():
        raise ValidationError("fecha_baja_it", "no puede ser una fecha futura")
    if parsed < hire_date:
        raise ValidationError(
            "fecha_baja_it", "no puede ser anterior a la fecha de ingreso"
        )
    if termination_date is not None and parsed > termination_date:
        # Mismo motivo que validate_work_accident_date(): no tiene sentido
        # abrir un episodio de IT para un empleado ya inactivo con fecha
        # posterior a su propia baja.
        raise ValidationError(
            "fecha_baja_it", "no puede ser posterior a la fecha de baja del empleado"
        )
    return parsed


def validate_it_confirmation_date(
    value: str, leave_date: date, last_confirmation_date: date | None = None
) -> date | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError(
            "fecha_confirmacion_it", "formato inválido, use AAAA-MM-DD"
        ) from exc
    if parsed > date.today():
        raise ValidationError("fecha_confirmacion_it", "no puede ser una fecha futura")
    if parsed < leave_date:
        raise ValidationError(
            "fecha_confirmacion_it", "no puede ser anterior a la fecha de baja"
        )
    if last_confirmation_date is not None and parsed < last_confirmation_date:
        # Solo se guarda la ÚLTIMA fecha de confirmación (por diseño), pero
        # sin este chequeo se podía "retroceder" en el tiempo -- una nueva
        # confirmación anterior a la ya registrada no tiene sentido clínico.
        raise ValidationError(
            "fecha_confirmacion_it", "no puede ser anterior a la última confirmación ya registrada"
        )
    return parsed


def validate_it_return_date(
    value: str, leave_date: date, last_confirmation_date: date | None = None
) -> date | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_alta_it", "formato inválido, use AAAA-MM-DD") from exc
    if parsed > date.today():
        raise ValidationError("fecha_alta_it", "no puede ser una fecha futura")
    if parsed < leave_date:
        raise ValidationError(
            "fecha_alta_it", "no puede ser anterior a la fecha de baja"
        )
    if last_confirmation_date is not None and parsed < last_confirmation_date:
        # Un alta médica no puede ser anterior a la última confirmación de
        # que la baja seguía vigente -- sería clínicamente imposible.
        raise ValidationError(
            "fecha_alta_it", "no puede ser anterior a la última confirmación registrada"
        )
    return parsed


TERMINATION_REASONS: tuple[str, ...] = (
    "Baja voluntaria",
    "Despido procedente",
    "Despido improcedente",
    "Fin de contrato temporal",
    "Jubilación",
    "Fallecimiento",
    "Otro",
)


def validate_termination_reason(value: str) -> str:
    if value not in TERMINATION_REASONS:
        raise ValidationError("motivo_baja", "motivo de baja no válido")
    return value


def validate_termination_date(value: str, hire_date: date) -> date:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("fecha_baja", "no puede estar vacía")
    try:
        parsed = datetime.strptime(stripped, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError("fecha_baja", "formato inválido, use AAAA-MM-DD") from exc
    if parsed < hire_date:
        raise ValidationError("fecha_baja", "no puede ser anterior a la fecha de ingreso")
    if parsed > date.today():
        # A diferencia del resto de validadores de fecha del dominio (todos
        # rechazan el futuro), esta era la única excepción -- una fecha de
        # baja futura dejaba al empleado inactivo DESDE HOY (terminate()
        # aplica active=0 de inmediato) y generaba un finiquito permanente
        # calculado como si la baja ya hubiera ocurrido, sin que exista
        # ningún concepto de "baja programada" en el resto de la app.
        raise ValidationError("fecha_baja", "no puede ser una fecha futura")
    return parsed


DOCUMENT_CATEGORIES: tuple[str, ...] = ("Contrato", "DNI/NIE", "Certificado", "Otro")
MAX_FILENAME_LENGTH = 255
MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def validate_document_category(value: str) -> str:
    if value not in DOCUMENT_CATEGORIES:
        raise ValidationError("categoria_documento", "categoría de documento no válida")
    return value


def validate_document_filename(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("nombre_archivo", "no puede estar vacío")
    if len(stripped) > MAX_FILENAME_LENGTH:
        raise ValidationError(
            "nombre_archivo", f"no puede superar {MAX_FILENAME_LENGTH} caracteres"
        )
    return stripped


def validate_document_content(value: bytes) -> bytes:
    if not value:
        raise ValidationError("archivo", "el archivo está vacío")
    if len(value) > MAX_DOCUMENT_SIZE_BYTES:
        raise ValidationError(
            "archivo", f"el archivo no puede superar {MAX_DOCUMENT_SIZE_BYTES // (1024 * 1024)} MB"
        )
    return value


def validate_dependent_children(value: int) -> int:
    if value < 0:
        raise ValidationError("hijos_a_cargo", "no puede ser negativo")
    if value > MAX_DEPENDENT_CHILDREN:
        raise ValidationError("hijos_a_cargo", f"no puede superar {MAX_DEPENDENT_CHILDREN}")
    return value


MAX_ANNUAL_VACATION_DAYS = 365.0


def validate_annual_vacation_days(value: float) -> float:
    if value < 0:
        raise ValidationError("dias_vacaciones_anuales", "no puede ser negativo")
    if value > MAX_ANNUAL_VACATION_DAYS:
        raise ValidationError(
            "dias_vacaciones_anuales", f"no puede superar {MAX_ANNUAL_VACATION_DAYS:.0f}"
        )
    return float(value)


MAX_DATA_RETENTION_YEARS = 50


def validate_data_retention_years(value: int) -> int:
    if value < 0:
        raise ValidationError("anos_conservacion_datos", "no puede ser negativo")
    if value > MAX_DATA_RETENTION_YEARS:
        raise ValidationError(
            "anos_conservacion_datos", f"no puede superar {MAX_DATA_RETENTION_YEARS}"
        )
    return int(value)


def validate_percentage(value: float, field: str) -> float:
    if value < 0:
        raise ValidationError(field, "no puede ser negativo")
    if value > MAX_PERCENTAGE:
        raise ValidationError(field, f"no puede superar {MAX_PERCENTAGE}%")
    return float(value)


def validate_username(value: str) -> str:
    stripped = value.strip()
    if len(stripped) < MIN_USERNAME_LENGTH:
        raise ValidationError(
            "usuario", f"debe tener al menos {MIN_USERNAME_LENGTH} caracteres"
        )
    if len(stripped) > MAX_USERNAME_LENGTH:
        raise ValidationError("usuario", f"no puede superar {MAX_USERNAME_LENGTH} caracteres")
    return stripped


def validate_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            "contraseña", f"debe tener al menos {MIN_PASSWORD_LENGTH} caracteres"
        )
    return value


_ACCESS_PIN_RE = re.compile(r"^\d{4,6}$")


def validate_access_pin(value: str) -> str:
    stripped = value.strip()
    if not _ACCESS_PIN_RE.match(stripped):
        raise ValidationError("pin", "debe tener entre 4 y 6 dígitos numéricos")
    return stripped


EMAIL_PROVIDERS: tuple[str, ...] = ("gmail", "outlook")


def validate_email_provider(value: str) -> str:
    if value not in EMAIL_PROVIDERS:
        raise ValidationError("proveedor_correo", f"debe ser uno de: {', '.join(EMAIL_PROVIDERS)}")
    return value


def validate_app_password(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("contraseña_de_aplicación", "no puede estar vacía")
    return stripped


USER_ROLES: tuple[str, ...] = ("admin", "encargado")


def validate_user_role_and_department(
    role: str, department_id: int | None
) -> tuple[str, int | None]:
    if role not in USER_ROLES:
        raise ValidationError("rol", "rol de usuario no válido")
    if role == "encargado" and department_id is None:
        raise ValidationError("departamento", "un encargado debe tener un departamento asignado")
    if role == "admin" and department_id is not None:
        raise ValidationError("departamento", "un administrador no debe tener departamento asignado")
    return role, department_id


VALID_THEME_MODES = frozenset({"light", "dark"})


def validate_theme_mode(value: str) -> str:
    if value not in VALID_THEME_MODES:
        raise ValidationError("tema", "modo de tema no válido")
    return value


VALID_TIME_ENTRY_TYPES = frozenset({"entrada", "salida"})


def validate_time_entry_type(value: str) -> str:
    if value not in VALID_TIME_ENTRY_TYPES:
        raise ValidationError("tipo_fichaje", "tipo de fichaje no válido")
    return value


def validate_time_entry_timestamp(value: datetime) -> datetime:
    if value > datetime.now():
        raise ValidationError("fichaje", "la fecha y hora no pueden ser futuras")
    return value


def validate_date_range(start: date, end: date) -> None:
    if end < start:
        raise ValidationError(
            "rango_fechas", "la fecha final no puede ser anterior a la inicial"
        )
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise ValidationError("rango_fechas", f"el rango no puede superar {MAX_RANGE_DAYS} días")


SUPPLEMENT_TYPES: tuple[str, ...] = ("plus", "horas_extra", "anticipo", "dietas", "bonos")
MAX_SUPPLEMENT_AMOUNT = 1_000_000.0
MAX_OVERTIME_HOURS_PER_ENTRY = 300.0  # límite de cordura (un mes tiene ~730h), no un límite legal


def validate_supplement_type(value: str) -> str:
    if value not in SUPPLEMENT_TYPES:
        raise ValidationError("tipo_complemento", "tipo de complemento no válido")
    return value


def validate_supplement_amount(value: float) -> float:
    if value <= 0:
        raise ValidationError("importe", "debe ser mayor que 0")
    if value > MAX_SUPPLEMENT_AMOUNT:
        raise ValidationError("importe", f"no puede superar {MAX_SUPPLEMENT_AMOUNT:,.0f}")
    return round(value, 2)


def validate_overtime_hours_and_rate(hours: float, rate_per_hour: float) -> tuple[float, float]:
    if hours <= 0:
        raise ValidationError("horas", "debe ser mayor que 0")
    if hours > MAX_OVERTIME_HOURS_PER_ENTRY:
        raise ValidationError("horas", f"no puede superar {MAX_OVERTIME_HOURS_PER_ENTRY:.0f}")
    if rate_per_hour <= 0:
        raise ValidationError("precio_hora", "debe ser mayor que 0")
    return hours, rate_per_hour


DEFAULT_HOLIDAY_LABEL = "Festivo"
MAX_HOLIDAY_IMPORT_LINES = 400
_HOLIDAY_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\s+(.*))?$")


def validate_holiday_label(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("etiqueta_festivo", "no puede estar vacía")
    if len(stripped) > MAX_TEXT_LENGTH:
        raise ValidationError("etiqueta_festivo", f"no puede superar {MAX_TEXT_LENGTH} caracteres")
    return stripped


def parse_holiday_import_text(text: str) -> list[tuple[date, str]]:
    """Convierte el texto pegado por el usuario en pares (fecha, etiqueta).

    Una fecha por línea: 'AAAA-MM-DD [etiqueta libre]' -- si falta la
    etiqueta se usa DEFAULT_HOLIDAY_LABEL. Las líneas vacías o que empiezan
    por '#' se ignoran (sirven para agrupar visualmente el texto pegado,
    ej. '# Nacional' / '# Autonómico' / '# Local'). Una fecha repetida
    dentro del mismo texto se rechaza en vez de ignorarse en silencio: casi
    siempre es la misma lista pegada dos veces por error, no una intención
    real.
    """
    results: list[tuple[date, str]] = []
    seen: set[date] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _HOLIDAY_LINE_RE.match(stripped)
        if match is None:
            raise ValidationError(
                "importar_festivos",
                f"línea {line_number}: formato inválido, use AAAA-MM-DD [etiqueta]",
            )
        try:
            holiday_date = date.fromisoformat(match.group(1))
        except ValueError as exc:
            raise ValidationError(
                "importar_festivos", f"línea {line_number}: fecha inválida"
            ) from exc
        if holiday_date in seen:
            raise ValidationError(
                "importar_festivos",
                f"línea {line_number}: la fecha {holiday_date.isoformat()} aparece más de una vez",
            )
        seen.add(holiday_date)
        label = validate_holiday_label(match.group(2) or DEFAULT_HOLIDAY_LABEL)
        results.append((holiday_date, label))
    if not results:
        raise ValidationError("importar_festivos", "no se ha reconocido ninguna fecha")
    if len(results) > MAX_HOLIDAY_IMPORT_LINES:
        raise ValidationError(
            "importar_festivos",
            f"no puede importar más de {MAX_HOLIDAY_IMPORT_LINES} fechas de una vez",
        )
    return results


MAX_DOCUMENT_TEMPLATE_BODY_LENGTH = 20_000  # límite de cordura, no un límite real de documento


def validate_document_template_body(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValidationError("cuerpo_plantilla", "no puede estar vacío")
    if len(stripped) > MAX_DOCUMENT_TEMPLATE_BODY_LENGTH:
        raise ValidationError(
            "cuerpo_plantilla",
            f"no puede superar {MAX_DOCUMENT_TEMPLATE_BODY_LENGTH} caracteres",
        )
    return stripped


CANDIDATE_PHASES: tuple[str, ...] = ("Recibido", "Entrevista", "Oferta", "Contratado", "Descartado")


def validate_candidate_phase(value: str) -> str:
    if value not in CANDIDATE_PHASES:
        raise ValidationError("fase_candidato", "fase no válida")
    return value
