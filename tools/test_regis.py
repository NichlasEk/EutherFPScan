"""System Regis IV integration tests on a private D-Bus, no real fingerprint data."""
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gi.repository import Gio, GLib
from regis.backend import Registry, IFACE, BUS

DEVICE = '/net/reactivated/Fprint/Device/0'
XML = '''<node><interface name="net.reactivated.Fprint.Manager">
<method name="GetDevices"><arg type="ao" direction="out"/></method></interface>
<interface name="net.reactivated.Fprint.Device">
<method name="ListEnrolledFingers"><arg type="s" direction="in"/><arg type="as" direction="out"/></method>
<method name="Claim"><arg type="s" direction="in"/></method><method name="Release"/>
<method name="EnrollStart"><arg type="s" direction="in"/></method><method name="EnrollStop"/>
<method name="VerifyStart"><arg type="s" direction="in"/></method><method name="VerifyStop"/>
<method name="DeleteEnrolledFinger"><arg type="s" direction="in"/></method>
<property name="name" type="s" access="read"/>
<property name="num-enroll-stages" type="i" access="read"/>
<property name="finger-needed" type="b" access="read"/>
<signal name="EnrollStatus"><arg type="s"/><arg type="b"/></signal>
<signal name="VerifyStatus"><arg type="s"/><arg type="b"/></signal>
</interface></node>'''


def wait_for(predicate):
    deadline = time.monotonic() + 4
    context = GLib.MainContext.default()
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('Asynchronous test timed out')
        context.iteration(False)
        time.sleep(.001)
    while context.pending():
        context.iteration(False)


