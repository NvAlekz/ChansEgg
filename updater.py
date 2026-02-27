import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests
import tkinter as tk
from tkinter import messagebox


@dataclass
class UpdaterConfig:
    enabled: bool = True
    check_on_startup: bool = True
    github_user: str = ""
    github_repo: str = ""
    expected_asset_name: str = "ChansEgg-Setup.exe"
    request_timeout_sec: int = 6
    download_timeout_sec: int = 20


def _parse_legacy_repo_fields(update_json_url: str) -> tuple[str, str]:
    url = (update_json_url or "").strip()
    if not url:
        return "", ""
    patterns = [
        r"^https?://api\.github\.com/repos/([^/]+)/([^/]+)/releases/latest/?$",
        r"^https?://github\.com/([^/]+)/([^/]+)/releases/latest/?$",
    ]
    for pat in patterns:
        m = re.match(pat, url, flags=re.IGNORECASE)
        if m:
            return m.group(1), m.group(2)
    return "", ""


def load_updater_config(path: str) -> UpdaterConfig:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = json.load(f)

        user = str(raw.get("github_user", "")).strip()
        repo = str(raw.get("github_repo", "")).strip()
        expected = str(raw.get("expected_asset_name", "ChansEgg-Setup.exe")).strip() or "ChansEgg-Setup.exe"

        # Backward compatibility with old schema (update_json_url).
        legacy_url = str(raw.get("update_json_url", "")).strip()
        if (not user or not repo) and legacy_url:
            legacy_user, legacy_repo = _parse_legacy_repo_fields(legacy_url)
            user = user or legacy_user
            repo = repo or legacy_repo

        return UpdaterConfig(
            enabled=bool(raw.get("enabled", True)),
            check_on_startup=bool(raw.get("check_on_startup", True)),
            github_user=user,
            github_repo=repo,
            expected_asset_name=expected,
            request_timeout_sec=max(3, int(raw.get("request_timeout_sec", 6))),
            download_timeout_sec=max(5, int(raw.get("download_timeout_sec", 20))),
        )
    except Exception as exc:
        print(f"[Updater] invalid updater config at {path}: {exc}")
        return UpdaterConfig()


def save_updater_config(path: str, cfg: UpdaterConfig) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "enabled": cfg.enabled,
                "check_on_startup": cfg.check_on_startup,
                "github_user": cfg.github_user,
                "github_repo": cfg.github_repo,
                "expected_asset_name": cfg.expected_asset_name,
                "request_timeout_sec": cfg.request_timeout_sec,
                "download_timeout_sec": cfg.download_timeout_sec,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def ensure_updater_config(path: str) -> UpdaterConfig:
    if not os.path.exists(path):
        cfg = UpdaterConfig()
        try:
            save_updater_config(path, cfg)
        except Exception as exc:
            print(f"[Updater] cannot create updater config at {path}: {exc}")
        return cfg

    cfg = load_updater_config(path)
    # Always normalize to new GitHub schema.
    try:
        save_updater_config(path, cfg)
    except Exception as exc:
        print(f"[Updater] cannot normalize updater config at {path}: {exc}")
    return cfg


def normalize_version(v: str) -> List[int]:
    s = (v or "").strip().lower().lstrip("v")
    if not s:
        return [0]
    parts = []
    for token in s.split("."):
        m = re.match(r"(\d+)", token.strip())
        if m:
            parts.append(int(m.group(1)))
        else:
            parts.append(0)
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return parts or [0]


def is_newer(v_new: str, v_cur: str) -> bool:
    a = normalize_version(v_new)
    b = normalize_version(v_cur)
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return a > b


def _is_https_url(url: str) -> bool:
    try:
        p = urlparse(url.strip())
        return p.scheme == "https" and bool(p.netloc)
    except Exception:
        return False


def _is_windows_exe_url(url: str) -> bool:
    try:
        p = urlparse(url.strip())
        return p.path.lower().endswith(".exe")
    except Exception:
        return False


