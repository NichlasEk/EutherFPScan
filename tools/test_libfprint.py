"""Integration tests against the real private libfprint; public-domain NIST fixtures only."""
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    image = ROOT / "build/libfprint-src/examples/prints" / (name + ".png")
    # Convert the public test image to the vendor orientation/polarity. The
    # driver must normalize it again before libfprint extracts minutiae.
    # Upstream stores the fingerprint in the PNG alpha channel (Cairo A8).
    pgm = subprocess.check_output(["magick", str(image),
                                   "-alpha", "extract", "-colorspace", "gray",
                                   "-negate", "-flip", "-depth", "8", "pgm:-"])
    header = re.match(rb"P5\s+(\d+)\s+(\d+)\s+255\s", pgm)
    if header is None:
        raise ValueError("Unexpected fixture PGM")
    w, h = map(int, header.groups())
    pixels = pgm[header.end():]
    if len(pixels) != w * h:
        raise ValueError("Unexpected fixture length")
    return struct.pack("!4sII", b"EFP1", w, h) + pixels


def exercise(mode, responses, prefix=()):
    with tempfile.TemporaryDirectory(prefix="euther-fprint-test-") as directory:
        path = str(Path(directory) / "capture.sock")
        stopped = threading.Event()
        failures = []
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(path)
            server.listen(1)
            server.settimeout(.1)

            def serve():
                index = 0
                while not stopped.is_set():
                    try:
                        connection, _ = server.accept()
                    except TimeoutError:
                        continue
                    with connection:
                        connection.settimeout(2)
                        try:
                            if connection.recv(1) != b"C":
                                raise AssertionError("Unexpected capture request")
                            if index >= len(responses):
                                raise AssertionError("Unexpected extra capture")
                            response = responses[index]
                            index += 1
                            if response is None:
                                # Cancellation must close the connection promptly.
                                if connection.recv(1) != b"":
                                    raise AssertionError("Expected client disconnect")
                            else:
                                # Exercise partial header delivery.
                                connection.sendall(response[:3])
                                connection.sendall(response[3:])
                        except (OSError, AssertionError) as exc:
                            failures.append(str(exc))

            thread = threading.Thread(target=serve)
            thread.start()
            try:
                result = subprocess.run([*prefix, str(ROOT / "build/fprint-check"), mode],
                                        env={**os.environ, "FP_EUTHER_VFS491": path,
                                             "LD_LIBRARY_PATH": str(ROOT / "build/libfprint-runtime")},
                                        capture_output=True, text=True, timeout=20)
            finally:
                stopped.set()
                thread.join(timeout=3)
            if thread.is_alive() or failures:
                raise AssertionError(f"Mock transport failed: {failures}")
        return result


class LibfprintTests(unittest.TestCase):
    def test_capture(self):
        result = exercise("capture", [fixture("arch")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("IMAGE 256 240", result.stdout)
        self.assertIn("CLOSED", result.stdout)

    def test_enrollment_serialization_match_and_nonmatch(self):
        result = exercise("roundtrip", [fixture("arch")] * 6 + [fixture("whorl")])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ENROLLED_AND_RESTORED", result.stdout)
        self.assertIn("SAME_IMAGE_MATCH 1", result.stdout)
        self.assertIn("OTHER_IMAGE_MATCH 0", result.stdout)

    def test_cancellation(self):
        result = exercise("cancel-retry", [None, fixture("arch")])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CANCELLED", result.stdout)
        self.assertIn("CAPTURE_AFTER_CANCEL_OK", result.stdout)

    def test_invalid_or_truncated_responses(self):
        for response in (b"ERROR: Capture timed out", b"EFP", fixture("arch")[:-1],
                         struct.pack("!4sII", b"EFP1", 2049, 1),
                         fixture("arch") + b"unexpected"):
            with self.subTest(length=len(response)):
                result = exercise("capture", [response])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FAILED:", result.stderr)
                self.assertNotIn("IMAGE ", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
