from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk


@dataclass(frozen=True, slots=True)
class Palette:
    primary_dark: str
    primary: str
    primary_light: str
    primary_pale: str
    bg: str
    surface: str
    border: str
    text: str
    text_muted: str
    text_on_dark: str
    text_on_dark_muted: str
    danger: str
    today_highlight: str
    shift_cell_color: str
    sidebar_separator: str
    disclaimer_bg: str
    disclaimer_fg: str
    heading_text: str


# Azul pizarra profesional, sin saturar -- pensado para no perder la
# seriedad de una app de gestión mientras aporta color e identidad visual.
# SURFACE es blanco roto (no #ffffff puro) a propósito: más suave a la vista.
LIGHT = Palette(
    primary_dark="#1c3d5c",
    primary="#2f6690",
    primary_light="#5b9bd5",
    primary_pale="#e8f0f7",
    bg="#f4f6f9",
    surface="#fafbfc",
    border="#d7dee6",
    text="#22303f",
    text_muted="#66758a",
    text_on_dark="#eef3f8",
    text_on_dark_muted="#9fb8cc",
    danger="#c0392b",
    today_highlight="#d6e4f0",
    shift_cell_color="#dbe9f6",
    sidebar_separator="#2f5678",
    disclaimer_bg="#fdf3cd",
    disclaimer_fg="#7a5b00",
    # Mismo tono que primary_dark en claro (a propósito -- aquí SÍ funciona
    # como texto, por el contraste con bg claro), pero es un campo aparte
    # porque en oscuro NO puede reutilizar primary_dark: ese valor se vuelve
    # casi negro y sirve de FONDO fijo de la barra lateral, no de texto.
    heading_text="#1c3d5c",
)

# Rediseño del modo oscuro (v2): base neutra tipo carbón/grafito en vez de
# la marino-sobre-marino original -- el acento azul destaca más al no
# competir con un fondo ya azulado, y el contraste texto/fondo sube.
DARK = Palette(
    primary_dark="#10131a",
    primary="#4f9fe8",
    primary_light="#7cc4f7",
    primary_pale="#1b2a3d",
    bg="#181a20",
    surface="#20232b",
    border="#343841",
    text="#e9ebef",
    text_muted="#9399a6",
    text_on_dark="#f2f4f7",
    text_on_dark_muted="#8a93a3",
    danger="#f0685f",
    today_highlight="#26415c",
    shift_cell_color="#213347",
    sidebar_separator="#080a0e",
    disclaimer_bg="#3d3115",
    disclaimer_fg="#f2cf6b",
    # primary_dark ("#10131a") es casi negro en este modo -- correcto como
    # fondo fijo de la barra lateral, ilegible como texto sobre bg/surface
    # (también oscuros). primary_light da el mismo peso visual de "titular
    # con acento" que primary_dark aporta en el modo claro, pero legible.
    heading_text="#7cc4f7",
)

_HEADING_FONT = ("TkDefaultFont", 16, "bold")

_active = LIGHT
_active_mode = "light"


def current() -> Palette:
    """La paleta actualmente activa. Siempre se llama en el momento de
    dibujar/reconstruir un widget (nunca se guarda el resultado en una
    constante de módulo) para que el cambio claro/oscuro se refleje sin
    reiniciar la app."""
    return _active


def current_mode() -> str:
    return _active_mode


