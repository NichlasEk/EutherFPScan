#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ $EUID -ne 0 ]]; then
    echo 'Run this installer with sudo from your terminal.' >&2
    exit 1
fi
task_library=build/libfprint-runtime/libfprint-2.so.2.0.0
test -f "$task_library" || { echo 'Run python3 tools/build_libfprint.py first.' >&2; exit 1; }
if readelf -d "$task_library" | rg -q 'RPATH|RUNPATH'; then
    echo 'Refusing library with an embedded runtime search path.' >&2
    exit 1
fi
# Install the service update too: disconnect must cancel the old capture.
bash tools/install_service.sh
systemctl stop fprintd
install -d -m 0755 /opt/eutherfpscan/fprint
install -m 0644 "$task_library" /opt/eutherfpscan/fprint/
ln -sfn libfprint-2.so.2.0.0 /opt/eutherfpscan/fprint/libfprint-2.so.2
install -d -m 0755 /etc/systemd/system/fprintd.service.d
install -m 0644 systemd/fprintd-euther.conf /etc/systemd/system/fprintd.service.d/euther.conf
systemctl daemon-reload
systemctl restart fprintd
python3 - <<'PY'
import re
import subprocess
base = ['gdbus', 'call', '--system', '--dest', 'net.reactivated.Fprint']
result = subprocess.check_output(base + ['--object-path', '/net/reactivated/Fprint/Manager',
    '--method', 'net.reactivated.Fprint.Manager.GetDevices'], text=True, timeout=10)
paths = re.findall(r"'(/net/reactivated/Fprint/Device/[^']+)'", result)
if len(paths) != 1:
    raise SystemExit('Expected one Euther device, got: ' + result)
name = subprocess.check_output(base + ['--object-path', paths[0], '--method',
    'org.freedesktop.DBus.Properties.Get', 'net.reactivated.Fprint.Device', 'name'],
    text=True, timeout=10)
if 'EutherFPScan Validity VFS491' not in name:
    raise SystemExit('Unexpected device name: ' + name)
print('fprintd device confirmed: EutherFPScan Validity VFS491')
PY
echo 'fprintd integration installed. PAM/sudo authentication has not been changed.'
echo 'Next: enroll five live swipes, then test correct finger, wrong finger and cancellation.'
