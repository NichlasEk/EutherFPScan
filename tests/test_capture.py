import os
import socket
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.capture import collect, decode


def worker(code):
    return [sys.executable, "-c", code]


class CaptureTests(unittest.TestCase):
    def test_daemon_failure_interrupts_capture_and_observes_before_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            pidfile = Path(folder) / "helper.pid"
            observations = []

            def check():
                if pidfile.exists():
                    raise RuntimeError("VFS_DAEMON_GONE")

            def observe():
                pid = int(pidfile.read_text())
                os.kill(pid, 0)  # Helper still exists at observation time.
                observations.append(pid)

            code = ("import os,time; from pathlib import Path; "
                    f"Path({str(pidfile)!r}).write_text(str(os.getpid())); "
                    "os.write(2,b'EUTHER_STAGE capture_wait_for_swipe\\n'); time.sleep(10)")
            with self.assertRaisesRegex(RuntimeError, "VFS_DAEMON_GONE"):
                collect(worker(code), timeout=2, health_check=check, cleanup_observer=observe)
            self.assertEqual(len(observations), 1)
            with self.assertRaises(ProcessLookupError):
                os.kill(observations[0], 0)

    def test_client_disconnect_cancels_helper(self):
        server, client = socket.socketpair()
        client.close()
        with server, self.assertRaisesRegex(InterruptedError, "client disconnected"):
            collect(worker("import time; time.sleep(5)"), timeout=1, cancel_socket=server)

    def test_c_helper_with_synthetic_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            lib = str(Path(directory) / "mock.so")
            subprocess.run(["cc", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                            "tests/mock_wrapper.c", "-o", lib], check=True)
            command = ["build/euther-capture", "--capture", lib]
            self.assertEqual(collect(command), (2, 2, b"abcd"))
            with patch.dict(os.environ, {"MOCK_BAD": "1"}):
                with self.assertRaisesRegex(RuntimeError, "Invalid image metadata"):
                    collect(command)
            for stage in ("device_init", "capture_wait_for_swipe", "clean_handles"):
                with self.subTest(stage=stage), patch.dict(os.environ, {"MOCK_HANG": stage}):
                    with self.assertRaisesRegex(TimeoutError, "EUTHER_STAGE " + stage):
                        collect(command, timeout=.3)

    def test_partial_delivery(self):
        code = "import os,time; data=b'EFP1'+bytes.fromhex('0000000200000002')+b'abcd'; " \
               "[(os.write(1,bytes([b])),time.sleep(.001)) for b in data]"
        self.assertEqual(collect(worker(code)), (2, 2, b"abcd"))

    def test_invalid_frames(self):
        for frame in [b"", b"X" * 12, struct.pack("!4sII", b"EFP1", 0, 1),
                      struct.pack("!4sII", b"EFP1", 2049, 1),
                      struct.pack("!4sII", b"EFP1", 2, 2) + b"abc",
                      struct.pack("!4sII", b"EFP1", 1, 1) + b"ab"]:
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                decode(frame)

    def test_timeout_and_next_capture(self):
        with self.assertRaises(TimeoutError):
            collect(worker("import time; time.sleep(5)"), .1)
        code = "import os; os.write(1,b'EFP1'+bytes.fromhex('0000000100000001')+b'x')"
        self.assertEqual(collect(worker(code)), (1, 1, b"x"))

    def test_nonzero_exit(self):
        with self.assertRaisesRegex(RuntimeError, "exited 7"):
            collect(worker("raise SystemExit(7)"))

    def test_closed_pipes_but_hung_process(self):
        with self.assertRaises(TimeoutError):
            collect(worker("import os,time; os.close(1); os.close(2); time.sleep(5)"), .1)

    def test_output_limits(self):
        for fd, size in [(1, 5 * 1024 * 1024), (2, 70000)]:
            with self.subTest(fd=fd), self.assertRaises(ValueError):
                collect(worker(f"import os; os.write({fd}, b'x'*{size})"))

    def test_private_file_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "image.pgm"
            code = "import os; os.write(1,b'EFP1'+bytes.fromhex('0000000100000001')+b'x')"
            command = [sys.executable, "tools/capture.py", "--output", str(output),
                       "--", *worker(code)]
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(output.read_bytes(), b"P5\n1 1\n255\nx")
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), b"P5\n1 1\n255\nx")


if __name__ == "__main__":
    unittest.main()