def build_github_latest_api_url(user: str, repo: str) -> str:
    u = (user or "").strip().strip("/")
    r = (repo or "").strip().strip("/")
    if not u or not r:
        raise ValueError("github_user/github_repo are required")
    if not re.match(r"^[A-Za-z0-9_.-]+$", u):
        raise ValueError("invalid github_user")
    if not re.match(r"^[A-Za-z0-9_.-]+$", r):
        raise ValueError("invalid github_repo")
    return f"https://api.github.com/repos/{u}/{r}/releases/latest"


def fetch_latest_release_from_github(user: str, repo: str, timeout: int) -> Dict[str, object]:
    api_url = build_github_latest_api_url(user, repo)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ChansEgg-Updater",
    }
    r = requests.get(api_url, timeout=timeout, headers=headers)
    if r.status_code == 404:
        raise RuntimeError("GitHub repo/release not found")
    if r.status_code == 403:
        raise RuntimeError("GitHub API forbidden/rate-limited")
    r.raise_for_status()
    payload = r.json()
    assets = payload.get("assets") if isinstance(payload, dict) else []
    if not isinstance(assets, list):
        assets = []
    return {
        "tag_name": str(payload.get("tag_name", "")).strip(),
        "body": str(payload.get("body", "")).strip(),
        "assets": assets,
        "prerelease": bool(payload.get("prerelease", False)),
    }


def pick_installer_asset(assets: List[dict], expected_name: str = "ChansEgg-Setup.exe") -> Optional[str]:
    expected = (expected_name or "").strip().lower()
    if not assets:
        return None

    def asset_url(asset: dict) -> str:
        return str((asset or {}).get("browser_download_url", "")).strip()

    # 1) exact match by name
    if expected:
        for asset in assets:
            name = str((asset or {}).get("name", "")).strip().lower()
            url = asset_url(asset)
            if name == expected and _is_https_url(url):
                if not sys.platform.startswith("win") or _is_windows_exe_url(url):
                    return url

    # 2) fallback first .exe
    for asset in assets:
        name = str((asset or {}).get("name", "")).strip().lower()
        url = asset_url(asset)
        if name.endswith(".exe") and _is_https_url(url):
            return url

    return None


def verify_sha256(path: str, expected: str) -> bool:
    if not expected:
        return True
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower() == expected.lower()


def download_installer(url: str, timeout: int) -> str:
    out_path = os.path.join(tempfile.gettempdir(), "ChansEgg-Setup.exe")
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
    return out_path


def run_installer_and_exit(root: tk.Tk, installer_path: str) -> None:
    if not sys.platform.startswith("win"):
        messagebox.showwarning("Actualizacion", "La instalacion automatica esta disponible solo en Windows.")
        return
    try:
        subprocess.Popen([installer_path], shell=False)
    finally:
        root.destroy()


