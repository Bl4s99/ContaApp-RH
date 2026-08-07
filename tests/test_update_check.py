from __future__ import annotations

import pytest

from app import update_check
from app.update_check import UpdateInfo, _is_newer, _parse_update_info, check_for_update
from app.version import VERSION


class TestIsNewer:
    def test_higher_patch_is_newer(self) -> None:
        assert _is_newer("1.0.1", "1.0.0") is True

    def test_higher_minor_is_newer(self) -> None:
        assert _is_newer("1.1.0", "1.0.9") is True

    def test_higher_major_is_newer(self) -> None:
        assert _is_newer("2.0.0", "1.9.9") is True

    def test_equal_is_not_newer(self) -> None:
        assert _is_newer("1.0.0", "1.0.0") is False

    def test_lower_is_not_newer(self) -> None:
        assert _is_newer("0.9.9", "1.0.0") is False


class TestParseUpdateInfo:
    def test_newer_version_returns_update_info(self) -> None:
        info = _parse_update_info(
            {"version": "99.0.0", "url": "https://contaapp.es/x.exe", "novedades": "cosas nuevas"}
        )
        assert info == UpdateInfo(
            version="99.0.0", url="https://contaapp.es/x.exe", novedades="cosas nuevas"
        )

    def test_same_version_returns_none(self) -> None:
        assert _parse_update_info({"version": VERSION}) is None

    def test_older_version_returns_none(self) -> None:
        assert _parse_update_info({"version": "0.0.1"}) is None

    def test_missing_url_and_novedades_default_to_empty_string(self) -> None:
        info = _parse_update_info({"version": "99.0.0"})
        assert info is not None
        assert info.url == ""
        assert info.novedades == ""

    def test_missing_version_key_raises_key_error(self) -> None:
        # check_for_update() captura esto -- aquí se comprueba que de verdad
        # se propaga, no que se trague en silencio en la función pura.
        with pytest.raises(KeyError):
            _parse_update_info({})

    def test_non_numeric_version_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            _parse_update_info({"version": "no-es-una-version"})

    def test_numeric_version_is_coerced_via_str(self) -> None:
        # Si el JSON remoto tiene el número sin comillas (1.0 en vez de
        # "1.0.0"), no debe reventar con AttributeError por llamar
        # .split() sobre un float -- se convierte primero con str().
        assert _parse_update_info({"version": 1.0}) is None  # str(1.0) = "1.0", no es más nueva


class TestCheckForUpdate:
    def test_unreachable_host_returns_none_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Mismo límite ya aceptado en el proyecto para PostgreSQL: sin
        # servidor real, solo se puede probar el camino de fallo -- que es,
        # de hecho, el camino que más importa que nunca lance (ver
        # docstring del módulo: la app debe seguir funcionando sin conexión).
        monkeypatch.setattr(update_check, "VERSION_CHECK_URL", "http://127.0.0.1:1/nope")
        assert check_for_update() is None
