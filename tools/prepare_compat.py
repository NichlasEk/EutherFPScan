"""Prepare pinned local dependencies on Debian 13 amd64; install nothing globally."""
import hashlib
import lzma
from pathlib import Path
import struct
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
PRIVATE = ROOT / "private"


def fetch(name, url, digest):
    path = BUILD / name
    if not path.exists():
        print(f"Fetching {name}", flush=True)
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"Checksum mismatch: {name}")
        path.write_bytes(data)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f"Checksum mismatch: {name}")
    return path


def prepare():
    BUILD.mkdir(exist_ok=True)
    PRIVATE.mkdir(exist_ok=True, mode=0o700)
    ssl = fetch("openssl-0.9.8zh.tar.gz",
                "https://www.openssl.org/source/old/0.9.x/openssl-0.9.8zh.tar.gz",
                "f1d9f3ed1b85a82ecf80d0e2d389e1fda3fca9a4dba0bf07adbf231e1a5e2fd6")
    usb = fetch("libusb.deb",
                "https://deb.debian.org/debian/pool/main/libu/libusb/libusb-0.1-4_0.1.12-35+b1_amd64.deb",
                "dffa6c8ff5cd6d26827110556d5dd2e2461bf3a67823f12da52a3d7b616125b9")
    hp = fetch("sp84530.tar", "https://ftp.hp.com/pub/softpaq/sp84501-85000/sp84530.tar",
               "dc9128f965532dd0140d9bcf662ef7a4180ba5fd182c5f8056119c0e967c0364")
    subprocess.run(["dpkg-deb", "-x", str(usb), str(BUILD / "compat")], check=True)
    with tarfile.open(hp) as archive:
        rpm = archive.extractfile("SP84530/Validity-Sensor-Setup-4.5-136.0.x86_64.rpm").read()

    def header_end(offset):
        if rpm[offset:offset + 3] != b"\x8e\xad\xe8":
            raise ValueError("Invalid RPM header")
        count, size = struct.unpack_from(">II", rpm, offset + 8)
        return offset + 16 + count * 16 + size

    # This pinned RPM uses an LZMA-compressed cpio payload.
    payload = lzma.decompress(rpm[header_end((header_end(96) + 7) // 8 * 8):])
    for member in ["usr/bin/vcsFPService", "usr/lib64/libvfsFprintWrapper.so"]:
        result = subprocess.run(["cpio", "-i", "--to-stdout", "./" + member],
                                input=payload, capture_output=True, check=True)
        if not result.stdout.startswith(b"\x7fELF"):
            raise ValueError(f"Missing ELF: {member}")
        (PRIVATE / Path(member).name).write_bytes(result.stdout)

    source = BUILD / "openssl-0.9.8zh"
    if not source.exists():
        with tarfile.open(ssl) as archive:
            archive.extractall(BUILD, filter="data")
    print("Building OpenSSL locally; see build/compat-build.log", flush=True)
    with (BUILD / "compat-build.log").open("w") as log:
        subprocess.run(["perl", "Configure", "linux-x86_64", "shared", "no-asm",
                        "--prefix=/opt/euther-compat"], cwd=source,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
        # Parallel build_libs races libcrypto.a in this historical build system.
        subprocess.run(["make", "-j1", "build_libs"], cwd=source,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    print("Local dependencies ready. No vendor programs started.")


if __name__ == "__main__":
    prepare()
