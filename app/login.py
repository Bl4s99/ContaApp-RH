from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.models import User
from app.repository import Repositories
from app.self_service_ui import EmployeeAccessDialog
from app.theme import apply_theme
from app.window_utils import center_window


class LoginWindow(tk.Tk):
    """Ventana de inicio de sesión. Se ejecuta con su propio mainloop, antes
    de que exista la ventana principal -- solo hay un usuario/contraseña por
    correcta, el llamador debe comprobar `authenticated_user` tras el
    mainloop para saber si debe continuar o si el usuario cerró la ventana."""

    def __init__(self, repos: Repositories) -> None:
        super().__init__()
        apply_theme(self, repos.app_settings.get_theme_mode())
        self.title("ContaApp RH — Iniciar sesión")
        self.resizable(False, False)

        self._repos = repos
        self.authenticated_user: User | None = None

        frame = ttk.Frame(self, padding=32)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text="ContaApp RH",
            style="PageHeading.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(
            frame, text="Inicia sesión para continuar", style="Muted.TLabel"
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 20))

        ttk.Label(frame, text="Usuario").grid(row=2, column=0, sticky="w", pady=4)
        self.username_var = tk.StringVar()
        username_entry = ttk.Entry(frame, textvariable=self.username_var, width=28)
        username_entry.grid(row=2, column=1, sticky="w", pady=4, padx=(8, 0))

        ttk.Label(frame, text="Contraseña").grid(row=3, column=0, sticky="w", pady=4)
        self.password_var = tk.StringVar()
        password_entry = ttk.Entry(
            frame, textvariable=self.password_var, show="•", width=28
        )
        password_entry.grid(row=3, column=1, sticky="w", pady=4, padx=(8, 0))

        self.error_label = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.error_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Button(
            frame, text="Entrar", command=self._handle_login, style="Accent.TButton"
        ).grid(row=5, column=0, columnspan=2, pady=(16, 0))

        ttk.Separator(frame, orient="horizontal").grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(20, 12)
        )
        ttk.Button(
            frame,
            text="¿Eres empleado? Consulta tus datos...",
            command=self._handle_employee_access,
        ).grid(row=7, column=0, columnspan=2)

        username_entry.bind("<Return>", lambda _e: self._handle_login())
        password_entry.bind("<Return>", lambda _e: self._handle_login())
        username_entry.focus_set()

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        center_window(self)

    def _handle_login(self) -> None:
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not username or not password:
            self.error_label.configure(text="Introduce usuario y contraseña.")
            return

        user = self._repos.users.authenticate(username, password)
        self._repos.audit_log.record_login_attempt(
            username, success=user is not None, user_id=user.id if user is not None else None
        )
        if user is None:
            self.error_label.configure(text="Usuario o contraseña incorrectos.")
            self.password_var.set("")
            return

        self.authenticated_user = user
        self.destroy()

    def _handle_employee_access(self) -> None:
        EmployeeAccessDialog(self, self._repos)
