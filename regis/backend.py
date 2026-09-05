"""Asynchronous fprintd client. Never reads or writes fingerprint templates."""
import getpass
import pwd
from gi.repository import Gio, GLib, GObject

BUS = 'net.reactivated.Fprint'
IFACE = BUS + '.Device'
FINGERS = [(side + '-' + finger, name + ' ' + label)
           for side, name in [('right', 'Höger'), ('left', 'Vänster')]
           for finger, label in [('thumb', 'tumme'), ('index-finger', 'pekfinger'),
                                 ('middle-finger', 'långfinger'), ('ring-finger', 'ringfinger'),
                                 ('little-finger', 'lillfinger')]]
FINGER_NAMES = dict(FINGERS)
RETRY = {'retry-scan': 'Läsningen behöver göras om.',
         'swipe-too-short': 'Svep hela fingerblomman över läsaren.',
         'too-fast': 'Svep lite långsammare och jämnt.',
         'finger-not-centered': 'Centrera fingret över läsaren.',
         'remove-and-retry': 'Lyft fingret helt innan nästa svep.'}


def local_users():
    own = getpass.getuser()
    users = []
    for user in pwd.getpwall():
        if user.pw_name == own or user.pw_uid == 0 or (
                1000 <= user.pw_uid < 65534 and not user.pw_shell.endswith(('nologin', 'false'))):
            users.append({'name': user.pw_name, 'label': user.pw_gecos.split(',')[0] or user.pw_name,
                          'uid': user.pw_uid, 'fingers': None, 'error': None})
    return sorted(users, key=lambda u: (u['name'] != own, u['uid'] == 0, u['name']))


def remote_error(error):
    return Gio.DBusError.get_remote_error(error) or '' if error else ''


def explain(error):
    name = remote_error(error)
    if 'PermissionDenied' in name or 'NotAuthorized' in name:
        return 'Behörighet saknas eller upplåsningen avbröts. Försök igen när du vill.'
    if 'AlreadyInUse' in name:
        return 'Läsaren används av ett annat program. Avsluta det försöket och prova igen.'
    if 'NoSuchDevice' in name or 'ServiceUnknown' in name:
        return 'Läsaren är inte tillgänglig. Kontrollera tjänsten och anslut igen.'
    if 'NoEnrolledPrints' in name:
        return 'Inga fingeravtryck är registrerade för användaren.'
    return 'Åtgärden misslyckades: ' + str(error).split(': ', 1)[-1]


