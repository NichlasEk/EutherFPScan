"""Exercise the guide on a private D-Bus with synthetic status events, no sensor."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
DEVICE = '/net/reactivated/Fprint/Device/0'
BUS = 'net.reactivated.Fprint'
INTERFACE = BUS + '.Device'


def check():
    from gi.repository import Gio, GLib
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    connection.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                         'org.freedesktop.DBus', 'RequestName',
                         GLib.Variant('(su)', (BUS, 0)), None, Gio.DBusCallFlags.NONE, 2000, None)
    xml = '''<node><interface name="net.reactivated.Fprint.Manager">
    <method name="GetDevices"><arg type="ao" direction="out"/></method></interface>
    <interface name="net.reactivated.Fprint.Device">
    <method name="Claim"><arg type="s" direction="in"/></method>
    <method name="Release"/><method name="EnrollStop"/>
    <method name="EnrollStart"><arg type="s" direction="in"/></method>
    <property name="name" type="s" access="read"/>
    <property name="num-enroll-stages" type="i" access="read"/>
    <property name="finger-needed" type="b" access="read"/>
    <signal name="EnrollStatus"><arg type="s"/><arg type="b"/></signal>
    </interface></node>'''
    info = Gio.DBusNodeInfo.new_for_xml(xml)
    state = dict(scenario='success', calls=[], active=False, stage=0)

    def needed(value):
        connection.emit_signal(None, DEVICE, 'org.freedesktop.DBus.Properties',
                               'PropertiesChanged', GLib.Variant('(sa{sv}as)',
                               (INTERFACE, {'finger-needed': GLib.Variant('b', value)}, [])))

    def tick():
        if not state['active']:
            return GLib.SOURCE_REMOVE
        if state['stage'] == 0:
            needed(True)
        else:
            needed(False)
            failed = state['scenario'] == 'error'
            done = failed or state['stage'] == 6
            status = 'enroll-unknown-error' if failed else ('enroll-completed' if done else 'enroll-stage-passed')
            connection.emit_signal(None, DEVICE, INTERFACE, 'EnrollStatus',
                                   GLib.Variant('(sb)', (status, done)))
            if done:
                return GLib.SOURCE_REMOVE
            needed(True)
        state['stage'] += 1
        return GLib.SOURCE_REMOVE if state['scenario'] == 'cancel' else GLib.SOURCE_CONTINUE

    def method(conn, sender, path, interface, name, parameters, invocation):
        state['calls'].append((name, parameters.unpack()))
        if name == 'GetDevices':
            invocation.return_value(GLib.Variant('(ao)', ([DEVICE],)))
            return
        if name == 'EnrollStart':
            state['active'] = True
            state['stage'] = 0
            GLib.timeout_add(100, tick)
        elif name == 'EnrollStop':
            state['active'] = False
        invocation.return_value(GLib.Variant('()', ()))

    def prop(conn, sender, path, interface, name):
        return {'name': GLib.Variant('s', 'EutherFPScan Validity VFS491'),
                'num-enroll-stages': GLib.Variant('i', 6),
                'finger-needed': GLib.Variant('b', False)}[name]

    connection.register_object('/net/reactivated/Fprint/Manager', info.interfaces[0], method, None, None)
    connection.register_object(DEVICE, info.interfaces[1], method, prop, None)
    loop = GLib.MainLoop()
    thread = threading.Thread(target=loop.run)
    thread.start()
    try:
        for scenario in ('success', 'error', 'cancel'):
            state.update(scenario=scenario, calls=[], active=False)
            env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=os.environ['DBUS_SESSION_BUS_ADDRESS'])
            command = [sys.executable, str(ROOT / 'tools/enroll.py'), 'synthetic-user']
            if scenario == 'cancel':
                process = subprocess.Popen(command, env=env, stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                # Wait for the first actual prompt, then exercise Ctrl+C cleanup.
                timer = threading.Timer(8, process.kill)
                timer.start()
                try:
                    process.stdin.write('\n')
                    process.stdin.flush()
                    output = ''
                    while 'Moment 1/6' not in output:
                        line = process.stdout.readline()
                        assert line, output
                        output += line
                    process.send_signal(signal.SIGINT)
                    tail, errors = process.communicate(timeout=5)
                    assert process.returncode == 130, output + tail + errors
                finally:
                    timer.cancel()
                    if process.poll() is None:
                        process.kill()
                    process.communicate()
            else:
                result = subprocess.run(command, env=env, input='\n', capture_output=True, text=True, timeout=8)
                assert result.returncode == (0 if scenario == 'success' else 1), result.stdout + result.stderr
                assert result.stdout.count(': svep HÖGER') == (6 if scenario == 'success' else 1), result.stdout
                assert ('KLART:' in result.stdout) == (scenario == 'success'), result.stdout
            assert ('Claim', ('synthetic-user',)) in state['calls'], state['calls']
            assert ('EnrollStop', ()) in state['calls'], state['calls']
            assert ('Release', ()) in state['calls'], state['calls']
            print(f'Private D-Bus guide test: {scenario} OK')
    finally:
        loop.quit()
        thread.join(timeout=3)


if __name__ == '__main__':
    if sys.argv[1:] == ['--inside']:
        check()
    else:
        os.execvp('dbus-run-session', ['dbus-run-session', '--', sys.executable,
                                     str(Path(__file__).resolve()), '--inside'])
