"""Captura screenshots reales de ContaApp RH para la demo interactiva,
navegando en proceso (sin simular clics) contra una BD ya sembrada por
generar_datos_demo.py.

Uso:
    py scripts/capturar_demo_screenshots.py --db-path <ruta de la BD sembrada> --output-dir <carpeta>

Tecnica de captura: PIL.ImageGrab sobre un bbox de pantalla fijo (el panel
de contenido, a la derecha de la barra lateral). Como es una captura de
pantalla real, la ventana tiene que estar realmente en primer plano --
se fuerza con SetForegroundWindow + el truco del Alt (necesario porque el
proceso que lanza el script no es ya el de primer plano) y se verifica
antes de cada captura, abortando en vez de guardar la ventana equivocada
si algo mas tapa la pantalla en ese instante.
"""
from __future__ import annotations

import argparse
import ctypes
import sqlite3
import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageGrab  # noqa: E402

from app.backup import BackupRepository  # noqa: E402
from app.database import get_connection  # noqa: E402
from app.login import LoginWindow  # noqa: E402
from app.repository import Repositories  # noqa: E402
from app.ui import MainWindow  # noqa: E402

CANONICAL_SIZE = (990, 680)
HERO_EMAIL = "laura.jimenez@empresa-ficticia.example"
CALENDAR_DEPARTMENTS = ["Ventas", "Recursos Humanos"]

user32 = ctypes.windll.user32
GA_ROOT = 2
SW_RESTORE = 9


def force_foreground(tk_window: tk.Tk | tk.Toplevel) -> None:
    hwnd = user32.GetAncestor(tk_window.winfo_id(), GA_ROOT)
    for attempt in range(8):
        if user32.GetForegroundWindow() == hwnd:
            return
        user32.keybd_event(0x12, 0, 0, 0)  # Alt down
        user32.keybd_event(0x12, 0, 0x0002, 0)  # Alt up
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        tk_window.lift()
        tk_window.attributes("-topmost", True)
        tk_window.update()
        tk_window.attributes("-topmost", False)
        tk_window.update()
        time.sleep(0.15 * (attempt + 1))


def assert_foreground(tk_window: tk.Tk | tk.Toplevel) -> None:
    our_hwnd = user32.GetAncestor(tk_window.winfo_id(), GA_ROOT)
    fg_hwnd = user32.GetForegroundWindow()
    if fg_hwnd != our_hwnd:
        raise RuntimeError(
            f"la ventana no esta en primer plano (foreground={fg_hwnd}, nuestra={our_hwnd}) "
            "-- abortando en vez de capturar la ventana equivocada"
        )


def save_shot(bbox: tuple[int, int, int, int], out_path: Path) -> None:
    img = ImageGrab.grab(bbox=bbox)
    if img.size != CANONICAL_SIZE:
        img = img.resize(CANONICAL_SIZE, Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Capturas de UI real (tablas, texto) comprimen mal en RGB de 24 bits --
    # reducir a paleta adaptativa de 256 colores no pierde calidad visible
    # aqui y deja los PNG en ~1/3 del tamano (confirmado visualmente antes
    # de aplicarlo en el pipeline).
    img.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=256).save(out_path, optimize=True)
    print(f"  {out_path.name}: {img.size[0]}x{img.size[1]} ({out_path.stat().st_size // 1024} KB)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = args.db_path.resolve()
    if not db_path.exists():
        raise SystemExit(f"No existe la BD sembrada: {db_path} -- ejecuta antes generar_datos_demo.py")
    out_dir = args.output_dir.resolve()

    conn = get_connection(db_path)
    assert isinstance(conn, sqlite3.Connection), (
        "la conexion resultante no es sqlite3 -- revisa si existe un db_config.json"
    )
    try:
        repos = Repositories.create(conn)
        admin_user = repos.users.list_all()[0]
        hero = next(e for e in repos.employees.list_all() if e.email == HERO_EMAIL)
        departments_by_name = {d.name: d for d in repos.departments.list_all()}

        # ---------------- Login (raiz Tk de vida corta, antes de MainWindow) ----------------
        print("Login...")
        login = LoginWindow(repos)
        login.update_idletasks()
        force_foreground(login)
        assert_foreground(login)
        login_bbox = (
            login.winfo_rootx(), login.winfo_rooty(),
            login.winfo_rootx() + login.winfo_width(), login.winfo_rooty() + login.winfo_height(),
        )
        save_shot(login_bbox, out_dir / "login.png")
        login.destroy()

        # ---------------- MainWindow: unica raiz Tk para el resto ----------------
        backups = BackupRepository(conn, db_path)
        window = MainWindow(repos, admin_user, backups)
        window.update_idletasks()
        force_foreground(window)
        time.sleep(0.3)
        window.update()
        assert_foreground(window)

        content = window.nametowidget(window._main_paned.panes()[1])  # type: ignore[no-untyped-call]
        x = window.winfo_rootx() + content.winfo_x()
        y = window.winfo_rooty() + content.winfo_y()
        w = content.winfo_width()
        h = content.winfo_height()
        bbox = (x, y, x + w, y + h)
        print(f"bbox de contenido: {bbox}")

        def capture(name: str) -> None:
            window.update_idletasks()
            window.update()
            force_foreground(window)
            assert_foreground(window)
            save_shot(bbox, out_dir / f"{name}.png")

        print("Inicio...")
        window._show_page("inicio")
        capture("inicio")

        print("Alertas...")
        window._show_page("alertas")
        capture("alertas")

        print("Lista de empleados...")
        window._show_page("empleados")
        window._employee_page.ficha.show_employee(None)
        capture("empleados")

        print("Ficha...")
        window._employee_page.ficha.show_employee(hero)
        ficha_canvas = window._employee_page.ficha._scroll.canvas
        for i, fraction in enumerate([0.0, 0.5, 1.0], start=1):
            ficha_canvas.yview_moveto(fraction)
            window.update_idletasks()
            capture("ficha" if i == 1 else f"ficha_{i}")
        ficha_canvas.yview_moveto(0.0)

        print("Nominas...")
        window._show_page("nominas")
        window._payroll_page.tree.selection_set(str(hero.id))
        window._payroll_page._handle_selection_changed()
        capture("nominas")

        print("Coste de personal...")
        window._show_page("coste")
        capture("coste")

        print("Candidatos...")
        window._show_page("candidatos")
        capture("candidatos")

        print("Organigrama...")
        window._show_page("organigrama")
        capture("organigrama")

        print("Calendario...")
        for i, dept_name in enumerate(CALENDAR_DEPARTMENTS, start=1):
            window._calendar_page.show_department(departments_by_name[dept_name])
            window._show_page("calendario")
            capture(f"calendario_{i}")

        print("Fichajes...")
        window._show_page("fichajes")
        names = list(window._time_clock_page.employee_combo["values"])
        window._time_clock_page.employee_combo.current(names.index(hero.full_name))
        window._time_clock_page._handle_employee_changed()
        capture("fichajes")

        print("Solicitudes de ausencia...")
        window._show_page("solicitudes")
        capture("solicitudes")

        print("Historial de versiones...")
        window._show_page("versiones")
        capture("versiones")

        window.destroy()
        print(f"\nCapturas guardadas en: {out_dir}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
