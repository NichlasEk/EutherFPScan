"""Isolated VFS daemon and serialized capture socket. No enrollment or firmware tools."""
import argparse
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import time

try:
    from .capture import collect
except ImportError:
    from capture import collect

BASE = Path(__file__).resolve().parents[1]
SOCKET = "/run/eutherfpscan/control.sock"
READY = Path("/tmp/vcsSemKey_ServiceReady")


def usb_node(sysfs=Path("/sys/bus/usb/devices")):
    matches = []
    for entry in sysfs.iterdir():
        try:
            if (entry.joinpath("idVendor").read_text().strip(),
                entry.joinpath("idProduct").read_text().strip()) == ("138a", "003d"):
                bus = int(entry.joinpath("busnum").read_text())
                dev = int(entry.joinpath("devnum").read_text())
                matches.append(f"/dev/bus/usb/{bus:03d}/{dev:03d}")
        except (OSError, ValueError):
            continue
    if len(matches) != 1:
        raise RuntimeError(f"Expected one VFS491, found {len(matches)}")
    return matches[0]


def launch():
    node = usb_node()
    os.makedirs("/var/lib/eutherfpscan/etc", mode=0o700, exist_ok=True)
    command = [
        "bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/bin", "/bin",
        "--proc", "/proc", "--dev", "/dev", "--ro-bind", "/sys", "/sys",
        "--dev-bind", node, node, "--tmpfs", "/tmp", "--dir", "/var",
        "--dir", "/run", "--symlink", "/run", "/var/run",
        "--bind", "/run/eutherfpscan", "/run/eutherfpscan",
        "--bind", "/var/lib/eutherfpscan/etc", "/etc",
        "--ro-bind", str(BASE), "/opt/eutherfpscan",
        "--setenv", "LD_LIBRARY_PATH", "/opt/eutherfpscan/lib",
        "--", "/usr/bin/python3", "/opt/eutherfpscan/tools/service.py", "--inside",
    ]
    print(f"Starting isolated daemon with USB {node}", flush=True)
    os.execvp(command[0], command)


def serve():
    os.umask(0o077)
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    daemon = subprocess.Popen([str(BASE / "private/vcsFPService")])
    # The vendor daemon may fork. IPC marker confirms service initialization,
    # not sensor readiness; the first actual capture is the hardware check.
    deadline = time.monotonic() + 15
    ready = READY
    while not ready.exists():
        if stopped or time.monotonic() >= deadline:
            raise RuntimeError("VFS daemon did not create its IPC readiness marker")
        if daemon.poll() not in (None, 0):
            raise RuntimeError(f"VFS daemon exited {daemon.returncode}")
        time.sleep(.1)
    Path(SOCKET).unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(SOCKET)
        os.chmod(SOCKET, 0o600)
        server.listen(1)
        server.settimeout(.5)
        print("IPC_READY: daemon initialized; sensor capture remains unverified", flush=True)
        while not stopped:
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            with connection:
                connection.settimeout(5)
                try:
                    # Fixed one-byte commands avoid framing ambiguity.
                    command = connection.recv(1)
                    if command == b"S":
                        connection.sendall(b"IPC_READY; hardware capture not implied\n")
                    elif command == b"C":
                        print("Capture requested (35 second deadline)", flush=True)
                        w, h, data = collect([str(BASE / "bin/euther-capture"), "--capture",
                                              str(BASE / "private/libvfsFprintWrapper.so")])
                        connection.sendall(struct.pack("!4sII", b"EFP1", w, h) + data)
                        print(f"Capture complete: {w} x {h}", flush=True)
                    else:
                        connection.sendall(b"ERROR: unknown command\n")
                except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
                    # Vendor diagnostics can include device data: return only to
                    # the root client; journal records the exception class.
                    print(f"Request failed: {type(exc).__name__}", flush=True)
                    try:
                        connection.sendall(("ERROR: " + str(exc)[:4096]).encode())
                    except OSError:
                        pass
    # Exiting the PID namespace removes the daemon and any forked children.


def request(status=False):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(40)
        client.connect(SOCKET)
        client.sendall(b"S" if status else b"C")
        chunks = bytearray()
        while True:
            block = client.recv(65536)
            if not block:
                break
            chunks.extend(block)
            if len(chunks) > 2048 * 2048 + 12:
                raise ValueError("Service response exceeded limit")
        if chunks.startswith(b"ERROR:"):
            raise RuntimeError(chunks.decode(errors="replace"))
        sys.stdout.buffer.write(chunks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ("launch", "inside", "request", "status"):
        group.add_argument("--" + name, action="store_true")
    args = parser.parse_args()
    try:
        if args.launch:
            launch()
        elif args.inside:
            serve()
        else:
            request(args.status)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")
