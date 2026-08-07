"""Aviso opcional de nueva versión disponible -- NO es un auto-actualizador
(no descarga ni reemplaza nada), solo comprueba en silencio si hay algo más
nuevo publicado en contaapp.es y, si lo hay, deja que quien llama muestre un
aviso con el enlace de descarga. check_for_update() nunca lanza: sin
conexión, con contaapp.es caído, o con una respuesta inesperada, ContaApp RH
sigue funcionando 100% igual -- esto es un aviso, nunca un requisito."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.logging_config import LOGGER_NAME
from app.version import VERSION

VERSION_CHECK_URL = "https://contaapp.es/version-rh.json"
_TIMEOUT_SECONDS = 5


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    url: str
    novedades: str


def _is_newer(remote: str, local: str) -> bool:
    return tuple(int(p) for p in remote.split(".")) > tuple(int(p) for p in local.split("."))


def _parse_update_info(data: Any) -> UpdateInfo | None:
    """Pura, sin E/S -- separada de check_for_update() para poder probar la
    lógica de comparación con dicts hechos a mano, sin red de por medio."""
    remote_version = str(data["version"])
    if not _is_newer(remote_version, VERSION):
        return None
    return UpdateInfo(
        version=remote_version,
        url=str(data.get("url", "")),
        novedades=str(data.get("novedades", "")),
    )


def check_for_update() -> UpdateInfo | None:
    try:
        with urllib.request.urlopen(VERSION_CHECK_URL, timeout=_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
        return _parse_update_info(data)
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
        TypeError,
        OSError,
    ) as exc:
        logging.getLogger(LOGGER_NAME).info(
            "No se pudo comprobar si hay una versión más reciente: %s", exc
        )
        return None
