from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app import validation
from app.repository import Repositories
from app.theme import apply_theme
from app.window_utils import center_window


class SetupWizard(tk.Tk):
    """Asistente de primer arranque. Se ejecuta con su propio mainloop, antes
    de que exista `LoginWindow` -- solo aparece cuando la base de datos está
    vacía de usuarios (instalación nueva). Recoge los datos de la empresa y
    crea la primera cuenta de administrador, en vez de sembrar una cuenta
    "admin"/"admin" fija. El llamador debe comprobar `completed` tras el
    mainloop: si es False, el usuario cerró el asistente sin terminarlo y no
    se ha creado nada."""

    def __init__(self, repos: Repositories) -> None:
        super().__init__()
        apply_theme(self, repos.app_settings.get_theme_mode())
        self.title("ContaApp RH — Configuración inicial")
        self.resizable(False, False)

        self._repos = repos
        self.completed = False

        frame = ttk.Frame(self, padding=32)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text="Bienvenido a ContaApp RH",
            style="PageHeading.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(
            frame,
            text="Antes de empezar, configura tu empresa y tu cuenta de administrador.",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 20))

        ttk.Label(frame, text="Nombre de la empresa").grid(row=2, column=0, sticky="w", pady=4)
        self.company_name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.company_name_var, width=32).grid(
            row=2, column=1, sticky="w", pady=4, padx=(8, 0)
        )

        ttk.Label(frame, text="NIF / CIF").grid(row=3, column=0, sticky="w", pady=4)
        self.company_nif_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.company_nif_var, width=32).grid(
            row=3, column=1, sticky="w", pady=4, padx=(8, 0)
        )

        ttk.Separator(frame, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(16, 12)
        )

        ttk.Label(frame, text="Usuario administrador").grid(row=5, column=0, sticky="w", pady=4)
        self.username_var = tk.StringVar()
        username_entry = ttk.Entry(frame, textvariable=self.username_var, width=32)
        username_entry.grid(row=5, column=1, sticky="w", pady=4, padx=(8, 0))

        ttk.Label(frame, text="Contraseña").grid(row=6, column=0, sticky="w", pady=4)
        self.password_var = tk.StringVar()
        password_entry = ttk.Entry(
            frame, textvariable=self.password_var, show="•", width=32
        )
        password_entry.grid(row=6, column=1, sticky="w", pady=4, padx=(8, 0))

        ttk.Label(frame, text="Confirmar contraseña").grid(row=7, column=0, sticky="w", pady=4)
        self.confirm_password_var = tk.StringVar()
        confirm_entry = ttk.Entry(
            frame, textvariable=self.confirm_password_var, show="•", width=32
        )
        confirm_entry.grid(row=7, column=1, sticky="w", pady=4, padx=(8, 0))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=340)
        self.error_label.grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Button(
            frame, text="Empezar", command=self._handle_setup, style="Accent.TButton"
        ).grid(row=9, column=0, columnspan=2, pady=(16, 0))

        confirm_entry.bind("<Return>", lambda _e: self._handle_setup())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self)

    def _handle_setup(self) -> None:
        company_name = self.company_name_var.get().strip()
        company_nif = self.company_nif_var.get().strip()
        username = self.username_var.get().strip()
        password = self.password_var.get()
        confirm_password = self.confirm_password_var.get()

        if not company_name or not company_nif or not username or not password:
            self.error_label.configure(text="Rellena todos los campos.")
            return
        if password != confirm_password:
            self.error_label.configure(text="Las contraseñas no coinciden.")
            return

        try:
            self._repos.app_settings.set_company_name(company_name)
            self._repos.app_settings.set_company_nif(company_nif)
            self._repos.users.create(username, password)
        except validation.ValidationError as exc:
            # No exc.message.capitalize(): mayusculiza también siglas como
            # "NIF/CIF" o "DNI" dentro del mensaje, dejándolas ilegibles.
            self.error_label.configure(text=exc.message)
            return

        self.completed = True
        self.destroy()
