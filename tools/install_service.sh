#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ $EUID -ne 0 ]]; then
    echo 'Run this installer with sudo from your terminal.' >&2
    exit 1
fi
for task_file in build/euther-capture private/vcsFPService private/libvfsFprintWrapper.so \
    build/openssl-0.9.8zh/libssl.so.0.9.8 build/openssl-0.9.8zh/libcrypto.so.0.9.8 \
    build/compat/usr/lib/x86_64-linux-gnu/libusb-0.1.so.4; do
    test -f "$task_file" || { echo "Missing $task_file; run make and tools/prepare_compat.py first" >&2; exit 1; }
done
command -v bwrap >/dev/null
systemd-analyze verify systemd/eutherfpscan.service
systemctl stop eutherfpscan.service 2>/dev/null || true
install -d -m 0755 /opt/eutherfpscan/{bin,tools,lib}
install -d -m 0700 /opt/eutherfpscan/private
install -m 0755 build/euther-capture /opt/eutherfpscan/bin/
install -m 0755 private/vcsFPService /opt/eutherfpscan/private/
install -m 0644 private/libvfsFprintWrapper.so /opt/eutherfpscan/private/
install -m 0644 tools/{service,capture}.py /opt/eutherfpscan/tools/
install -m 0644 build/openssl-0.9.8zh/lib{ssl,crypto}.so.0.9.8 /opt/eutherfpscan/lib/
install -m 0644 build/compat/usr/lib/x86_64-linux-gnu/libusb-0.1.so.4 /opt/eutherfpscan/lib/
install -m 0644 systemd/eutherfpscan.service /etc/systemd/system/
systemctl daemon-reload
systemctl start eutherfpscan.service
for ((task_attempt=0; task_attempt<20; task_attempt++)); do
    if [[ -S /run/eutherfpscan/control.sock ]]; then
        python3 /opt/eutherfpscan/tools/service.py --status
        systemctl enable eutherfpscan.service
        echo 'Enabled at boot. IPC initialized; a real finger swipe is still required to verify capture.'
        exit 0
    fi
    if systemctl is-failed --quiet eutherfpscan.service; then break; fi
    sleep 1
done
echo 'Readiness failed; automatic startup was not newly enabled. Check: sudo journalctl -u eutherfpscan -n 60 --no-pager' >&2
exit 1
