#!/usr/bin/env python3
"""Install/restore the reviewed Regis theme and SDDM PAM configuration."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

try:
    from . import install_sddm_pam as pam
except ImportError:
    import install_sddm_pam as pam

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path('/etc/sddm.conf')
CONFIG_BACKUP = Path('/var/lib/eutherfpscan/sddm.conf.backup')
CONFIG_SHA = '3a7e157f5fac4cc9064376474915023a33bb5e935e8c67513f2b85cf51b31e92'
THEME = Path('/usr/share/sddm/themes/regis')
FILES = ('Main.qml', 'LoginView.qml', 'RegisButton.qml', 'RegisCombo.qml',
         'RegisField.qml', 'regis.svg', 'metadata.desktop', 'theme.conf')
CONFIG_BLOCK = b'[Theme]\nCurrent=regis\nThemeDir=/usr/share/sddm/themes\n'


def config_updated(original):
    if hashlib.sha256(original).hexdigest() != CONFIG_SHA:
        raise RuntimeError('sddm.conf differs from the reviewed original')
    return original + CONFIG_BLOCK


def backup(path, content):
    if path.is_symlink():
        raise RuntimeError(f'Refusing symlink backup: {path}')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with path.open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError:
        if path.read_bytes() != content or path.stat().st_uid != 0:
            raise RuntimeError(f'Backup differs: {path}')


def run_pam(option):
    subprocess.run([sys.executable, str(ROOT / 'tools/install_sddm_pam.py'), option], check=True)


def theme_files():
    result = {name: (ROOT / 'sddm/regis' / name).read_bytes() for name in FILES}
    result['theme.conf'] = b'[General]\nfingerprintEnabled=true\n'
    return result


def install_theme(files):
    if THEME.is_symlink():
        raise RuntimeError('Refusing a symlink theme directory')
    if THEME.exists():
        for name, content in files.items():
            path = THEME / name
            if path.is_symlink() or path.read_bytes() != content or path.stat().st_uid != 0:
                raise RuntimeError(f'Installed theme differs: {name}')
        return
    staging = Path(tempfile.mkdtemp(prefix='.regis-', dir=THEME.parent))
    try:
        staging.chmod(0o755)
        for name, content in files.items():
            path = staging / name
            path.write_bytes(content)
            path.chmod(0o644)
        os.rename(staging, THEME)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def restore():
    original = CONFIG_BACKUP.read_bytes()
    installed = config_updated(original)
    current = CONFIG.read_bytes()
    pam_original = pam.BACKUP.read_bytes()
    pam_installed = pam.updated(pam_original)
    if current not in (original, installed) or pam.TARGET.read_bytes() not in (pam_original, pam_installed):
        raise RuntimeError('Configuration changed since installation; inspect before restoring')
    if current == installed:
        pam.replace_file(CONFIG, installed, original)
    run_pam('--remove')
    print('Original SDDM configuration and PAM restored. Inactive theme files retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--apply', action='store_true')
    actions.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    if (args.apply or args.remove) and os.geteuid() != 0:
        raise RuntimeError('Run with sudo to apply or remove')
    if args.remove:
        restore()
        return
    current = CONFIG.read_bytes()
    original = current[:-len(CONFIG_BLOCK)] if current.endswith(CONFIG_BLOCK) else current
    replacement = config_updated(original)
    current_pam = pam.TARGET.read_bytes()
    original_pam = current_pam.replace(pam.BLOCK.encode(), b'', 1)
    expected_pam = pam.updated(original_pam)
    if current_pam not in (original_pam, expected_pam):
        raise RuntimeError('Unexpected PAM configuration')
    if hashlib.sha256(Path('/etc/pam.d/common-auth').read_bytes()).hexdigest() != pam.COMMON_SHA:
        raise RuntimeError('common-auth changed')
    files = theme_files()
    print('Install root-owned Regis theme; enable SDDM fingerprint PAM; select Regis.')
    print('Backups: ' + str(CONFIG_BACKUP) + ' and ' + str(pam.BACKUP))
    print('The running SDDM service and desktop session will not be restarted.')
    if not args.apply:
        print('Preview only. Apply: sudo python3 tools/install_sddm.py --apply')
        return
    backup(CONFIG_BACKUP, original)
    backup(pam.BACKUP, original_pam)
    install_theme(files)
    try:
        run_pam('--apply')
        if current != replacement:
            pam.replace_file(CONFIG, current, replacement)
        if CONFIG.read_bytes() != replacement or pam.TARGET.read_bytes() != expected_pam:
            raise RuntimeError('Read-back verification failed')
    except Exception:
        # Restore the pre-run state when it is still one of our known states.
        if CONFIG.read_bytes() == replacement and current != replacement:
            pam.replace_file(CONFIG, replacement, current)
        if pam.TARGET.read_bytes() == expected_pam and current_pam != expected_pam:
            pam.replace_file(pam.TARGET, expected_pam, current_pam)
        raise
    print('REGIS_INSTALL_OK: theme and fingerprint login configured for the next SDDM start (reboot when ready).')
    print('Restore: sudo python3 ' + str(ROOT / 'tools/install_sddm.py') + ' --remove')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