class Registry(GObject.GObject):
    __gsignals__ = {'changed': (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, users=None):
        super().__init__()
        self.users = local_users() if users is None else users
        self.device = None
        self.busy = False
        self.job = None
        self.message = 'Ansluter till läsaren …'
        self.own = getpass.getuser()
        self.stages = 6
        self._generation = 0

    def changed(self):
        self.emit('changed')

    def _call(self, proxy, method, args, callback, interactive=True):
        flags = Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION if interactive else Gio.DBusCallFlags.NONE
        def done(obj, result):
            try:
                value, error = obj.call_finish(result).unpack(), None
            except GLib.Error as exc:
                value, error = None, exc
            callback(value, error)
        proxy.call(method, args, flags, 120000 if interactive else 10000, None, done)

    def connect_device(self):
        if self.busy:
            return
        self.busy = True
        self.message = 'Ansluter till läsaren …'
        self.changed()
        self._generation += 1
        generation = self._generation
        def fail(error):
            self.device = None
            self.busy = False
            self.message = explain(error) if error else 'Ingen EutherFPScan-läsare hittades.'
            self.changed()
        def device_ready(_source, result):
            try:
                device = Gio.DBusProxy.new_for_bus_finish(result)
                name = device.get_cached_property('name')
                if name and name.unpack() == 'EutherFPScan Validity VFS491':
                    self.device = device
                    stages = device.get_cached_property('num-enroll-stages')
                    self.stages = max(1, stages.unpack() if stages else 6)
                    device.connect('g-signal', self._signal)
                    device.connect('g-properties-changed', self._properties)
                    device.connect('notify::g-name-owner', self._owner_changed)
                    self.busy = False
                    self.message = 'Läsaren är ansluten.'
                    self.changed()
                    self.refresh([u for u in self.users if u['name'] == self.own])
                else:
                    next_device()
            except GLib.Error as error:
                fail(error)
        paths = []
        def next_device():
            if generation != self._generation:
                return
            if not paths:
                fail(None)
                return
            Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE,
                                     None, BUS, paths.pop(0), IFACE, None, device_ready)
        def listed(value, error):
            if error:
                fail(error)
            else:
                paths.extend(value[0])
                next_device()
        def manager_ready(_source, result):
            try:
                manager = Gio.DBusProxy.new_for_bus_finish(result)
                self._call(manager, 'GetDevices', None, listed, False)
            except GLib.Error as error:
                fail(error)
        Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None, BUS,
                                 '/net/reactivated/Fprint/Manager', BUS + '.Manager', None, manager_ready)

    def _owner_changed(self, device, _param):
        if device is not self.device or device.get_name_owner():
            return
        self.device = None
        self.message = 'Anslutningen till läsaren bröts. Anslut igen.'
        if self.job:
            job = self.job
            self.job = None
            self.busy = False
            job['done'](False, self.message)
        else:
            self.busy = False
            self.message = 'Registertjänsten vilar eller har avslutats. Tryck Anslut för att hämta aktuella uppgifter.'
        for user in self.users:
            user['fingers'] = None
        self.changed()

    def refresh(self, users=None):
        if self.busy or not self.device:
            return
        queue = list(self.users if users is None else users)
        self.busy = True
        self.message = 'Hämtar register … Systemet kan be om behörighet.'
        self.changed()
        def next_user():
            if not queue or not self.device:
                self.busy = False
                self.changed()
                return
            user = queue.pop(0)
            def listed(value, error):
                if error and 'NoEnrolledPrints' not in remote_error(error):
                    user['fingers'] = None
                    user['error'] = explain(error)
                    self.message = user['error']
                    queue.clear()  # Do not repeat denied admin prompts for every user.
                else:
                    user['fingers'] = list(value[0]) if value else []
                    user['error'] = None
                    self.message = 'Registret är uppdaterat.'
                self.changed()
                next_user()
            username = '' if user['name'] == self.own else user['name']
            self._call(self.device, 'ListEnrolledFingers', GLib.Variant('(s)', (username,)), listed)
        next_user()

    def start(self, mode, user, finger, event, done):
        if self.busy or not self.device:
            raise RuntimeError('Läsaren är upptagen eller frånkopplad.')
        if mode not in ('enroll', 'verify', 'delete') or finger not in FINGER_NAMES:
            raise ValueError('Ogiltig åtgärd eller finger.')
        known = user['fingers']
        if known is None or ((finger in known) != (mode != 'enroll')):
            raise ValueError('Uppdatera registret innan åtgärden startas.')
        job = dict(mode=mode, user=user, finger=finger, event=event, done=done,
                   claimed=False, started=False, pending=True, cancel=False, ending=False,
                   terminal=None, passed=0, attempts=0, prompt=None, needed=False, device=self.device,
                   mutation_sent=False, hint='')
        self.job = job
        self.busy = True
        self.changed()
        event('Väntar på behörighet', 'Följ systemets upplåsningsdialog om den visas.', 0)
        def claimed(_value, error):
            if self.job is not job:
                return
            job['pending'] = False
            if error:
                self._finish(False, explain(error))
                return
            job['claimed'] = True
            if job['cancel']:
                self._finish(False, 'Avbrutet. Lyft fingret från läsaren.')
                return
            job['pending'] = True
            method = {'enroll': 'EnrollStart', 'verify': 'VerifyStart', 'delete': 'DeleteEnrolledFinger'}[mode]
            if mode == 'delete':
                job['mutation_sent'] = True
                event('Raderar avtrycket', 'Begäran har skickats. Vänta på bekräftelsen.', 0)
            def started(_value, error):
                if self.job is not job:
                    return
                job['pending'] = False
                if error:
                    self._finish(False, explain(error))
                    return
                job['started'] = mode != 'delete'
                if job['cancel']:
                    self._finish(False, 'Avbrutet. Lyft fingret från läsaren.')
                elif mode == 'delete':
                    self._finish(True, FINGER_NAMES[finger] + ' har raderats.')
                elif job['terminal']:
                    self._finish(*job['terminal'])
                else:
                    if job['prompt'] is None:
                        event('Förbereder läsaren', 'Vänta med att svepa tills du får besked.', 0)
                    self._prompt()
            self._call(self.device, method, GLib.Variant('(s)', (finger,)), started)
        username = '' if user['name'] == self.own else user['name']
        self._call(self.device, 'Claim', GLib.Variant('(s)', (username,)), claimed)

    def _properties(self, device, changed, _invalidated):
        if self.job and device is self.job['device']:
            values = changed.unpack()
            if 'finger-needed' in values:
                self.job['needed'] = values['finger-needed']
                self._prompt()

    def _prompt(self):
        job = self.job
        if not job or job['ending'] or job['cancel'] or job['terminal'] or not job['needed']:
            return
        token = (job['passed'], job['attempts'])
        if job['prompt'] == token:
            return
        job['prompt'] = token
        count = self.stages if job['mode'] == 'enroll' else 1
        title = f"Svep {FINGER_NAMES[job['finger']].lower()} en gång"
        detail = f"Moment {job['passed'] + 1}/{count}. Lyft sedan fingret helt och vänta på nästa besked."
        if job['hint']:
            detail = job['hint'] + '\n' + detail
        job['event'](title, detail, min(job['passed'] / count, 1))

    def _signal(self, device, _sender, name, parameters):
        job = self.job
        if not job or device is not job['device'] or job['ending'] or job['cancel']:
            return
        if name != {'enroll': 'EnrollStatus', 'verify': 'VerifyStatus', 'delete': ''}[job['mode']]:
            return
        status, done = parameters.unpack()
        prefix = job['mode'] + '-'
        suffix = status[len(prefix):] if status.startswith(prefix) else status
        if done:
            success = status in ('enroll-completed', 'verify-match')
            message = {'enroll-completed': 'Fingeravtrycket är registrerat.',
                       'verify-match': 'Avtrycket stämmer. Identiteten är bekräftad.',
                       'verify-no-match': 'Avtrycket stämmer inte med det registrerade fingret.',
                       'enroll-duplicate': 'Det fingret är redan registrerat. Välj ett annat finger.'}.get(status,
                           'Läsaren kunde inte slutföra åtgärden (' + status + ').')
            self._finish(success, message)
        elif status == 'enroll-stage-passed':
            job['passed'] += 1
            job['hint'] = ''
            job['event']('Godkänt svep', 'Lyft fingret och invänta nästa uppmaning.',
                         min(job['passed'] / self.stages, 1))
            self._prompt()
        elif suffix in RETRY:
            job['attempts'] += 1
            job['hint'] = RETRY[suffix]
            job['event']('Försök igen', RETRY[suffix], job['passed'] / self.stages)
            self._prompt()
        else:
            self._finish(False, 'Oväntat svar från läsaren: ' + status)

    def cancel(self):
        if not self.job or self.job['ending']:
            return
        if self.job['mutation_sent']:
            self.job['event']('Inväntar raderingen', 'Begäran är redan skickad och kan inte återkallas.', 0)
            return
        self.job['cancel'] = True
        self.job['event']('Avbryter …', 'Vänta medan läsaren släpps.', 0)
        self._finish(False, 'Avbrutet. Lyft fingret från läsaren.')

    def _finish(self, success, message):
        job = self.job
        if not job or job['ending']:
            return
        if job['pending']:
            job['terminal'] = (success, message)
            return
        job['ending'] = True
        cleanup_errors = []
        def complete(_value=None, error=None):
            if self.job is not job:
                return
            if error:
                cleanup_errors.append(explain(error))
            self.job = None
            self.busy = False
            if success and job['mode'] in ('enroll', 'delete'):
                job['user']['fingers'] = None
            if cleanup_errors:
                self.message = message + ' Läsaren kunde inte släppas: ' + ' '.join(cleanup_errors)
            else:
                self.message = message
            self.changed()
            job['done'](success and not cleanup_errors, self.message)
        def release(_value=None, error=None):
            if error and 'NoActionInProgress' not in remote_error(error):
                cleanup_errors.append(explain(error))
            if job['claimed']:
                self._call(job['device'], 'Release', None, complete, False)
            else:
                complete()
        if job['started']:
            self._call(job['device'], 'EnrollStop' if job['mode'] == 'enroll' else 'VerifyStop',
                       None, release, False)
        else:
            release()
