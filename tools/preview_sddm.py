#!/usr/bin/env python3
"""Run the Regis SDDM demo without PAM or reader access; optionally save a PNG."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import selectors
import time

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    greeter = shutil.which('sddm-greeter-qt6')
    if not greeter:
        raise SystemExit('sddm-greeter-qt6 is required')
    env = dict(os.environ, QT_QUICK_BACKEND='software', QT_QUICK_CONTROLS_STYLE='Basic')
    with tempfile.TemporaryDirectory(prefix='regis-preview-') as directory:
        theme = Path(directory) / 'theme'
        shutil.copytree(ROOT / 'sddm/regis', theme)
        shutil.copyfile(theme / 'Preview.qml', theme / 'Main.qml')
        if args.screenshot:
            destination = args.screenshot.resolve()
            if '\n' in str(destination) or '\r' in str(destination):
                raise SystemExit('Invalid screenshot path')
            destination.parent.mkdir(parents=True, exist_ok=True)
            (theme / 'theme.conf').write_text('[General]\nscreenshotPath=' + str(destination) + '\n')
            env['QT_QPA_PLATFORM'] = 'offscreen'
        command = [greeter, '--test-mode', '--theme', str(theme)]
        if args.screenshot:
            # The greeter does not connect QML's quit signal. Stop only this
            # child after its capture result, never the running login manager.
            with subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT) as process:
                output = b''
                deadline = time.monotonic() + 20
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        while time.monotonic() < deadline and b'PREVIEW_CAPTURE_OK' not in output:
                            if selector.select(timeout=1):
                                chunk = os.read(process.stdout.fileno(), 65536)
                                if not chunk:
                                    break
                                output += chunk
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                if b'PREVIEW_CAPTURE_OK' not in output or b'Error' in output:
                    raise SystemExit(output.decode(errors='replace'))
            print(destination)
        else:
            subprocess.run(command, env=env, check=True)


if __name__ == '__main__':
    main()
