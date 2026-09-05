"""Load the wrapper in a sandbox without hardware, host home, IPC or network."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lazy", action="store_true", help="Defer optional symbol binding")
    args = parser.parse_args()
    command = [
        "bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/bin", "/bin",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/opt",
        "--ro-bind", str(ROOT / "build"), "/opt/build",
        "--ro-bind", str(ROOT / "private"), "/opt/private",
        "--setenv", "LD_LIBRARY_PATH",
        "/opt/build/openssl-0.9.8zh:/opt/build/compat/usr/lib/x86_64-linux-gnu",
        "--", "/opt/build/euther-capture", "--probe-lazy" if args.lazy else "--probe",
        "/opt/private/libvfsFprintWrapper.so",
    ]
    try:
        raise SystemExit(subprocess.run(command, timeout=10).returncode)
    except subprocess.TimeoutExpired:
        parser.exit(1, "Wrapper load timed out\n")


if __name__ == "__main__":
    main()
