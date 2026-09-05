"""Bounded subprocess supervisor and EFP1 decoder; no device access on import."""
import argparse
import math
import os
from pathlib import Path
import selectors
import signal
import socket
import struct
import subprocess
import time

MAX_PIXELS = 2048 * 2048


def decode(frame):
    if len(frame) < 12:
        raise ValueError("Truncated image header")
    magic, width, height = struct.unpack("!4sII", frame[:12])
    if magic != b"EFP1" or not (0 < width <= 2048 and 0 < height <= 2048):
        raise ValueError("Invalid image header")
    if len(frame) != 12 + width * height:
        raise ValueError("Image payload length mismatch")
    return width, height, frame[12:]


def collect(command, timeout=35, cancel_socket=None):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be positive")
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)
    frame, diagnostics = bytearray(), bytearray()
    deadline = time.monotonic() + timeout

    def timeout_error(message):
        # Preserve the most recent diagnostics, including the last entered
        # vendor call. Image bytes are never included in the error.
        tail = diagnostics[-2048:].decode(errors="replace").strip()
        return TimeoutError(message + ("\nHelper diagnostics:\n" + tail if tail else ""))

    try:
        with selectors.DefaultSelector() as sel:
            sel.register(proc.stdout, selectors.EVENT_READ, frame)
            sel.register(proc.stderr, selectors.EVENT_READ, diagnostics)
            if cancel_socket is not None:
                sel.register(cancel_socket, selectors.EVENT_READ, None)
            while any(key.data is not None for key in sel.get_map().values()):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise timeout_error("Capture timed out")
                for key, _ in sel.select(remaining):
                    if key.data is None:
                        if not cancel_socket.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT):
                            raise InterruptedError("Capture client disconnected")
                        raise ValueError("Unexpected data during capture")
                    block = os.read(key.fd, 65536)
                    if not block:
                        sel.unregister(key.fileobj)
                        continue
                    target = key.data
                    limit = MAX_PIXELS + 12 if target is frame else 65536
                    if len(target) + len(block) > limit:
                        raise ValueError("Capture output limit exceeded")
                    target.extend(block)
            try:
                code = proc.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as exc:
                raise timeout_error("Capture cleanup timed out") from exc
            if code:
                raise RuntimeError(f"Capture exited {code}: " + diagnostics.decode(errors="replace"))
        return decode(frame)
    finally:
        # Also terminate descendants retaining pipes after the helper exits.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=35)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("Provide helper command after --")
    try:
        width, height, pixels = collect(command, args.timeout)
        # Exclusive creation prevents accidental replacement; fingerprints are private.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as image:
            image.write(f"P5\n{width} {height}\n255\n".encode() + pixels)
        print(f"Saved {width} x {height} raw grayscale image to {args.output}")
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
