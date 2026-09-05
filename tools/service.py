"""Isolated VFS daemon and serialized capture socket. No enrollment or firmware tools."""
import argparse
from collections import deque
import ctypes
import os
from pathlib import Path
import re
import signal
import stat
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

try:
    from .capture import collect
except ImportError:
    from capture import collect

BASE = Path(__file__).resolve().parents[1]
SOCKET = "/run/eutherfpscan/control.sock"
READY = Path("/tmp/vcsSemKey_ServiceReady")
SYSLOG = Path("/dev/log")


def daemon_pids(proc=Path("/proc"), parent_pid=None):
    """Find live vendor processes in this sandbox, excluding zombies."""
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            if entry.joinpath("comm").read_text().strip() != "vcsFPService":
                continue
            fields = entry.joinpath("stat").read_text().rsplit(") ", 1)[1].split()
            state = fields[0]
            if parent_pid is not None and int(fields[1]) != parent_pid:
                continue
            if state not in ("Z", "X"):
                found.append(int(entry.name))
        except (FileNotFoundError, ProcessLookupError):
            continue  # Process exited between reads.
    return sorted(found)


def adopt_daemon_children():
    # Receive exit status of the vendor's daemonized child rather than losing
    # it to bubblewrap's PID-namespace init. No privileges are added.
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def start_vendor_daemon(command):
    # Python ignores SIGPIPE, but Popen normally resets it before exec.
    # Keep it ignored for this legacy daemon: writes to disconnected peers
    # must return EPIPE instead of terminating the entire sensor service.
    # The helper and all other subprocesses retain their existing policy.
    if signal.getsignal(signal.SIGPIPE) != signal.SIG_IGN:
        raise RuntimeError("Expected SIGPIPE ignored in the Python supervisor")
    return subprocess.Popen(command, restore_signals=False)


class DaemonMonitor:
    def __init__(self, parent):
        self.parent = parent
        self.pids = set(daemon_pids(parent_pid=os.getpid()))

    def check(self):
        live = set(daemon_pids()) & self.pids
        for pid in list(self.pids):
            if pid == self.parent.pid:
                code = self.parent.poll()
                if code is None:
                    continue
            else:
                try:
                    waited, status = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    continue
                if not waited:
                    continue
                code = os.waitstatus_to_exitcode(status)
            self.pids.remove(pid)
            reason = f"signal={signal.Signals(-code).name}" if code < 0 else f"code={code}"
            print(f"VFS_DAEMON_EXIT pid={pid} {reason}", flush=True)
        if not live:
            raise RuntimeError("VFS_DAEMON_GONE: no live vcsFPService; readiness marker is insufficient")

    def before_cleanup(self):
        print("VFS_DAEMON_BEFORE_HELPER_CLEANUP alive=" +
              ",".join(map(str, daemon_pids())), flush=True)
        self.check()


def helper_failure_summary(error):
    # Only our fixed stage names and numeric results may reach the journal.
    # Do not include free-form vendor diagnostics or image data.
    allowed = {"load_wrapper", "wait_service", "set_matcher", "device_init",
               "capture_wait_for_swipe", "read_image", "free_image",
               "clean_handles", "device_exit", "unload_wrapper", "capture"}
    result = []
    for line in str(error).splitlines():
        match = re.fullmatch(r"EUTHER_(STAGE|RESULT) ([a-z_]+)(?: (-?[0-9]{1,11}))?", line)
        if match and match[2] in allowed:
            if (match[1] == "STAGE" and match[3] is None or
                    match[1] == "RESULT" and match[3] is not None):
                result.append(match[0])
    return result[-24:]


