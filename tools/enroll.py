#!/usr/bin/env python3
"""Swedish live fprintd enrollment guide; no images or templates handled here."""
import argparse
import getpass
import os
import signal

BUS = 'net.reactivated.Fprint'
INTERFACE = BUS + '.Device'
RETRIES = {
    'enroll-retry-scan': 'Läsningen behöver göras om.',
    'enroll-swipe-too-short': 'Svepet var för kort; dra hela fingerblomman över läsaren.',
    'enroll-too-fast': 'Försök med ett långsammare, jämnt svep.',
    'enroll-finger-not-centered': 'Centrera fingerblomman över läsaren.',
    'enroll-remove-and-retry': 'Lyft fingret helt innan du försöker igen.',
}


class Guide:
    def __init__(self, stages, emit=print):
        self.stages = stages
        self.emit = emit
        self.passed = 0
        self.attempt = 0
        self.prompted = None
        self.needed = False
        self.done = False
        self.completed = False

    def finger_needed(self, needed):
        self.needed = needed
        token = (self.passed, self.attempt)
        if needed and not self.done and token != self.prompted:
            self.prompted = token
            self.emit(f'\nMoment {self.passed + 1}/{self.stages}: svep HÖGER PEKFINGER EN gång.')
            self.emit('Lyft sedan fingret helt. Vänta på nästa besked; svep inte kontinuerligt.')

    def status(self, status, done):
        self.done = done
        if status == 'enroll-completed' and done:
            self.completed = True
            self.emit('\nKLART: fprintd bekräftar att fingeravtrycket är registrerat.')
        elif status == 'enroll-stage-passed' and not done:
            self.passed += 1
            self.emit(f'Godkänt moment {self.passed}/{self.stages}. Vänta …')
            self.finger_needed(self.needed)
        elif status in RETRIES and not done:
            self.attempt += 1
            self.emit(RETRIES[status] + ' Momentet behöver göras om.')
            self.finger_needed(self.needed)
        else:
            self.done = True
            self.emit(f'\nSTOPP: registreringen misslyckades ({status}). Sluta svepa.')
            self.emit('Vi behöver granska felet innan nästa försök.')


def enroll(username):
    from gi.repository import Gio, GLib

    def proxy(path, interface):
        return Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE,
                                             None, BUS, path, interface, None)

    def call(device, method, args=None):
        return device.call_sync(method, args, Gio.DBusCallFlags.NONE, 10000, None)

    manager = proxy('/net/reactivated/Fprint/Manager', BUS + '.Manager')
    devices = [proxy(path, INTERFACE) for path in call(manager, 'GetDevices').unpack()[0]]
    devices = [device for device in devices if device.get_cached_property('name').unpack()
               == 'EutherFPScan Validity VFS491']
    if len(devices) != 1:
        raise RuntimeError('Förväntade exakt en EutherFPScan-läsare.')
    device = devices[0]
    stages = device.get_cached_property('num-enroll-stages').unpack()
    if stages < 1 or device.get_cached_property('finger-needed') is None:
        raise RuntimeError('fprintd saknar information för stegvis guidning.')
    guide = Guide(stages, emit=lambda text: print(text, flush=True))
    loop = GLib.MainLoop()
    interrupted = False
    claimed = False
    started = False

    def status_changed(_device, _sender, name, parameters):
        if name == 'EnrollStatus':
            guide.status(*parameters.unpack())
            if guide.done:
                loop.quit()

    def properties_changed(_device, changed, _invalidated):
        values = changed.unpack()
        if 'finger-needed' in values:
            guide.finger_needed(values['finger-needed'])

    def cancel():
        nonlocal interrupted
        interrupted = True
        guide.done = True
        print('\nAvbrutet. Lyft fingret.', flush=True)
        loop.quit()
        return GLib.SOURCE_CONTINUE

    print(f'Registrerar HÖGER PEKFINGER för {username}. fprintd begär {stages} moment.')
    print('En inledande dubblettkontroll kan ingå före de fem registreringssvepen.')
    print('Håll fingret borta tills du får en uppmaning. Ctrl+C avbryter.')
    input('Tryck Enter när du sitter redo … ')
    handlers = [device.connect('g-signal', status_changed),
                device.connect('g-properties-changed', properties_changed)]
    cancel_source = GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, cancel)
    try:
        call(device, 'Claim', GLib.Variant('(s)', (username,)))
        claimed = True
        call(device, 'EnrollStart', GLib.Variant('(s)', ('right-index-finger',)))
        started = True
        if not guide.done:
            loop.run()
        return 130 if interrupted else (0 if guide.completed else 1)
    finally:
        guide.done = True
        GLib.source_remove(cancel_source)
        for handler in handlers:
            device.disconnect(handler)
        if started:
            try:
                call(device, 'EnrollStop')
            except GLib.Error as error:
                print(f'EnrollStop: {error.message}', flush=True)
        if claimed:
            try:
                call(device, 'Release')
            except GLib.Error as error:
                print(f'Release: {error.message}', flush=True)


def main():
    parser = argparse.ArgumentParser(description='Guidad registrering av höger pekfinger.')
    parser.add_argument('username', nargs='?', default=os.environ.get('SUDO_USER') or getpass.getuser())
    args = parser.parse_args()
    try:
        return enroll(args.username)
    except (KeyboardInterrupt, EOFError):
        print('\nAvbrutet.')
        return 130
    except Exception as error:
        print(f'Registreringen kunde inte genomföras: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