class RegisTests(unittest.TestCase):
    def setUp(self):
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.connection.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                                  'org.freedesktop.DBus', 'RequestName', GLib.Variant('(su)', (BUS, 0)),
                                  None, Gio.DBusCallFlags.NONE, 2000, None)
        info = Gio.DBusNodeInfo.new_for_xml(XML)
        self.ids = [self.connection.register_object('/net/reactivated/Fprint/Manager', info.interfaces[0], self.method),
                    self.connection.register_object(DEVICE, info.interfaces[1], self.method, self.prop)]
        self.calls = []
        self.data = {'': ['right-index-finger'], 'other': ['left-thumb']}
        self.claimed = None
        self.delay_claim = False
        self.early_result = False
        self.delay_delete = False
        self.deny = False
        self.active = None
        self.registry = Registry(users=[dict(name='tester', label='Tester', uid=1000, fingers=None, error=None),
                                        dict(name='other', label='Other', uid=1001, fingers=None, error=None)])
        self.registry.own = 'tester'
        self.registry.connect_device()
        wait_for(lambda: self.registry.device is not None and not self.registry.busy)

    def tearDown(self):
        if self.registry.job:
            self.registry.cancel()
            wait_for(lambda: not self.registry.busy)
        for identifier in self.ids:
            self.connection.unregister_object(identifier)

    def prop(self, _conn, _sender, _path, _interface, name):
        return {'name': GLib.Variant('s', 'EutherFPScan Validity VFS491'),
                'num-enroll-stages': GLib.Variant('i', 6), 'finger-needed': GLib.Variant('b', False)}[name]

    def method(self, _conn, _sender, _path, _interface, name, params, invocation):
        args = params.unpack()
        self.calls.append((name, args))
        if name == 'GetDevices':
            invocation.return_value(GLib.Variant('(ao)', ([DEVICE],)))
            return
        if self.deny and name in ('ListEnrolledFingers', 'Claim'):
            invocation.return_dbus_error(IFACE.replace('.Device', '') + '.Error.PermissionDenied', 'denied')
            return
        if name == 'ListEnrolledFingers':
            invocation.return_value(GLib.Variant('(as)', (self.data.get(args[0], []),)))
            return
        if name == 'Claim':
            self.claimed = args[0]
            if self.delay_claim:
                def later():
                    invocation.return_value(GLib.Variant('()', ()))
                    return False
                GLib.timeout_add(50, later)
                return
        if name in ('EnrollStart', 'VerifyStart'):
            self.active = name
            self.finger = args[0]
            if self.early_result:
                self.emit('verify-match', True)
                def reply():
                    invocation.return_value(GLib.Variant('()', ()))
                    return False
                GLib.timeout_add(30, reply)
                return
        elif name == 'DeleteEnrolledFinger':
            self.data[self.claimed].remove(args[0])
            if self.delay_delete:
                def reply_delete():
                    invocation.return_value(GLib.Variant('()', ()))
                    return False
                GLib.timeout_add(50, reply_delete)
                return
        elif name.endswith('Stop'):
            self.active = None
        elif name == 'Release':
            self.claimed = None
        invocation.return_value(GLib.Variant('()', ()))

    def emit(self, status, done):
        if status == 'enroll-completed':
            self.data[self.claimed].append(self.finger)
        self.connection.emit_signal(None, DEVICE, IFACE,
                                    'EnrollStatus' if status.startswith('enroll') else 'VerifyStatus',
                                    GLib.Variant('(sb)', (status, done)))

    def needed(self, value):
        self.connection.emit_signal(None, DEVICE, 'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                                    GLib.Variant('(sa{sv}as)', (IFACE, {'finger-needed': GLib.Variant('b', value)}, [])))

    def start(self, mode, finger, user=None):
        self.events, self.results = [], []
        self.registry.start(mode, user or self.registry.users[0], finger,
                            lambda *event: self.events.append(event),
                            lambda *result: self.results.append(result))

    def test_listing_and_single_finger_deletion_for_selected_user(self):
        self.assertEqual(self.registry.users[0]['fingers'], ['right-index-finger'])
        self.assertIsNone(self.registry.users[1]['fingers'])
        self.registry.refresh()
        wait_for(lambda: not self.registry.busy)
        self.start('delete', 'left-thumb', self.registry.users[1])
        wait_for(lambda: bool(self.results))
        self.assertTrue(self.results[0][0])
        self.assertEqual(self.data[''], ['right-index-finger'])
        self.assertEqual(self.data['other'], [])
        self.assertIn(('Claim', ('other',)), self.calls)
        self.assertIn(('DeleteEnrolledFinger', ('left-thumb',)), self.calls)
        self.assertEqual(self.calls[-1][0], 'Release')

    def test_enrollment_progress_retry_and_cleanup(self):
        self.start('enroll', 'left-index-finger')
        wait_for(lambda: self.active == 'EnrollStart' and not self.registry.job['pending'])
        for index in range(6):
            self.needed(True)
            wait_for(lambda: len([e for e in self.events if e[0].startswith('Svep')]) >= index + 1)
            self.needed(False)
            self.emit('enroll-stage-passed' if index < 5 else 'enroll-completed', index == 5)
            if index < 5:
                wait_for(lambda: self.registry.job['passed'] == index + 1)
        wait_for(lambda: bool(self.results))
        self.assertTrue(self.results[0][0])
        self.assertIn('left-index-finger', self.data[''])
        self.assertEqual([name for name, _ in self.calls][-2:], ['EnrollStop', 'Release'])

    def test_match_and_nonmatch(self):
        for outcome, success in [('verify-match', True), ('verify-no-match', False)]:
            self.start('verify', 'right-index-finger')
            wait_for(lambda: self.active == 'VerifyStart' and not self.registry.job['pending'])
            self.emit(outcome, True)
            wait_for(lambda: bool(self.results))
            self.assertEqual(self.results[0][0], success)
            self.assertEqual([name for name, _ in self.calls][-2:], ['VerifyStop', 'Release'])

    def test_cancel_during_authorization_never_starts_capture(self):
        self.delay_claim = True
        self.start('enroll', 'left-thumb')
        self.registry.cancel()
        wait_for(lambda: bool(self.results))
        self.assertFalse(self.results[0][0])
        self.assertNotIn('EnrollStart', [name for name, _ in self.calls])
        self.assertEqual(self.calls[-1][0], 'Release')

    def test_cancel_live_capture_then_new_verification(self):
        self.start('verify', 'right-index-finger')
        wait_for(lambda: self.active == 'VerifyStart' and not self.registry.job['pending'])
        self.registry.cancel()
        wait_for(lambda: bool(self.results))
        self.assertFalse(self.results[0][0])
        self.test_match_and_nonmatch()

    def test_denial_is_not_reported_as_empty_registry(self):
        self.deny = True
        self.registry.refresh([self.registry.users[1]])
        wait_for(lambda: not self.registry.busy)
        self.assertIsNone(self.registry.users[1]['fingers'])
        self.assertIsNotNone(self.registry.users[1]['error'])
        self.start('enroll', 'left-thumb')
        wait_for(lambda: bool(self.results))
        self.assertFalse(self.results[0][0])
        self.assertNotIn('EnrollStart', [name for name, _ in self.calls])

    def test_terminal_signal_before_method_reply_still_stops_and_releases(self):
        self.early_result = True
        self.start('verify', 'right-index-finger')
        wait_for(lambda: bool(self.results))
        self.assertTrue(self.results[0][0])
        self.assertEqual([name for name, _ in self.calls][-2:], ['VerifyStop', 'Release'])

    def test_existing_finger_cannot_be_overwritten_by_enroll(self):
        count = len(self.calls)
        with self.assertRaises(ValueError):
            self.start('enroll', 'right-index-finger')
        self.assertEqual(len(self.calls), count)

    def test_sent_deletion_is_not_falsely_reported_as_cancelled(self):
        self.delay_delete = True
        self.start('delete', 'right-index-finger')
        wait_for(lambda: any(name == 'DeleteEnrolledFinger' for name, _ in self.calls))
        self.registry.cancel()
        wait_for(lambda: bool(self.results))
        self.assertTrue(self.results[0][0])
        self.assertEqual(self.data[''], [])
        self.assertEqual(self.calls[-1][0], 'Release')

    @unittest.skipUnless(os.environ.get('EUTHER_TEST_GUI') == '1', 'Set EUTHER_TEST_GUI=1 on a desktop')
    def test_graphical_prompt_cancel_and_delete_confirmation(self):
        from regis.ui import RegisWindow, Gtk
        app = Gtk.Application(application_id='se.euther.RegisTests', flags=Gio.ApplicationFlags.NON_UNIQUE)
        app.register(None)
        window = RegisWindow(app, self.registry)
        try:
            self.assertTrue(window.verify_button.get_sensitive())
            self.assertFalse(window.enroll_button.get_sensitive())
            window.confirm_delete()
            confirmation = next(w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.MessageDialog))
            confirmation.response(Gtk.ResponseType.CANCEL)
            self.assertEqual(self.data[''], ['right-index-finger'])
            self.assertNotIn('DeleteEnrolledFinger', [name for name, _ in self.calls])
            window.begin('verify')
            window.dialog.response(Gtk.ResponseType.ACCEPT)
            wait_for(lambda: self.active == 'VerifyStart' and not self.registry.job['pending'])
            self.needed(True)
            def prompt_visible():
                return any(isinstance(w, Gtk.Label) and 'Svep höger pekfinger' in w.get_text()
                           for w in window.dialog.get_content_area().get_children())
            wait_for(prompt_visible)
            window.dialog.response(Gtk.ResponseType.CANCEL)
            wait_for(lambda: self.registry.job is None)
            window.dialog.response(Gtk.ResponseType.CANCEL)
            self.assertIsNone(window.dialog)
            window.confirm_delete()
            confirmation = next(w for w in Gtk.Window.list_toplevels() if isinstance(w, Gtk.MessageDialog))
            confirmation.response(Gtk.ResponseType.ACCEPT)
            wait_for(lambda: self.registry.job is None and not self.registry.busy and self.data[''] == [])
            self.assertFalse(window.verify_button.get_sensitive())
            self.assertTrue(window.enroll_button.get_sensitive())
            window.dialog.response(Gtk.ResponseType.CANCEL)
        finally:
            if self.registry.job:
                self.registry.cancel()
                wait_for(lambda: self.registry.job is None)
            for widget in Gtk.Window.list_toplevels():
                widget.destroy()
            app.quit()


if __name__ == '__main__':
    if sys.argv[1:] == ['--inside']:
        os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = os.environ['DBUS_SESSION_BUS_ADDRESS']
        unittest.main(argv=[sys.argv[0]], verbosity=2)
    else:
        os.execvp('dbus-run-session', ['dbus-run-session', '--', sys.executable, str(Path(__file__).resolve()), '--inside'])
