"""Build a private libfprint 1.94.9 with the Euther image driver (Debian 13 amd64)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tarfile

from prepare_compat import BUILD, ROOT, fetch

PACKAGES = [
    "meson", "ninja-build", "libglib2.0-dev", "libglib2.0-dev-bin",
    "libgio-2.0-dev", "libgio-2.0-dev-bin", "libgusb-dev", "libusb-1.0-0-dev",
    "libjson-glib-dev", "libpcre2-dev", "libffi-dev", "libmount-dev", "libblkid-dev",
    "libselinux1-dev", "libsepol-dev", "zlib1g-dev", "libsysprof-capture-4-dev",
]


def build():
    BUILD.mkdir(exist_ok=True)
    debs = BUILD / "sdk-debs"
    sdk = BUILD / "sdk"
    debs.mkdir(exist_ok=True)
    sdk.mkdir(exist_ok=True)
    if not (sdk / ".ready").exists():
        subprocess.run(["apt-get", "download", *PACKAGES], cwd=debs, check=True)
        for deb in sorted(debs.glob("*.deb")):
            subprocess.run(["dpkg-deb", "-x", str(deb), str(sdk)], check=True)
        for pc in sdk.rglob("*.pc"):
            pc.write_text(pc.read_text().replace("prefix=/usr", f"prefix={sdk}/usr"))
        # Development symlinks refer to the existing Debian runtime libraries.
        for link in (sdk / "usr/lib/x86_64-linux-gnu").glob("*.so"):
            if link.is_symlink() and not link.exists():
                target = Path("/usr/lib/x86_64-linux-gnu") / link.readlink()
                if target.exists():
                    link.unlink()
                    link.symlink_to(target)
        manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(debs.glob("*.deb"))}
        (BUILD / "sdk-packages.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (sdk / ".ready").touch()
    archive = fetch("libfprint-1.94.9.tar.xz",
                    "https://deb.debian.org/debian/pool/main/libf/libfprint/libfprint_1.94.9.orig.tar.xz",
                    "0af811e8b70e8e27d711d0b50d4e628c4092332a1a7e25927ab1b1726b0b515f")
    source = BUILD / "libfprint-src"
    if not source.exists():
        with tarfile.open(archive) as tar:
            tar.extractall(BUILD / "libfprint-unpack", filter="data")
        shutil.move(BUILD / "libfprint-unpack/libfprint-1.94.9", source)
    for relative, before, after in [
        ("meson.build", "virtual_drivers = [", "virtual_drivers = [\n    'euther_vfs491',"),
        ("libfprint/meson.build", "driver_sources = {",
         "driver_sources = {\n    'euther_vfs491': ['drivers/euther_vfs491.c'],"),
    ]:
        path = source / relative
        text = path.read_text()
        if after not in text:
            if text.count(before) != 1:
                raise ValueError(f"Unexpected upstream build file: {relative}")
            path.write_text(text.replace(before, after))
    shutil.copy2(ROOT / "libfprint/euther_vfs491.c", source / "libfprint/drivers/euther_vfs491.c")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(sdk / "usr/lib/python3/dist-packages")
    env["PATH"] = str(sdk / "usr/bin") + os.pathsep + env["PATH"]
    env["PKG_CONFIG_PATH"] = ":".join(str(sdk / p) for p in (
        "usr/lib/x86_64-linux-gnu/pkgconfig", "usr/share/pkgconfig"))
    output = BUILD / "libfprint-build"
    with (BUILD / "libfprint-build.log").open("w") as log:
        command = ["python3", "-m", "mesonbuild.mesonmain", "setup"]
        if (output / "build.ninja").exists():
            command.append("--reconfigure")
        command += [str(output), str(source), "-Ddrivers=euther_vfs491", "-Ddoc=false",
                    "-Dintrospection=false", "-Dinstalled-tests=false", "-Dudev_rules=disabled",
                    "-Dudev_hwdb=disabled"]
        subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["ninja", "-C", str(output), "-j2"], env=env,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
        # Meson's install step strips build RUNPATHs. Never install a library
        # for root fprintd that searches a user-writable SDK directory.
        stage = BUILD / "libfprint-stage"
        subprocess.run(["python3", "-m", "mesonbuild.mesonmain", "install", "-C", str(output),
                        "--destdir", str(stage), "--no-rebuild", "--tags", "runtime"], env=env,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
        libraries = list(stage.rglob("libfprint-2.so.2.0.0"))
        if len(libraries) != 1:
            raise RuntimeError("Unexpected staged library layout")
        runtime = BUILD / "libfprint-runtime"
        runtime.mkdir(exist_ok=True)
        shutil.copy2(libraries[0], runtime / libraries[0].name)
        link = runtime / "libfprint-2.so.2"
        link.unlink(missing_ok=True)
        link.symlink_to(libraries[0].name)
        dynamic = subprocess.check_output(["readelf", "-d", str(libraries[0])], text=True)
        if "RPATH" in dynamic or "RUNPATH" in dynamic:
            raise RuntimeError("Staged library still has a runtime search path")
        flags = shlex.split(subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "gio-unix-2.0"], env=env, text=True))
        subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", str(ROOT / "libfprint/check.c"),
                        "-I" + str(source), "-I" + str(output), "-I" + str(output / "libfprint"),
                        "-L" + str(output / "libfprint"),
                        "-Wl,-rpath," + str(output / "libfprint"), "-lfprint-2", *flags,
                        "-o", str(BUILD / "fprint-check")], env=env,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    print("Private libfprint build ready; system libfprint and PAM are unchanged.")


if __name__ == "__main__":
    build()
