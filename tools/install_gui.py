#!/usr/bin/env python3
"""Install System Regis IV for the current desktop user; no root required."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.geteuid() == 0:
        raise SystemExit('Kör utan sudo: python3 tools/install_gui.py')
    destination = Path.home() / '.local/share/system-regis-iv'
    destination.mkdir(mode=0o755, parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'regis', destination / 'regis', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (destination / 'tools').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'tools/regis.py', destination / 'tools/regis.py')
    applications = Path.home() / '.local/share/applications'
    applications.mkdir(parents=True, exist_ok=True)
    command_path = str(destination / 'tools/regis.py').replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    app_id = 'se.euther.SystemRegisIV'
    icons = Path.home() / '.local/share/icons/hicolor/scalable/apps'
    icons.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'regis/assets/regis.svg', icons / (app_id + '.svg'))
    desktop = applications / (app_id + '.desktop')
    desktop.write_text('[Desktop Entry]\nType=Application\nName=System Regis IV\n'
                       'Comment=Hantera datorns fingeravtrycksregister\n'
                       f'Exec=/usr/bin/python3 "{command_path}"\n'
                       f'Icon={app_id}\nStartupWMClass={app_id}\n'
                       'Terminal=false\nCategories=Settings;System;GTK;\n'
                       'Keywords=fingerprint;fingeravtryck;regis;sigill;\nStartupNotify=true\n')
    desktop.chmod(0o644)
    legacy = applications / 'system-regis-iv.desktop'
    if legacy.exists() and f'Exec=/usr/bin/python3 "{command_path}"' in legacy.read_text():
        legacy.unlink()
    if shutil.which('gtk-update-icon-cache'):
        subprocess.run(['gtk-update-icon-cache', '--force', '--ignore-theme-index',
                        str(icons.parents[1])], check=True)
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(applications)], check=True)
    print(f'Installerat: {destination}')
    print('Startmeny: System Regis IV')


if __name__ == '__main__':
    main()
