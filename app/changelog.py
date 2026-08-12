"""Historial de versiones de ContaApp RH -- fuente única para la página
"Historial de versiones" dentro de la app (ver app/changelog_page.py).

Orden: MÁS RECIENTE PRIMERO. Cada vez que se publique una versión nueva:
  1. Subir VERSION en app/version.py.
  2. ANTEPONER (no añadir al final) una ChangelogEntry nueva aquí.
Un test en tests/test_changelog.py hace cumplir que CHANGELOG[0].version
coincida siempre con VERSION.

Se mantiene a mano en sincronía con simple-conta-win/src/routes/versiones-rh.tsx
(misma lista, mismo contenido) y, para la entrada más reciente, con el campo
"novedades" de simple-conta-win/public/version-rh.json -- misma disciplina de
sincronía manual que ya existe hoy entre VERSION y ese mismo fichero JSON."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChangelogEntry:
    version: str
    date: str  # ISO "YYYY-MM-DD"
    notes: tuple[str, ...]


CHANGELOG: tuple[ChangelogEntry, ...] = (
    ChangelogEntry(
        version="1.0.0",
        date="2026-08-07",
        notes=(
            "Primera versión con seguimiento de versión de ContaApp RH.",
            "Nóminas con IRPF real (procedimiento oficial)",
            "Calendario de turnos por departamento",
            "Vacaciones y solicitud de ausencias",
            "Documentos, plantillas y herramientas RGPD/LOPDGDD",
            "Alertas automáticas (contratos, revisiones, formación)",
            "Exportación SEPA y para gestoría",
            "Asistente de primer arranque y configuración de base de datos desde la propia app",
        ),
    ),
)