def show_update_dialog(
    root: tk.Tk,
    latest: str,
    installer_url: str,
    notes: str,
    on_accept: Optional[Callable[[], None]] = None,
    sha256: str = "",
    request_timeout: int = 20,
) -> None:
    if not root.winfo_exists():
        return
    if getattr(root, "_chansegg_update_dialog_open", False):
        return
    root._chansegg_update_dialog_open = True

    win = tk.Toplevel(root)
    win.title("Actualizacion disponible")
    win.configure(bg="#151A21")
    win.resizable(False, False)
    win.transient(root)
    win.grab_set()

    def on_close():
        root._chansegg_update_dialog_open = False
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    root.update_idletasks()
    w, h = 500, 245
    if root.winfo_viewable():
        rx, ry = root.winfo_rootx(), root.winfo_rooty()
        rw, rh = root.winfo_width(), root.winfo_height()
        x = rx + max(0, (rw - w) // 2)
        y = ry + max(0, (rh - h) // 2)
    else:
        x = max(0, (root.winfo_screenwidth() - w) // 2)
        y = max(0, (root.winfo_screenheight() - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")

    title = tk.Label(
        win,
        text=f"Hay una nueva actualizacion disponible (v{latest})",
        bg="#151A21",
        fg="#E6E6E6",
        font=("Segoe UI", 11, "bold"),
        wraplength=470,
        justify="left",
    )
    title.pack(padx=16, pady=(16, 10), anchor="w")

    if notes:
        body = tk.Label(
            win,
            text=notes,
            bg="#151A21",
            fg="#9AA4B2",
            font=("Segoe UI", 9),
            wraplength=470,
            justify="left",
        )
        body.pack(padx=16, pady=(0, 10), anchor="w")

    status = tk.Label(win, text="", bg="#151A21", fg="#9AA4B2", font=("Segoe UI", 9))
    status.pack(padx=16, pady=(0, 6), anchor="w")

    btns = tk.Frame(win, bg="#151A21")
    btns.pack(padx=16, pady=14, fill="x")

    def later() -> None:
        on_close()

    def on_error(msg: str) -> None:
        status.config(text="")
        messagebox.showerror("Error de actualizacion", f"No se pudo descargar la actualizacion.\n\n{msg}")
        btn_update.config(state="normal")
        btn_later.config(state="normal")

    def update_now() -> None:
        if on_accept:
            try:
                on_accept()
            except Exception as exc:
                print(f"[Updater] on_accept failed: {exc}")
        btn_update.config(state="disabled")
        btn_later.config(state="disabled")
        status.config(text="Descargando instalador...")

        def dl_worker() -> None:
            try:
                installer_path = download_installer(installer_url, timeout=request_timeout)
                if sha256 and not verify_sha256(installer_path, sha256):
                    raise RuntimeError("Checksum SHA256 no coincide con la version publicada.")
                root.after(0, lambda: run_installer_and_exit(root, installer_path))
            except Exception as exc:
                root.after(0, lambda: on_error(str(exc)))

        threading.Thread(target=dl_worker, daemon=True).start()

    btn_later = tk.Button(
        btns,
        text="Mas tarde",
        command=later,
        bg="#0F141B",
        fg="#E6E6E6",
        activebackground="#0F141B",
        activeforeground="#E6E6E6",
        relief="flat",
        padx=14,
        pady=8,
    )
    btn_later.pack(side="right", padx=(8, 0))

    btn_update = tk.Button(
        btns,
        text="Actualizar",
        command=update_now,
        bg="#7A3A8E",
        fg="#FFFFFF",
        activebackground="#7A3A8E",
        activeforeground="#FFFFFF",
        relief="flat",
        padx=14,
        pady=8,
    )
    btn_update.pack(side="right")


def check_for_updates_async(root: tk.Tk, current_version: str, config_path: str) -> None:
    cfg = ensure_updater_config(config_path)
    if not cfg.enabled or not cfg.check_on_startup:
        return
    if not cfg.github_user or not cfg.github_repo:
        return

    def worker() -> None:
        try:
            data = fetch_latest_release_from_github(cfg.github_user, cfg.github_repo, timeout=cfg.request_timeout_sec)
            # /releases/latest should already be stable, but keep explicit guard.
            if bool(data.get("prerelease", False)):
                print("[Updater] latest release is prerelease, skipping")
                return
            latest_tag = str(data.get("tag_name", "")).strip()
            latest = latest_tag.lstrip("vV")
            if not latest:
                print("[Updater] invalid latest tag_name from GitHub release")
                return
            installer_url = pick_installer_asset(
                assets=data.get("assets", []),  # type: ignore[arg-type]
                expected_name=cfg.expected_asset_name,
            )
            if not installer_url:
                print("[Updater] no .exe installer asset found in latest GitHub release")
                return
            notes = str(data.get("body", "")).strip()

            if is_newer(latest, current_version):
                root.after(
                    0,
                    lambda: show_update_dialog(
                        root=root,
                        latest=latest,
                        installer_url=installer_url,
                        notes=notes,
                        sha256="",
                        request_timeout=cfg.download_timeout_sec,
                    ),
                )
        except Exception as exc:
            print(f"[Updater] check skipped: {exc}")

    threading.Thread(target=worker, daemon=True).start()