def apply_theme(root: tk.Tk, mode: str = "light") -> None:
    """Configura el aspecto visual de toda la app para `mode` ("light" o
    "dark"). Puede llamarse más de una vez sobre la misma ventana -- cada
    llamada reconfigura los estilos con nombre, y todo widget ttk que use
    esos estilos se repinta solo. Los pocos widgets con color fijado
    directamente (no vía estilo) deben releerse aparte tras el cambio; ver
    MainWindow.set_theme_mode."""
    global _active, _active_mode
    _active = DARK if mode == "dark" else LIGHT
    _active_mode = "dark" if mode == "dark" else "light"
    p = _active

    root.configure(background=p.bg)

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=p.bg, foreground=p.text)
    style.configure("TFrame", background=p.bg)
    style.configure("TLabel", background=p.bg, foreground=p.text)
    style.configure("TCheckbutton", background=p.bg, foreground=p.text)
    style.map("TCheckbutton", background=[("active", p.bg)])

    style.configure(
        "TButton",
        background=p.surface,
        foreground=p.text,
        bordercolor=p.border,
        lightcolor=p.surface,
        darkcolor=p.surface,
        padding=(10, 5),
    )
    style.map(
        "TButton",
        background=[("active", p.primary_pale), ("pressed", p.primary_pale)],
        bordercolor=[("focus", p.primary_light)],
    )

    style.configure(
        "Accent.TButton",
        background=p.primary,
        foreground="#ffffff",
        bordercolor=p.primary,
        lightcolor=p.primary,
        darkcolor=p.primary,
        padding=(12, 6),
    )
    style.map(
        "Accent.TButton",
        background=[("active", p.primary_light), ("pressed", p.primary_dark)],
        bordercolor=[("active", p.primary_light), ("pressed", p.primary_dark)],
    )

    style.configure("TEntry", fieldbackground=p.surface, bordercolor=p.border, foreground=p.text)
    style.map("TEntry", bordercolor=[("focus", p.primary_light)])

    style.configure(
        "TCombobox",
        fieldbackground=p.surface,
        background=p.surface,
        bordercolor=p.border,
        foreground=p.text,
        arrowcolor=p.primary,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", p.surface)],
        bordercolor=[("focus", p.primary_light)],
    )
    root.option_add("*TCombobox*Listbox.background", p.surface)
    root.option_add("*TCombobox*Listbox.foreground", p.text)
    root.option_add("*TCombobox*Listbox.selectBackground", p.primary_light)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    style.configure("TSpinbox", fieldbackground=p.surface, bordercolor=p.border, foreground=p.text)

    style.configure("TSeparator", background=p.border)

    # El propio Panedwindow y su sash (la barra arrastrable entre paneles)
    # nunca se habían reconfigurado -- se quedaban con el gris por defecto
    # del tema "clam" de fábrica, una franja clara fuera de lugar sobre un
    # fondo oscuro.
    style.configure("TPanedwindow", background=p.bg)
    style.configure("Sash", sashthickness=6, gripcount=0, background=p.border)

    style.configure("TLabelframe", background=p.bg, bordercolor=p.border)
    style.configure("TLabelframe.Label", background=p.bg, foreground=p.heading_text)

    style.configure(
        "Treeview",
        background=p.surface,
        fieldbackground=p.surface,
        foreground=p.text,
        bordercolor=p.border,
        rowheight=24,
    )
    style.map(
        "Treeview",
        background=[("selected", p.primary_light)],
        foreground=[("selected", "#ffffff")],
    )
    style.configure(
        "Treeview.Heading",
        background=p.primary_dark,
        foreground="#ffffff",
        bordercolor=p.primary_dark,
        relief="flat",
        padding=(6, 6),
    )
    style.map("Treeview.Heading", background=[("active", p.primary)])

    style.configure(
        "Vertical.TScrollbar",
        background=p.border,
        troughcolor=p.bg,
        bordercolor=p.bg,
        arrowcolor=p.text_muted,
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=p.border,
        troughcolor=p.bg,
        bordercolor=p.bg,
        arrowcolor=p.text_muted,
    )

    style.configure("Error.TLabel", background=p.bg, foreground=p.danger)
    style.configure("Muted.TLabel", background=p.bg, foreground=p.text_muted)
    style.configure("Surface.TLabel", background=p.surface, foreground=p.text)

    # --- Barra lateral: panel oscuro con identidad propia ------------------
    style.configure("Sidebar.TFrame", background=p.primary_dark)
    style.configure(
        "SidebarTitle.TLabel",
        background=p.primary_dark,
        foreground="#ffffff",
        font=("TkDefaultFont", 13, "bold"),
    )
    style.configure(
        "SidebarSection.TLabel",
        background=p.primary_dark,
        foreground=p.text_on_dark_muted,
        font=("TkDefaultFont", 9, "bold"),
    )
    style.configure(
        "SidebarMuted.TLabel", background=p.primary_dark, foreground=p.text_on_dark_muted
    )
    style.configure("Sidebar.TSeparator", background=p.sidebar_separator)

    style.configure(
        "Sidebar.TButton",
        background=p.primary_dark,
        foreground=p.text_on_dark,
        bordercolor=p.primary_dark,
        lightcolor=p.primary_dark,
        darkcolor=p.primary_dark,
        anchor="w",
        padding=(10, 7),
    )
    style.map(
        "Sidebar.TButton",
        background=[("active", p.primary), ("pressed", p.primary)],
        bordercolor=[("active", p.primary), ("pressed", p.primary)],
        foreground=[("active", "#ffffff")],
    )

    # --- Tarjetas (Inicio) y encabezados de página --------------------------
    style.configure(
        "Card.TFrame", background=p.surface, bordercolor=p.border, relief="solid", borderwidth=1
    )
    style.configure(
        "CardValue.TLabel",
        background=p.surface,
        foreground=p.primary,
        font=("TkDefaultFont", 22, "bold"),
    )
    style.configure("CardCaption.TLabel", background=p.surface, foreground=p.text_muted)

    style.configure(
        "PageHeading.TLabel", background=p.bg, foreground=p.heading_text, font=_HEADING_FONT
    )
