import os
from pathlib import Path
import signal
import shutil
import stat
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.capture import decode
from tools import service
from tools.service import StartupLog, UsbMirror, usb_node, usb_mount_args


class ServiceTests(unittest.TestCase):
    def test_launch_cleans_private_usb_directory_on_exit_and_startup_failure(self):
        real_temporary_directory = tempfile.TemporaryDirectory
        for fail in (False, True):
            with self.subTest(startup_failure=fail):
                roots = []

                def temporary_directory(*, prefix, dir):
                    self.assertEqual(dir, "/dev")
                    # The unit test cannot create host device nodes as root.
                    return real_temporary_directory(prefix=prefix)

                def run(root):
                    roots.append(root.parent)
                    self.assertEqual(stat.S_IMODE(root.parent.stat().st_mode), 0o700)
                    mirror = UsbMirror(root, make_node=lambda path, mode, dev: path.touch())
                    mirror.sync({"003/006": os.makedev(1, 3)})
                    if fail:
                        raise RuntimeError("synthetic startup failure")

                with patch.object(service, "usb_node", return_value="/unused"), \
                     patch.object(service.tempfile, "TemporaryDirectory", temporary_directory), \
                     patch.object(service, "launch_with_usb", run):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, "synthetic startup failure"):
                            service.launch()
                    else:
                        service.launch()
                self.assertEqual(len(roots), 1)
                self.assertFalse(roots[0].exists())

    def test_vendor_log_discards_messages_after_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "syslog"
            with StartupLog(path) as log, socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
                client.sendto(b"startup diagnostic", str(path))
                deadline = time.monotonic() + 1
                while not log.messages and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(list(log.messages), ["startup diagnostic"])
                log.ready()
                client.sendto(b"capture-phase message", str(path))
                time.sleep(.15)
                self.assertEqual(list(log.messages), [])
    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not available")
    def test_sandbox_sees_updated_usb_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            mirror = UsbMirror(root / "usb", make_node=lambda path, mode, dev: path.touch())
            mirror.sync({"003/005": os.makedev(189, 260)})
            code = (
                "from pathlib import Path; import sys; "
                "assert Path('/dev/bus/usb/003/005').exists(); print('ready',flush=True); "
                "sys.stdin.readline(); "
                "assert not Path('/dev/bus/usb/003/005').exists(); "
                "assert Path('/dev/bus/usb/003/006').exists(); "
                "exec(\"for path in ['/run/service/usb/003/006']:\\n"
                " try: Path(path).write_text('forbidden')\\n"
                " except OSError as e: assert e.errno == 30\\n"
                " else: raise AssertionError('USB view was writable')\")"
            )
            command = ["bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
                       "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
                       "--dev", "/dev", *usb_mount_args(root / "usb"),
                       "--bind", str(root), "/run/service",
                       "--ro-bind", str(root / "usb"), "/run/service/usb",
                       "--", "/usr/bin/python3", "-c", code]
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(proc.stdout.readline().strip(), "ready")
                mirror.sync({"003/006": os.makedev(189, 261)})
                stdout, stderr = proc.communicate("updated\n", timeout=3)
                self.assertEqual(proc.returncode, 0, stdout + stderr)
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.communicate()

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap not available")
    def test_usb_mount_permits_character_device_access_without_capabilities(self):
        # /dev/null is a harmless real character device. Regular files cannot
        # detect the nodev regression that broke the previous USB mount.
        code = ("import os; "
                "fd=os.open('/dev/bus/usb/null',os.O_RDWR); os.close(fd); "
                "assert int(next(l.split()[1] for l in open('/proc/self/status') "
                "if l.startswith('CapEff:')),16)==0; print('DEVICE_OPEN_OK')")
        result = subprocess.run([
            "bwrap", "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
            "--proc", "/proc", "--dev", "/dev", *usb_mount_args("/dev"),
            "--", "/usr/bin/python3", "-c", code], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DEVICE_OPEN_OK", result.stdout)

    def test_usb_mirror_tracks_new_address_and_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            created = []

            def make_node(path, mode, device):
                created.append((path.name, mode, device))
                path.touch()

            mirror = UsbMirror(folder, make_node=make_node)
            mirror.sync({"003/005": os.makedev(189, 260)})
            mirror.sync({"003/005": os.makedev(189, 260)})
            self.assertEqual(len(created), 1)
            mirror.sync({"003/006": os.makedev(189, 261)})
            self.assertFalse((Path(folder) / "003/005").exists())
            self.assertTrue((Path(folder) / "003/006").exists())
            self.assertEqual(created[-1][1], stat.S_IFCHR | 0o600)
            mirror.sync({})
            self.assertFalse((Path(folder) / "003/006").exists())

    def test_usb_mirror_rejects_paths_outside_mirror(self):
        with tempfile.TemporaryDirectory() as folder:
            mirror = UsbMirror(folder)
            for name in ("/dev/bus/usb/003/006", "../escape", "003/../../escape"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    mirror.sync({name: os.makedev(189, 261)})

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
                    f"service.SYSLOG=Path({str(root / 'syslog')!r}); "
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
