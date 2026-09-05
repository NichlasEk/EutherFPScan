#!/usr/bin/env python3
"""Preview/apply/revert the reviewed sudo-only PAM change on this Debian host."""
import argparse
import difflib
import hashlib
import os
from pathlib import Path
import stat
import tempfile

TARGET = Path('/etc/pam.d/sudo')
BACKUP = Path('/var/lib/eutherfpscan/pam-sudo.backup')
ORIGINAL_SHA = '5355ef86ec2f1103fbb9db4f441ec15abdc31383d85774b77849b1fb3bed302e'
COMMON_SHA = 'b787b01c7e71c658fa9acb84cbe153f71786cf380af4b01ae9135210cdc0154d'
BLOCK = '# EutherFPScan: fingerprint first; password fallback below.\nauth sufficient pam_fprintd.so max-tries=1 timeout=15\n\n'


def updated(original):
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA:
        raise RuntimeError('sudo PAM differs from the reviewed Debian configuration; inspect before changing')
    return original.replace(b'@include common-auth\n', BLOCK.encode() + b'@include common-auth\n', 1)


def replace_file(path, expected, content):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        raise RuntimeError('Expected root-owned regular PAM file')
    fd, name = tempfile.mkstemp(prefix='.euther-sudo-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), stat.S_IMODE(info.st_mode))
            os.fchown(output.fileno(), info.st_uid, info.st_gid)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if path.read_bytes() != expected:
            raise RuntimeError('PAM configuration changed during preparation')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--apply', action='store_true')
    group.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    current = TARGET.read_bytes()
    if args.remove:
        original = BACKUP.read_bytes()
        expected = updated(original)
        if current == original:
            print('Fingerprint sudo is already removed.')
            return
        if current != expected:
            raise RuntimeError('PAM file changed since installation; refusing to overwrite it')
        replacement = original
    else:
        if BLOCK.encode() in current:
            original = current.replace(BLOCK.encode(), b'', 1)
            if updated(original) != current:
                raise RuntimeError('Unexpected PAM content')
            print('Fingerprint sudo is already configured.')
            return
        replacement = updated(current)
        if hashlib.sha256(Path('/etc/pam.d/common-auth').read_bytes()).hexdigest() != COMMON_SHA:
            raise RuntimeError('common-auth changed; review authentication requirements before applying')
        if not Path('/usr/lib/x86_64-linux-gnu/security/pam_fprintd.so').is_file():
            raise RuntimeError('pam_fprintd is missing')
    print(''.join(difflib.unified_diff(current.decode().splitlines(True),
                                     replacement.decode().splitlines(True),
                                     fromfile=str(TARGET), tofile=str(TARGET) + ' (proposed)')))
    if not (args.apply or args.remove):
        print('Preview only. Apply: sudo python3 tools/install_sudo.py --apply')
        return
    if os.geteuid() != 0:
        raise RuntimeError('Run the apply/remove command with sudo')
    if args.apply:
        BACKUP.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            with BACKUP.open('xb') as backup:
                os.fchmod(backup.fileno(), 0o600)
                backup.write(current)
                backup.flush()
                os.fsync(backup.fileno())
        except FileExistsError:
            if BACKUP.is_symlink() or BACKUP.read_bytes() != current:
                raise RuntimeError('Existing backup differs; refusing to replace it')
    replace_file(TARGET, current, replacement)
    print('Sudo PAM updated. Password fallback remains available.' if args.apply else 'Original sudo PAM restored.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError) as error:
        raise SystemExit(str(error))
