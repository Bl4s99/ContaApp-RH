from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.changelog import CHANGELOG
from app.changelog_page import ChangelogPage
from app.version import VERSION

# tk_root fixture is session-scoped in tests/conftest.py.


def _label_texts(widget: tk.Misc) -> list[str]:
    texts = []
    for child in widget.winfo_children():
        if isinstance(child, (ttk.Label, tk.Label)):
            text = child.cget("text")
            if text:
                texts.append(text)
        texts.extend(_label_texts(child))
    return texts


class TestChangelogPage:
    def test_shows_every_version_and_note(self, tk_root: tk.Tk) -> None:
        page = ChangelogPage(tk_root)
        texts = " ".join(_label_texts(page))
        for entry in CHANGELOG:
            assert entry.version in texts
            for note in entry.notes:
                assert note in texts
        page.destroy()

    def test_marks_the_running_version_as_current(self, tk_root: tk.Tk) -> None:
        page = ChangelogPage(tk_root)
        texts = _label_texts(page)
        current_heading = next(t for t in texts if t.startswith(f"Versión {VERSION}"))
        assert "actual" in current_heading
        page.destroy()

    def test_apply_theme_change_does_not_raise(self, tk_root: tk.Tk) -> None:
        page = ChangelogPage(tk_root)
        page.apply_theme_change()
        page.destroy()
