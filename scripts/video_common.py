"""Utilidades compartidas por los 5 scripts "director" de grabacion
(video1_turnos.py ... video5 es solo instrucciones, no tiene script --
ver GUIA_GRABACION). Cada script abre la app real contra video_demo.db
(generada con generar_datos_demo.py) y va marcando cada "beat" del guion
por consola mientras espera lo que dura ese beat en el video final, para
que quien esta grabando la pantalla sepa que viene a continuacion y el
ritmo salga parecido al de la version final ya montada.

No hace nada con el propio grabador de pantalla -- eso lo abre y lo para
la persona que graba (Xbox Game Bar / OBS / lo que prefiera), fuera de
este script.
"""
from __future__ import annotations

import ctypes
import sys
import time
import tkinter as tk
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VIDEO_DB_PATH = Path(__file__).resolve().parent / "video_demo.db"
HERO_EMAIL = "laura.jimenez@empresa-ficticia.example"

sys.path.insert(0, str(REPO_ROOT))

if not VIDEO_DB_PATH.exists():
    raise SystemExit(
        f"No existe {VIDEO_DB_PATH.name} -- genera la BD primero con:\n"
        f'  py scripts/generar_datos_demo.py --db-path "{VIDEO_DB_PATH}"'
    )

user32 = ctypes.windll.user32
GA_ROOT = 2
SW_RESTORE = 9


def force_foreground(tk_window: tk.Tk | tk.Toplevel) -> None:
    hwnd = user32.GetAncestor(tk_window.winfo_id(), GA_ROOT)
    for attempt in range(8):
        if user32.GetForegroundWindow() == hwnd:
            return
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 0x0002, 0)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        tk_window.lift()
        tk_window.attributes("-topmost", True)
        tk_window.update()
        tk_window.attributes("-topmost", False)
        tk_window.update()
        time.sleep(0.15 * (attempt + 1))


def wait_for_recording(video_title: str) -> None:
    print("=" * 70)
    print(f"  {video_title}")
    print("=" * 70)
    print()
    print("1. Abre tu grabador de pantalla (Xbox Game Bar: Win+Alt+R, o OBS)")
    print("2. Encuadra la ventana de ContaApp RH que va a aparecer")
    print("3. Dale a grabar")
    input("4. Pulsa Enter aqui EN CUANTO la grabacion este en marcha...\n")
    print("Arrancando la app en 2 segundos...")
    time.sleep(2)


def beat(seconds: float, message: str, window: tk.Misc | None = None) -> None:
    # Trocea la espera en fragmentos de 100ms y llama a update() entre
    # medias en vez de un unico time.sleep() largo -- si no, Tkinter no
    # procesa ningun evento durante todo el beat y Windows puede marcar la
    # ventana como "(no responde)" pasados unos segundos, justo mientras se
    # esta grabando.
    print(f"  [{seconds:>4.1f}s] {message}")
    if window is None:
        time.sleep(seconds)
        return
    remaining = seconds
    step = 0.1
    while remaining > 0:
        window.update()
        time.sleep(min(step, remaining))
        remaining -= step


def done(message: str = "Beat final -- deja de grabar cuando quieras.") -> None:
    print()
    print(message)
    print("=" * 70)