class StartupLog:
    """Drain vendor syslog; retain only bounded startup messages, never captures."""
    def __init__(self, path):
        self.path = path
        self.messages = deque(maxlen=24)
        self.lock = threading.Lock()
        self.record = True
        self.stop = threading.Event()

    def __enter__(self):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.socket.bind(str(self.path))
        self.socket.settimeout(.1)
        self.thread = threading.Thread(target=self.drain)
        self.thread.start()
        return self

    def drain(self):
        while not self.stop.is_set():
            try:
                message = self.socket.recv(1024)
            except TimeoutError:
                continue
            with self.lock:
                if self.record:
                    self.messages.append(message.decode(errors="replace"))

    def ready(self):
        with self.lock:
            self.record = False
            self.messages.clear()

    def __exit__(self, kind, error, traceback):
        self.stop.set()
        self.thread.join(timeout=1)
        self.socket.close()
        self.path.unlink(missing_ok=True)
        if error:
            for message in self.messages:
                # Render control characters as escapes in the journal.
                print("VENDOR_STARTUP " + ascii(message), flush=True)


def check_usb_access():
    nodes = list(Path("/dev/bus/usb").glob("*/*"))
    if not nodes:
        raise RuntimeError("No sensor device node visible inside sandbox")
    for node in nodes:
        if not stat.S_ISCHR(node.stat().st_mode):
            raise RuntimeError("Unexpected non-device in USB view")
        # Open and close only: no USB transfer, reset or initialization.
        fd = os.open(node, os.O_RDWR | os.O_CLOEXEC)
        os.close(fd)
        print(f"USB_OPEN_OK {node}", flush=True)


def usb_node(sysfs=Path("/sys/bus/usb/devices"), allow_missing=False):
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
    if not matches and allow_missing:
        return None
    if len(matches) != 1:
        raise RuntimeError(f"Expected one VFS491, found {len(matches)}")
    return matches[0]


class UsbMirror:
    """Host-maintained view of only the selected sensor's device node.

    Changes remain visible when udev gives the sensor a new USB address.
    The device mount must permit device access (no nodev flag).
    """
    def __init__(self, root, make_node=os.mknod):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.make_node = make_node
        self.current = {}

    def sync(self, nodes, cleanup=False):
        for name in nodes:
            relative = Path(name)
            if (relative.is_absolute() or len(relative.parts) != 2 or
                    not all(len(part) == 3 and part.isdecimal() for part in relative.parts)):
                raise ValueError("Invalid USB node name")
        # Remove obsolete nodes before adding replacements, so unrelated
        # devices cannot remain exposed through an old USB minor number.
        for name in self.current.keys() - nodes.keys():
            (self.root / name).unlink(missing_ok=True)
        for name, device in nodes.items():
            if self.current.get(name) == device:
                continue
            relative = Path(name)
            target = self.root / relative
            target.parent.mkdir(mode=0o700, exist_ok=True)
            target.unlink(missing_ok=True)
            self.make_node(target, stat.S_IFCHR | 0o600, device)
        if self.current != nodes:
            print("USB exposure: " + ("cleared during shutdown" if cleanup else
                  (", ".join(sorted(nodes)) or "sensor temporarily absent")),
                  flush=True)
        self.current = dict(nodes)


def current_usb_nodes():
    node = usb_node(allow_missing=True)
    if node is None:
        return {}
    try:
        info = os.stat(node)
    except FileNotFoundError:
        return {}  # udev may be between removal and creation
    if not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 189:
        raise RuntimeError("Unexpected USB device node")
    return {"/".join(Path(node).parts[-2:]): info.st_rdev}


def usb_mount_args(source):
    # Bubblewrap --remount-ro adds nodev, even after --dev-bind. This would
    # cause EACCES when opening the USB character device. Drop capabilities
    # explicitly instead; only the host can create new device nodes.
    return ["--dev-bind", str(source), "/dev/bus/usb", "--cap-drop", "ALL"]


def launch():
    # Validate uniqueness before starting any vendor process.
    usb_node()
    # /run is nodev on Debian: --dev-bind preserves that restriction.
    # Use a private 0700 directory on devtmpfs, where device opens work.
    # The context also removes the mirror if startup fails before Popen.
    with tempfile.TemporaryDirectory(prefix="eutherfpscan-usb-", dir="/dev") as folder:
        launch_with_usb(Path(folder) / "usb")


