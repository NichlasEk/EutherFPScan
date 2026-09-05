#!/usr/bin/env python3
"""Compare device access from /run and /dev using only private /dev/null nodes.

Run with sudo. Does not open the fingerprint reader or restart any service.
Temporary directories and device nodes are removed on exit.
"""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

try:
    from .service import UsbMirror, usb_mount_args
except ImportError:
    from service import UsbMirror, usb_mount_args


PROBE = r'''
import json, os
path = '/dev/bus/usb/003/006'
info = os.stat(path)
result = dict(uid=os.geteuid(), gid=os.getegid(), mode=oct(info.st_mode & 0o777),
              owner=info.st_uid, device=[os.major(info.st_rdev), os.minor(info.st_rdev)])
result['mounts'] = [line.strip() for line in open('/proc/self/mountinfo')
                    if line.split()[4] in ('/dev/bus/usb', '/run/eutherfpscan/usb')]
result['capabilities'] = [line.strip() for line in open('/proc/self/status')
                          if line.startswith(('CapEff:', 'CapBnd:'))]
try:
    fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
    os.close(fd)
    result['open'] = 'OK'
except OSError as error:
    result['open'] = str(error)
    result['errno'] = error.errno
print(json.dumps(result, indent=2))
'''


def probe(parent):
    with tempfile.TemporaryDirectory(prefix='euther-usb-probe-', dir=parent) as folder:
        mirror = UsbMirror(Path(folder) / 'usb')
        # Same permissions and directory layout as the real sensor mirror,
        # but major 1, minor 3 is /dev/null; no USB node is ever exposed.
        mirror.sync({'003/006': os.makedev(1, 3)})
        command = [
            'bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
            '--ro-bind', '/usr', '/usr', '--symlink', 'usr/lib', '/lib',
            '--symlink', 'usr/lib64', '/lib64', '--symlink', 'usr/bin', '/bin',
            '--proc', '/proc', '--dev', '/dev',
            *usb_mount_args(mirror.root), '--tmpfs', '/tmp', '--dir', '/run',
            '--bind', folder, '/run/eutherfpscan',
            '--ro-bind', str(mirror.root), '/run/eutherfpscan/usb',
            '--', '/usr/bin/python3', '-c', PROBE,
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        print(result.stdout, end='', flush=True)
        if result.stderr:
            print(result.stderr, end='', flush=True)
        if result.returncode:
            raise RuntimeError(f'bwrap exited {result.returncode}')
        return json.loads(result.stdout)['open'] == 'OK'


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run: sudo python3 tools/check_usb_sandbox.py')
    if not shutil.which('bwrap'):
        raise SystemExit('bubblewrap is missing')
    info = os.stat('/dev/null')
    if not stat.S_ISCHR(info.st_mode) or info.st_rdev != os.makedev(1, 3):
        raise SystemExit('Unexpected /dev/null device; stopping')
    print('Device sandbox diagnostic: /dev/null only; no sensor access.', flush=True)
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        if line.split()[4] in ('/run', '/dev'):
            print('HOST ' + line, flush=True)
    results = {}
    for parent in ('/run', '/dev'):
        print(f'\nSOURCE {parent}', flush=True)
        try:
            results[parent] = probe(parent)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            results[parent] = None
            print(f'PROBE_FAILED: {error}', flush=True)
    if results == {'/run': False, '/dev': True}:
        print('\nCONFIRMED: /run mirror denied; /dev mirror opens successfully.')
    else:
        print('\nRESULT: ' + json.dumps(results) + '; inspect details above.')


if __name__ == '__main__':
    main()
