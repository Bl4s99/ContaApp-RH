from __future__ import annotations

import sqlite3
import tkinter as tk
import tkinter.messagebox as messagebox

import pytest

from app.collective_agreement_ui import (
    CollectiveAgreementDetailDialog,
    CollectiveAgreementManagerDialog,
    ProfessionalCategoryFormDialog,
)
from app.repository import ProfessionalCategoryInput, Repositories

# tk_root/conn fixtures are session/function-scoped in tests/conftest.py.


class TestCollectiveAgreementManagerDialog:
    def test_creating_an_agreement_adds_it_to_the_list(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dialog = CollectiveAgreementManagerDialog(tk_root, repos)
        dialog.name_var.set("Convenio Estatal de Comercio")
        dialog._handle_create()
        assert dialog.listbox.size() == 1
        assert "Convenio Estatal de Comercio" in dialog.listbox.get(0)
        assert repos.collective_agreements.list_all()[0].name == "Convenio Estatal de Comercio"
        dialog.destroy()

    def test_creating_with_empty_name_shows_an_error_instead_of_crashing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dialog = CollectiveAgreementManagerDialog(tk_root, repos)
        dialog.name_var.set("   ")
        dialog._handle_create()
        assert dialog.error_label.cget("text") != ""
        assert dialog.listbox.size() == 0
        dialog.destroy()

    def test_view_with_nothing_selected_shows_an_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dialog = CollectiveAgreementManagerDialog(tk_root, repos)
        dialog._handle_view()
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()

    def test_delete_with_nothing_selected_shows_an_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        dialog = CollectiveAgreementManagerDialog(tk_root, repos)
        dialog._handle_delete()
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()

    def test_delete_with_confirmation_removes_the_agreement(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        repos = Repositories.create(conn)
        repos.collective_agreements.create("Convenio Estatal de Comercio")
        dialog = CollectiveAgreementManagerDialog(tk_root, repos)
        dialog.listbox.selection_set(0)
        dialog._handle_delete()
        assert dialog.listbox.size() == 0
        assert repos.collective_agreements.list_all() == []
        dialog.destroy()

    def test_listbox_shows_the_category_count_per_agreement(
        self, tk_root: tk.Tk, conn: sqlite3.Connection
    ) -> None:
        repos = Repositories.create(conn)
        agreement = repos.collective_agreements.create("Convenio Estatal de Comercio")
        assert agreement.id is not None
        repos.professional_categories.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement.id, name="Oficial", minimum_salary=18000.0
            )
        )
        dialog = CollectiveAgreementManagerDialog(tk_root, repos)
        assert "1 categoría" in dialog.listbox.get(0)
        dialog.destroy()


class TestCollectiveAgreementDetailDialog:
    @pytest.fixture()
    def agreement_id(self, conn: sqlite3.Connection) -> int:
        repos = Repositories.create(conn)
        agreement = repos.collective_agreements.create("Convenio Estatal de Comercio")
        assert agreement.id is not None
        return agreement.id

    def test_starts_with_no_categories(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repos = Repositories.create(conn)
        dialog = CollectiveAgreementDetailDialog(tk_root, repos, agreement_id)
        assert dialog.categories_tree.get_children() == ()
        dialog.destroy()

    def test_adding_a_category_via_the_form_dialog_shows_up_in_the_tree(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repos = Repositories.create(conn)
        dialog = CollectiveAgreementDetailDialog(tk_root, repos, agreement_id)
        form = ProfessionalCategoryFormDialog(
            dialog, repos, agreement_id, category=None, on_change=dialog._render
        )
        form.name_var.set("Oficial de primera")
        form.minimum_salary_var.set("18000")
        form._handle_save()

        rows = [
            dialog.categories_tree.item(iid, "values")
            for iid in dialog.categories_tree.get_children()
        ]
        assert rows == [("Oficial de primera", "18.000,00 €")]
        dialog.destroy()

    def test_spanish_decimal_comma_is_accepted(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repos = Repositories.create(conn)
        dialog = CollectiveAgreementDetailDialog(tk_root, repos, agreement_id)
        form = ProfessionalCategoryFormDialog(
            dialog, repos, agreement_id, category=None, on_change=dialog._render
        )
        form.name_var.set("Oficial")
        # Coma decimal simple, sin separador de miles -- el mismo formato
        # de entrada ya aceptado (y no más) por el campo de salario de la
        # ficha (ver employee_page.py's _handle_save: "por ejemplo
        # 30000.50", no "30.000,50"); el separador de miles solo aparece
        # al MOSTRAR, nunca al escribir.
        form.minimum_salary_var.set("18000,50")
        form._handle_save()
        [category] = repos.professional_categories.list_for_agreement(agreement_id)
        assert category.minimum_salary == 18000.50
        dialog.destroy()

    def test_invalid_minimum_salary_text_shows_an_error_instead_of_crashing(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repos = Repositories.create(conn)
        dialog = CollectiveAgreementDetailDialog(tk_root, repos, agreement_id)
        form = ProfessionalCategoryFormDialog(
            dialog, repos, agreement_id, category=None, on_change=dialog._render
        )
        form.name_var.set("Malo")
        form.minimum_salary_var.set("no es un numero")
        form._handle_save()
        assert form.error_label.cget("text") != ""
        assert repos.professional_categories.list_for_agreement(agreement_id) == []
        form.destroy()
        dialog.destroy()

    def test_editing_a_category_prefills_the_form_and_updates_it(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repos = Repositories.create(conn)
        category = repos.professional_categories.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement_id, name="Oficial", minimum_salary=18000.0
            )
        )
        assert category.id is not None
        dialog = CollectiveAgreementDetailDialog(tk_root, repos, agreement_id)
        form = ProfessionalCategoryFormDialog(
            dialog, repos, agreement_id, category=category, on_change=dialog._render
        )
        assert form.name_var.get() == "Oficial"
        assert form.minimum_salary_var.get() == "18000.00"
        form.minimum_salary_var.set("19000")
        form._handle_save()
        assert repos.professional_categories.get(category.id).minimum_salary == 19000.0
        dialog.destroy()

    def test_edit_with_nothing_selected_shows_an_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repos = Repositories.create(conn)
        dialog = CollectiveAgreementDetailDialog(tk_root, repos, agreement_id)
        dialog._handle_edit()
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()

    def test_delete_with_nothing_selected_shows_an_error(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, agreement_id: int
    ) -> None:
        repos = Repositories.create(conn)
        dialog = CollectiveAgreementDetailDialog(tk_root, repos, agreement_id)
        dialog._handle_delete()
        assert dialog.error_label.cget("text") != ""
        dialog.destroy()

    def test_delete_with_confirmation_removes_the_category(
        self, tk_root: tk.Tk, conn: sqlite3.Connection, agreement_id: int,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        repos = Repositories.create(conn)
        category = repos.professional_categories.create(
            ProfessionalCategoryInput(
                collective_agreement_id=agreement_id, name="Oficial", minimum_salary=18000.0
            )
        )
        assert category.id is not None
        dialog = CollectiveAgreementDetailDialog(tk_root, repos, agreement_id)
        dialog.categories_tree.selection_set(str(category.id))
        dialog._handle_delete()
        assert dialog.categories_tree.get_children() == ()
        assert repos.professional_categories.list_for_agreement(agreement_id) == []
        dialog.destroy()
