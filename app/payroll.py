"""Estimación orientativa de nómina española (procedimiento general de retención
de IRPF, arts. 80-87 del Reglamento del IRPF, y cotizaciones a la Seguridad Social).

AVISO IMPORTANTE — LEER ANTES DE USAR:
Esto es una ESTIMACIÓN para uso interno, no una nómina oficial ni válida para
presentar impuestos. Simplificaciones deliberadas frente al cálculo oficial
completo que haría una gestoría:
  - Solo la escala estatal de retención (Art. 101 LIRPF); no incluye el tramo
    autonómico específico de cada comunidad.
  - El mínimo personal y familiar solo cubre el mínimo del contribuyente y el
    mínimo por descendientes. NO incluye ascendientes a cargo, discapacidad,
    ni el incremento por edad del contribuyente (65+/75+).
  - Los umbrales de la reducción por obtención de rendimientos del trabajo y
    los tramos de la escala de retención corresponden a la normativa vigente
    en el momento de escribir este módulo. La Ley de Presupuestos puede
    actualizarlos cada año — verifica que sigan siendo correctos para el
    ejercicio fiscal actual antes de usar estas cifras para decisiones reales.
Consulta siempre con una gestoría o asesor laboral antes de pagar nóminas
reales basándote en estos cálculos.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Escala general de retenciones (Art. 101 LIRPF) ---
# Lista de (límite_superior_del_tramo, tipo_marginal).
IRPF_RETENTION_BRACKETS: list[tuple[float, float]] = [
    (12450.0, 0.19),
    (20200.0, 0.24),
    (35200.0, 0.30),
    (60000.0, 0.37),
    (300000.0, 0.45),
    (float("inf"), 0.47),
]

# --- Mínimo personal y familiar (Art. 57 y 58 LIRPF) ---
MINIMO_CONTRIBUYENTE = 5550.0
# Importe por 1er, 2º, 3er, 4º-y-siguientes hijo a cargo (cada uno, no acumulativo distinto).
MINIMO_DESCENDIENTES = [2400.0, 2700.0, 4000.0, 4500.0]

# --- Reducción por obtención de rendimientos del trabajo (Art. 20 LIRPF) ---
REDUCCION_RENDIMIENTOS_MAX = 7302.0
REDUCCION_RENDIMIENTOS_UMBRAL_BAJO = 14047.5
REDUCCION_RENDIMIENTOS_UMBRAL_ALTO = 19747.5
REDUCCION_RENDIMIENTOS_MIN = 2364.0

MAX_TIPO_RETENCION_PCT = 47.0
PAGAS_TOTALES = 14
MESES_PAGA_EXTRA = frozenset({7, 12})  # julio y diciembre


def _apply_progressive_scale(base: float, brackets: list[tuple[float, float]]) -> float:
    if base <= 0:
        return 0.0
    tax = 0.0
    lower = 0.0
    for upper, rate in brackets:
        if base <= lower:
            break
        tax += (min(base, upper) - lower) * rate
        lower = upper
    return tax


def minimo_por_descendientes(dependent_children: int) -> float:
    if dependent_children <= 0:
        return 0.0
    total = 0.0
    for index in range(dependent_children):
        bracket_index = min(index, len(MINIMO_DESCENDIENTES) - 1)
        total += MINIMO_DESCENDIENTES[bracket_index]
    return total


def reduccion_rendimientos_trabajo(rendimiento_neto: float) -> float:
    if rendimiento_neto <= REDUCCION_RENDIMIENTOS_UMBRAL_BAJO:
        return REDUCCION_RENDIMIENTOS_MAX
    if rendimiento_neto >= REDUCCION_RENDIMIENTOS_UMBRAL_ALTO:
        # No a 0.0: la reducción tiene un SUELO de REDUCCION_RENDIMIENTOS_MIN
        # para quien supera el umbral alto (Art. 20 LIRPF) -- saltar a 0
        # aquí producía una discontinuidad de ~2364€ en la base imponible
        # justo en este punto, haciendo que un euro más de salario pudiera
        # bajar el neto mensual varios euros. REDUCCION_RENDIMIENTOS_MIN es
        # precisamente ese suelo, no un valor que solo se toque en el
        # instante exacto del umbral.
        return REDUCCION_RENDIMIENTOS_MIN
    span = REDUCCION_RENDIMIENTOS_UMBRAL_ALTO - REDUCCION_RENDIMIENTOS_UMBRAL_BAJO
    progress = (rendimiento_neto - REDUCCION_RENDIMIENTOS_UMBRAL_BAJO) / span
    return REDUCCION_RENDIMIENTOS_MAX - progress * (
        REDUCCION_RENDIMIENTOS_MAX - REDUCCION_RENDIMIENTOS_MIN
    )


def estimate_irpf_withholding_rate(
    annual_gross_salary: float, ss_employee_pct: float, dependent_children: int
) -> float:
    """Tipo de retención de IRPF estimado, en % (0-47), redondeado a 2 decimales."""
    if annual_gross_salary <= 0:
        return 0.0

    ss_employee_annual = annual_gross_salary * (ss_employee_pct / 100.0)
    rendimiento_neto = max(0.0, annual_gross_salary - ss_employee_annual)

    reduccion = reduccion_rendimientos_trabajo(rendimiento_neto)
    base_para_tipo = max(0.0, rendimiento_neto - reduccion)
    if base_para_tipo <= 0:
        return 0.0

    minimo_personal_familiar = MINIMO_CONTRIBUYENTE + minimo_por_descendientes(
        dependent_children
    )

    cuota_sobre_base = _apply_progressive_scale(base_para_tipo, IRPF_RETENTION_BRACKETS)
    cuota_sobre_minimo = _apply_progressive_scale(
        minimo_personal_familiar, IRPF_RETENTION_BRACKETS
    )
    cuota_retencion = max(0.0, cuota_sobre_base - cuota_sobre_minimo)

    tipo = (cuota_retencion / base_para_tipo) * 100.0
    return round(min(tipo, MAX_TIPO_RETENCION_PCT), 2)


@dataclass(frozen=True, slots=True)
class MonthlyPayroll:
    month: int
    year: int
    paga_ordinaria: float
    paga_extra: float
    supplements_total: float
    bruto_mes: float
    irpf_pct: float
    irpf_importe: float
    ss_employee_pct: float
    ss_employee_importe: float
    advances_total: float
    neto: float
    ss_employer_pct: float
    ss_employer_importe: float
    coste_total_empresa: float


def calculate_monthly_payroll(
    annual_gross_salary: float,
    dependent_children: int,
    ss_employee_pct: float,
    ss_employer_pct: float,
    month: int,
    year: int,
    supplements_total: float = 0.0,
    advances_total: float = 0.0,
    irpf_pct_override: float | None = None,
) -> MonthlyPayroll:
    """supplements_total (pluses + horas extra) y advances_total (anticipos ya
    pagados) son ajustes puntuales de UN mes concreto, no del salario anual
    base -- por eso son parámetros aparte en vez de tocar annual_gross_salary.
    Simplificación deliberada, documentada aquí y en el aviso de la UI: el
    tipo de IRPF (irpf_pct) sigue calculándose sobre el salario anual base
    (sin complementos, que son variables mes a mes y no se pueden proyectar
    con la misma fiabilidad), pero el IMPORTE retenido si se aplica sobre el
    bruto del mes ya con los complementos incluidos -- igual que hacen en la
    práctica muchos programas de nómina reales con las percepciones variables.

    irpf_pct_override, si se da, sustituye a estimate_irpf_withholding_rate()
    por completo -- pensado para el % real que una gestoría ya ha calculado
    (con tramo autonómico, discapacidad, etc. que esta estimación no cubre,
    ver el aviso al principio del módulo), no solo para corregir la
    estimación interna. Por eso no se limita a MAX_TIPO_RETENCION_PCT: ese
    tope es del procedimiento de ESTIMACIÓN, no una regla general del IRPF."""
    if not 1 <= month <= 12:
        raise ValueError(f"mes fuera de rango: {month}")
    if supplements_total < 0:
        raise ValueError("supplements_total no puede ser negativo")
    if advances_total < 0:
        raise ValueError("advances_total no puede ser negativo")
    if irpf_pct_override is not None and irpf_pct_override < 0:
        raise ValueError("irpf_pct_override no puede ser negativo")

    paga_ordinaria = round(annual_gross_salary / PAGAS_TOTALES, 2)
    paga_extra = paga_ordinaria if month in MESES_PAGA_EXTRA else 0.0
    bruto_mes = round(paga_ordinaria + paga_extra + supplements_total, 2)

    irpf_pct = (
        round(irpf_pct_override, 2)
        if irpf_pct_override is not None
        else estimate_irpf_withholding_rate(annual_gross_salary, ss_employee_pct, dependent_children)
    )
    irpf_importe = round(bruto_mes * irpf_pct / 100.0, 2)

    ss_employee_importe = round(bruto_mes * ss_employee_pct / 100.0, 2)
    neto = round(bruto_mes - irpf_importe - ss_employee_importe - advances_total, 2)

    ss_employer_importe = round(bruto_mes * ss_employer_pct / 100.0, 2)
    coste_total_empresa = round(bruto_mes + ss_employer_importe, 2)

    return MonthlyPayroll(
        month=month,
        year=year,
        paga_ordinaria=paga_ordinaria,
        paga_extra=paga_extra,
        supplements_total=round(supplements_total, 2),
        bruto_mes=bruto_mes,
        irpf_pct=irpf_pct,
        irpf_importe=irpf_importe,
        ss_employee_pct=ss_employee_pct,
        ss_employee_importe=ss_employee_importe,
        advances_total=round(advances_total, 2),
        neto=neto,
        ss_employer_pct=ss_employer_pct,
        ss_employer_importe=ss_employer_importe,
        coste_total_empresa=coste_total_empresa,
    )
