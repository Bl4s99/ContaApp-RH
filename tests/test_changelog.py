from __future__ import annotations

from datetime import date

from app.changelog import CHANGELOG
from app.version import VERSION


class TestChangelogStructure:
    def test_first_entry_matches_current_version(self) -> None:
        # Guardarraíl de la disciplina "cada versión nueva añade su
        # entrada": si alguien sube VERSION sin anteponer una
        # ChangelogEntry (o viceversa), esto falla de inmediato.
        assert CHANGELOG[0].version == VERSION

    def test_versions_are_strictly_descending(self) -> None:
        parsed = [tuple(int(p) for p in entry.version.split(".")) for entry in CHANGELOG]
        assert parsed == sorted(parsed, reverse=True)

    def test_no_duplicate_versions(self) -> None:
        versions = [entry.version for entry in CHANGELOG]
        assert len(versions) == len(set(versions))

    def test_every_entry_has_at_least_one_note(self) -> None:
        for entry in CHANGELOG:
            assert len(entry.notes) > 0

    def test_every_entry_has_a_valid_iso_date(self) -> None:
        for entry in CHANGELOG:
            date.fromisoformat(entry.date)  # lanza ValueError si el formato no es válido
