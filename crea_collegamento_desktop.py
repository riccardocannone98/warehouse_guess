"""Crea sul desktop un collegamento che avvia Warehouse Guess.

Da eseguire una sola volta (doppio clic, oppure ``python crea_collegamento_desktop.py``).
Se sposti la cartella del progetto, eseguilo di nuovo.
"""
from __future__ import annotations

import os
import platform
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "Warehouse Guess"
ICON_ICO = ROOT / "app" / "static" / "icon.ico"
ICON_PNG = ROOT / "app" / "static" / "icon.png"


def windows_shortcut() -> Path:
    # Il percorso del desktop si chiede a Windows: con OneDrive non è ~/Desktop.
    script = r"""
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop ($env:WG_NAME + '.lnk')
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($link)
$s.TargetPath = $env:WG_TARGET
$s.WorkingDirectory = $env:WG_ROOT
$s.IconLocation = $env:WG_ICON
$s.WindowStyle = 7
$s.Description = 'Disponibilita sneaker per taglia'
$s.Save()
Write-Output $link
"""
    env = {
        **os.environ,
        "WG_NAME": NAME,
        "WG_TARGET": str(ROOT / "avvia.bat"),
        "WG_ROOT": str(ROOT),
        "WG_ICON": str(ICON_ICO),
    }
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        env=env, capture_output=True, text=True, check=True,
    )
    return Path(result.stdout.strip())


def desktop_dir() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, check=True)
        if out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        pass
    return Path.home() / "Desktop"


def make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def mac_shortcut() -> Path:
    launcher = ROOT / "avvia.command"
    make_executable(launcher)
    link = Path.home() / "Desktop" / f"{NAME}.command"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(launcher)
    return link


def linux_shortcut() -> Path:
    launcher = ROOT / "avvia.command"
    make_executable(launcher)
    desktop = desktop_dir()
    desktop.mkdir(parents=True, exist_ok=True)
    link = desktop / "warehouse-guess.desktop"
    link.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={NAME}\n"
        "Comment=Disponibilità sneaker per taglia\n"
        f'Exec="{launcher}"\n'
        f"Path={ROOT}\n"
        f"Icon={ICON_PNG}\n"
        "Terminal=true\n",
        encoding="utf-8",
    )
    make_executable(link)
    # GNOME chiede di "consentire l'avvio" ai lanciatori non marcati come fidati.
    subprocess.run(["gio", "set", str(link), "metadata::trusted", "true"], capture_output=True)
    return link


if __name__ == "__main__":
    system = platform.system()
    try:
        if system == "Windows":
            created = windows_shortcut()
        elif system == "Darwin":
            created = mac_shortcut()
        else:
            created = linux_shortcut()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Non sono riuscito a creare il collegamento: {exc}")
    else:
        print(f"Collegamento creato: {created}")
        print("Fai doppio clic sull'icona per avviare l'app.")
    if system == "Windows":
        input("Premi Invio per chiudere.")