def launch_with_usb(root):
    mirror = UsbMirror(root)
    mirror.sync(current_usb_nodes())
    os.makedirs("/var/lib/eutherfpscan/etc", mode=0o700, exist_ok=True)
    command = [
        "bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/bin", "/bin",
        "--proc", "/proc", "--dev", "/dev", "--ro-bind", "/sys", "/sys",
        *usb_mount_args(mirror.root), "--tmpfs", "/tmp", "--dir", "/var",
        "--dir", "/run", "--symlink", "/run", "/var/run",
        "--bind", "/run/eutherfpscan", "/run/eutherfpscan",
        # The alias is not used for device I/O.
        "--ro-bind", str(mirror.root), "/run/eutherfpscan/usb",
        "--bind", "/var/lib/eutherfpscan/etc", "/etc",
        "--ro-bind", str(BASE), "/opt/eutherfpscan",
        "--setenv", "LD_LIBRARY_PATH", "/opt/eutherfpscan/lib",
        "--", "/usr/bin/python3", "/opt/eutherfpscan/tools/service.py", "--inside",
    ]
    print("Starting isolated daemon with a tracked VFS491 USB view", flush=True)
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    child = subprocess.Popen(command)
    try:
        while child.poll() is None and not stopped:
            mirror.sync(current_usb_nodes())
            time.sleep(.1)
        if not stopped and child.returncode:
            raise RuntimeError(f"VFS sandbox exited {child.returncode}")
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        mirror.sync({}, cleanup=True)


def serve():
    with StartupLog(SYSLOG) as startup_log:
        serve_with_log(startup_log)


def serve_with_log(startup_log):
    os.umask(0o077)
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    adopt_daemon_children()
    daemon = start_vendor_daemon([str(BASE / "private/vcsFPService")])
    # The vendor daemon may fork. IPC marker confirms service initialization,
    # not sensor readiness; the first actual capture is the hardware check.
    deadline = time.monotonic() + 15
    ready = READY
    while not (ready.exists() and daemon_pids()):
        if stopped or time.monotonic() >= deadline:
            raise RuntimeError("VFS daemon did not create its IPC readiness marker")
        if daemon.poll() not in (None, 0):
            raise RuntimeError(f"VFS daemon exited {daemon.returncode}")
        time.sleep(.1)
    print("VFS_DAEMON_ALIVE: " + ",".join(map(str, daemon_pids())), flush=True)
    monitor = DaemonMonitor(daemon)
    startup_log.ready()
    Path(SOCKET).unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(SOCKET)
        os.chmod(SOCKET, 0o600)
        server.listen(1)
        server.settimeout(.5)
        print("IPC_READY: daemon initialized; sensor capture remains unverified", flush=True)
        while not stopped:
            monitor.check()
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            with connection:
                connection.settimeout(5)
                try:
                    # Fixed one-byte commands avoid framing ambiguity.
                    command = connection.recv(1)
                    monitor.check()
                    if command == b"S":
                        connection.sendall(b"IPC_READY; hardware capture not implied\n")
                    elif command == b"C":
                        print("Capture requested (35 second deadline)", flush=True)
                        w, h, data = collect([str(BASE / "bin/euther-capture"), "--capture",
                                              str(BASE / "private/libvfsFprintWrapper.so")],
                                             cancel_socket=connection,
                                             health_check=monitor.check,
                                             cleanup_observer=monitor.before_cleanup)
                        connection.sendall(struct.pack("!4sII", b"EFP1", w, h) + data)
                        print(f"Capture complete: {w} x {h}", flush=True)
                    else:
                        connection.sendall(b"ERROR: unknown command\n")
                except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
                    # Vendor diagnostics can include device data: return only to
                    # the root client; journal records the exception class.
                    print(f"Request failed: {type(exc).__name__}", flush=True)
                    for summary in helper_failure_summary(exc):
                        print(summary, flush=True)
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
            check_usb_access()
            serve()
        else:
            request(args.status)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")
