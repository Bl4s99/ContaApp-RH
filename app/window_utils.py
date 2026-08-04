from __future__ import annotations

import tkinter as tk


def center_window(window: tk.Tk | tk.Toplevel, parent: tk.Misc | None = None) -> None:
    """Centra `window` sobre `parent` (o sobre la pantalla si no hay padre),
    en vez de dejar que el gestor de ventanas la abra arriba a la izquierda.
    Solo reposiciona -- no toca el tamaño ya calculado por sus widgets."""
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()

    if parent is not None:
        parent_top = parent.winfo_toplevel()
        # winfo_x()/winfo_y(), not winfo_rootx()/winfo_rooty(): geometry("+x+y")
        # positions in the winfo_x/y coordinate system, which already excludes
        # the OS title bar/border -- winfo_rootx/rooty includes it, and mixing
        # the two introduces a fixed offset (title-bar-sized) toward one corner.
        origin_x = parent_top.winfo_x()
        origin_y = parent_top.winfo_y()
        origin_width = parent_top.winfo_width()
        origin_height = parent_top.winfo_height()
    else:
        origin_x, origin_y = 0, 0
        origin_width, origin_height = screen_width, screen_height

    x = origin_x + (origin_width - width) // 2
    y = origin_y + (origin_height - height) // 2

    # No dejar la ventana fuera de la pantalla visible (p. ej. un padre
    # cerca del borde con una ventana hija más ancha que él).
    x = max(0, min(x, screen_width - width))
    y = max(0, min(y, screen_height - height))

    window.geometry(f"+{x}+{y}")
