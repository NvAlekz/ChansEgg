import os
import sys
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageTk

from updater import check_for_updates_async


def resource_path(rel: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)


def _first_existing(*paths: str) -> str:
    for p in paths:
        if p and os.path.exists(p):
            return p
    return ""


class Splash(tk.Toplevel):
    def __init__(self, master: tk.Tk, image_path: str = "", ms: int = 1200):
        super().__init__(master)
        self.overrideredirect(True)
        self.configure(bg="#0F141B")
        self._tkimg = None

        rendered_image = False
        if image_path and os.path.exists(image_path):
            try:
                img = Image.open(image_path).convert("RGBA")
                img = img.resize((420, 220), Image.LANCZOS)
                self._tkimg = ImageTk.PhotoImage(img)
                lbl = tk.Label(self, image=self._tkimg, bg="#0F141B", bd=0, highlightthickness=0)
                lbl.pack()
                rendered_image = True
            except Exception as exc:
                print(f"[Splash] failed loading {image_path}: {exc}")
        if not rendered_image:
            body = tk.Frame(self, bg="#0F141B", width=420, height=220)
            body.pack(fill="both", expand=True)
            body.pack_propagate(False)
            title = tk.Label(body, text="ChansEgg", bg="#0F141B", fg="#E6E6E6", font=("Segoe UI", 22, "bold"))
            title.pack(expand=True)

        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.after(ms, self.destroy)


def run_app(
    app_factory: Callable[[], tk.Tk],
    ensure_assets: Optional[Callable[[], None]] = None,
    app_version: str = "1.0.0",
    updater_config_path: str = "",
    splash_duration_ms: int = 1200,
    runtime_assets_dir: str = "",
    user_assets_dir: str = "",
    enable_updater: bool = True,
) -> None:
    if ensure_assets:
        ensure_assets()

    runtime_splash = str(Path(runtime_assets_dir) / "splash.png") if runtime_assets_dir else ""
    bundled_splash = resource_path(os.path.join("assets", "splash.png"))
    user_splash = str(Path(user_assets_dir) / "splash.png") if user_assets_dir else ""
    splash_path = _first_existing(runtime_splash, bundled_splash, user_splash)

    boot_root = tk.Tk()
    boot_root.withdraw()
    Splash(boot_root, splash_path, ms=splash_duration_ms)
    boot_root.after(splash_duration_ms + 60, boot_root.quit)
    boot_root.mainloop()
    if boot_root.winfo_exists():
        boot_root.destroy()

    app = app_factory()
    if enable_updater and updater_config_path:
        app.after(1500, lambda: check_for_updates_async(app, app_version, updater_config_path))
    app.mainloop()
