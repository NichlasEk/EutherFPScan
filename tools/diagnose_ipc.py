#!/usr/bin/env python3
"""One guided capture session with payload-free syscall tracing in private/."""
import argparse
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
STRACE = ROOT / 'build/strace-sdk/root/usr/bin/strace'
STRACE_SHA = '69f88291a4e47f258b8e32b089c919a247509f063ef3d6afe5389939051102b3'
RAW = 'read,readv,write,writev,sendto,sendmsg,recvfrom,recvmsg,ioctl'
TRACE = RAW + ',open,openat,close,pipe,pipe2,dup,dup2,dup3,socket,socketpair,connect,accept,accept4,shutdown,exit,exit_group,kill,tgkill'


def trace_args(output):
    if hashlib.sha256(STRACE.read_bytes()).hexdigest() != STRACE_SHA:
        raise RuntimeError('Unexpected strace binary checksum')
    return [str(STRACE), '-f', '-tt', '-s', '128', '--syscall-limit=10000',
            '-e', 'trace=' + TRACE, '-e', 'raw=' + RAW, '-o', str(output)]


def self_test():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'trace'
        code = "import os; r,w=os.pipe(); os.close(r)\ntry: os.write(w,b'PRIVATE_TEST_PAYLOAD')\nexcept BrokenPipeError: pass\nos.write(1,b'PRIVATE_TEST_PAYLOAD')"
        subprocess.run(trace_args(path) + [sys.executable, '-c', code], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        trace = path.read_text()
        assert 'EPIPE' in trace and 'PRIVATE_TEST_PAYLOAD' not in trace, trace
        assert 'write(0x' in trace, trace
    print('Trace self-test passed: EPIPE visible; payload omitted.')


def targets():
    group = subprocess.check_output(['systemctl', 'show', 'eutherfpscan', '-p', 'ControlGroup', '--value'], text=True).strip()
    if not group.startswith('/system.slice/eutherfpscan.service'):
        raise RuntimeError('Unexpected service cgroup')
    pids = Path('/sys/fs/cgroup' + group + '/cgroup.procs').read_text().split()
    result = []
    for pid in pids:
        proc = Path('/proc') / pid
        try:
            name = (proc / 'comm').read_text().strip()
            command = (proc / 'cmdline').read_bytes().split(b'\0')
            if name == 'vcsFPService' or (name == 'python3' and b'--inside' in command):
                result.append(int(pid))
        except FileNotFoundError:
            continue
    if len(result) != 2:
        raise RuntimeError(f'Expected inner supervisor and vendor daemon; found {result}')
    return result


def diagnose(username):
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo')
    trace_args('/dev/null')  # Validate prerequisite before changing service state.
    print('Ett diagnostikförsök: tjänsten startas om, sedan guidar vi svepen.', flush=True)
    print('Spårningen sparar systemanrop och felkoder, inte läs-/skrivbuffertar.', flush=True)
    print('Guiden har högst fyra minuter; avbryt med Ctrl+C vid behov.', flush=True)
    input('Håll fingret borta och tryck Enter när du är redo … ')
    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix='ipc-', dir=ROOT / 'private'))
    tracer = None
    trace_log = None
    try:
        subprocess.run(['systemctl', 'restart', 'eutherfpscan'], check=True, timeout=25)
        deadline = time.monotonic() + 20
        while not Path('/run/eutherfpscan/control.sock').is_socket():
            if time.monotonic() > deadline:
                raise RuntimeError('Service socket did not appear; inspect journal')
            time.sleep(.1)
        pids = targets()
        with (directory / 'fds.txt').open('w') as listing:
            for pid in pids:
                for fd in sorted((Path('/proc') / str(pid) / 'fd').iterdir()):
                    try:
                        listing.write(f'{pid} fd={fd.name} {os.readlink(fd)}\n')
                    except FileNotFoundError:
                        pass
        trace_log = (directory / 'tracer.txt').open('w')
        command = trace_args(directory / 'syscalls.txt')
        for pid in pids:
            command += ['-p', str(pid)]
        tracer = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=trace_log, start_new_session=True)
        deadline = time.monotonic() + 4
        while True:
            attached = all(f'TracerPid:\t{tracer.pid}\n' in Path(f'/proc/{pid}/status').read_text() for pid in pids)
            if attached:
                break
            if tracer.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Tracing could not attach; no capture started')
            time.sleep(.05)
        print('Spårningen är ansluten. Följ nu guidens uppmaningar.', flush=True)
        subprocess.run([sys.executable, str(ROOT / 'tools/enroll.py'), username],
                       input='\n', text=True, timeout=240)
    finally:
        if tracer is not None and tracer.poll() is None:
            tracer.send_signal(signal.SIGINT)  # Attach mode: detach, leave tracees running.
            try:
                tracer.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tracer.kill()
                tracer.wait()
        if trace_log is not None:
            trace_log.close()
        uid = int(os.environ.get('SUDO_UID', '0'))
        gid = int(os.environ.get('SUDO_GID', '0'))
        for path in directory.iterdir():
            os.chmod(path, 0o600)
            os.chown(path, uid, gid)
        os.chown(directory, uid, gid)
        print(f'\nPrivat diagnostik: {directory}', flush=True)
        trace = directory / 'syscalls.txt'
        if trace.exists():
            errors = [line for line in trace.read_text().splitlines()
                      if any(word in line for word in ('EPIPE', 'ECONNRESET', 'ECONNREFUSED', 'SIGPIPE'))]
            print('\n'.join(errors[:30]) or 'Inga EPIPE/reset-rader fångades.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('username', nargs='?', default=os.environ.get('SUDO_USER'))
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        elif args.username:
            diagnose(args.username)
        else:
            parser.error('Specify username')
    except (KeyboardInterrupt, EOFError):
        print('\nAvbrutet.')
        raise SystemExit(130)
    except Exception as error:
        print(f'Diagnostiken avbröts: {error}')
        raise SystemExit(1)
