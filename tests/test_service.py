import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from tools.capture import decode
from tools.service import usb_node


class ServiceTests(unittest.TestCase):
    def test_usb_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(RuntimeError):
                usb_node(root)
            device = root / "3-1"
            device.mkdir()
            for name, value in {"idVendor": "138a", "idProduct": "003d",
                                "busnum": "3", "devnum": "7"}.items():
                (device / name).write_text(value)
            self.assertEqual(usb_node(root), "/dev/bus/usb/003/007")
            (device / "idProduct").write_text("0090")
            with self.assertRaises(RuntimeError):
                usb_node(root)

    def test_socket_session_and_shutdown(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "private").mkdir()
            (root / "bin").mkdir()
            ready = root / "ready"
            daemon = root / "private/vcsFPService"
            daemon.write_text("#!/usr/bin/python3\nfrom pathlib import Path\n"
                              f"Path({str(ready)!r}).touch()\n")
            helper = root / "bin/euther-capture"
            helper.write_text("#!/usr/bin/python3\nimport os\n"
                              "os.write(1,b'EFP1'+bytes.fromhex('0000000100000001')+b'x')\n")
            daemon.chmod(0o700)
            helper.chmod(0o700)
            path = str(root / "control.sock")
            code = ("from pathlib import Path; from tools import service; "
                    f"service.BASE=Path({folder!r}); service.SOCKET={path!r}; "
                    f"service.READY=Path({str(ready)!r}); service.serve()")
            proc = subprocess.Popen([sys.executable, "-c", code],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    start_new_session=True)
            try:
                deadline = time.monotonic() + 5
                while not Path(path).exists():
                    if proc.poll() is not None or time.monotonic() > deadline:
                        self.fail("Mock service did not start")
                    time.sleep(.02)
                self.assertEqual(Path(path).stat().st_mode & 0o777, 0o600)

                def request(command):
                    with socket.socket(socket.AF_UNIX) as client:
                        client.settimeout(3)
                        client.connect(path)
                        client.sendall(command)
                        data = bytearray()
                        while block := client.recv(4096):
                            data.extend(block)
                        return data

                self.assertIn(b"IPC_READY", request(b"S"))
                self.assertEqual(decode(request(b"C")), (1, 1, b"x"))
                self.assertIn(b"ERROR", request(b"X"))
                self.assertEqual(decode(request(b"C")), (1, 1, b"x"))
                proc.terminate()
                self.assertEqual(proc.wait(timeout=3), 0)
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                proc.stderr.close()
