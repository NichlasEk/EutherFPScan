"""Check Debian fprintd discovery on a private D-Bus, without hardware or enrollment."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def check():
    with tempfile.TemporaryDirectory(prefix="euther-dbus-test-") as directory:
        env = {**os.environ,
               "DBUS_SYSTEM_BUS_ADDRESS": os.environ["DBUS_SESSION_BUS_ADDRESS"],
               "LD_LIBRARY_PATH": str(ROOT / "build/libfprint-runtime"),
               "FP_EUTHER_VFS491": str(Path(directory) / "unused-capture.sock")}
        with tempfile.TemporaryFile() as log:
            daemon = subprocess.Popen(["/usr/libexec/fprintd", "--no-timeout"], env=env,
                                      stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 8
                command = ["gdbus", "call", "--session", "--dest", "net.reactivated.Fprint",
                           "--object-path", "/net/reactivated/Fprint/Manager", "--method",
                           "net.reactivated.Fprint.Manager.GetDevices"]
                while True:
                    result = subprocess.run(command, capture_output=True, text=True, timeout=2)
                    if result.returncode == 0:
                        break
                    if daemon.poll() is not None or time.monotonic() > deadline:
                        log.seek(0)
                        raise RuntimeError(log.read(8192).decode(errors="replace") + result.stderr)
                    time.sleep(.1)
                paths = re.findall(r"'(/net/reactivated/Fprint/Device/[^']+)'", result.stdout)
                if len(paths) != 1:
                    raise RuntimeError("Unexpected device list: " + result.stdout)
                result = subprocess.run(["gdbus", "call", "--session", "--dest",
                                         "net.reactivated.Fprint", "--object-path", paths[0],
                                         "--method", "org.freedesktop.DBus.Properties.Get",
                                         "net.reactivated.Fprint.Device", "name"],
                                        capture_output=True, text=True, check=True, timeout=2)
                if "EutherFPScan Validity VFS491" not in result.stdout:
                    raise RuntimeError("Unexpected device name: " + result.stdout)
                print("Debian fprintd discovers EutherFPScan VFS491 on private D-Bus.")
            finally:
                daemon.terminate()
                try:
                    daemon.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    daemon.kill()
                    daemon.wait()


if __name__ == "__main__":
    if sys.argv[1:] == ["--inside"]:
        check()
    else:
        os.execvp("dbus-run-session", ["dbus-run-session", "--", sys.executable,
                                      str(Path(__file__).resolve()), "--inside"])
